"""Regression checks for current-version readiness and honest guideline retrieval."""

from datetime import datetime, timezone

import pytest

from app.models import ContentPayload, Decision, Flag, Submission
from app.pipeline import run_pipeline
from app.review_state import current_review_state
from retrieval import brand_rag
from retrieval.schemas import ContentPayload as RetrievalPayload


NOW = datetime.now(timezone.utc).isoformat()


def _submission(status="draft", version=1, stage=None):
    return Submission(
        id="synthetic-submission", content_type="text", role="creator", status=status,
        version=version, text="Synthetic claim: our product cures every illness.",
        processing_stage=stage, created_at=NOW, updated_at=NOW,
    )


def _flag(version=1, state="contradicted", origin="module"):
    return Flag(
        id="synthetic-finding", submission_id="synthetic-submission", version=version,
        finding_type="claim", origin=origin, state=state, location="line 1",
        passage="our product cures every illness", explanation="Unsupported synthetic claim",
        why_it_matters="The claim needs evidence before publication.",
        created_at=NOW,
    )


def test_unchecked_and_running_versions_never_inherit_previous_findings():
    old_finding = _flag(version=1)
    assert current_review_state(_submission(version=2), [old_finding]) == "not_checked"
    assert current_review_state(_submission(status="ai_review", version=2, stage="extracting"), [old_finding]) == "review_in_progress"
    assert current_review_state(_submission(status="draft", version=2, stage="failed"), []) == "review_incomplete"


def test_checked_blockers_and_overrides_remain_distinct():
    checked = _submission(status="manager_review", stage="completed")
    assert current_review_state(checked, [_flag()]) == "changes_required"
    approved = _submission(status="approved", stage="completed")
    override = Decision(
        id="synthetic-decision", submission_id=approved.id, role="authorised_reviewer",
        decision="approve", override_unresolved=True,
        override_reason="Synthetic test justification", version=1, created_at=NOW,
    )
    assert current_review_state(approved, [_flag()], [override]) == "approved_with_override"
    assert current_review_state(approved.model_copy(update={"version": 2}), [_flag()], [override]) == "approved_for_publication"


def test_request_changes_creates_unchecked_version_with_no_scores(client):
    created = client.post("/submissions", data={
        "content_type": "text", "role": "creator",
        "text": "Synthetic claim: our product cures every illness.",
    })
    assert created.status_code == 201
    sub_id = created.json()["id"]
    assert client.post(f"/submissions/{sub_id}/check", json={"role": "creator"}).status_code == 200
    decision = client.post(f"/submissions/{sub_id}/decision", json={
        "role": "manager", "decision": "request_changes", "comment": "Check the claim.",
    })
    assert decision.status_code == 200
    detail = client.get(f"/submissions/{sub_id}").json()
    assert detail["submission"]["version"] == 2
    assert "cures every illness" in detail["submission"]["text"]
    assert detail["readiness_status"] == "not_checked"
    assert detail["brand_score"] is None and detail["fact_score"] is None
    summary = next(item for item in client.get("/submissions").json() if item["id"] == sub_id)
    assert summary["readiness_status"] == "not_checked"
    assert summary["flag_count"] == 0


def test_empty_org_guidelines_differ_from_retrieval_failure(monkeypatch):
    monkeypatch.setattr(brand_rag, "list_brand_docs", lambda *args, **kwargs: [])
    payload = RetrievalPayload(content_type="text", text="Synthetic copy", org_id="nike")
    assert brand_rag.retrieve_guidelines(payload, org_id="nike") == []

    def unavailable(*args, **kwargs):
        raise ConnectionError("Synthetic vector store outage")

    monkeypatch.setattr(brand_rag, "list_brand_docs", unavailable)
    with pytest.raises(ConnectionError):
        brand_rag.retrieve_guidelines(payload, org_id="nike")

    def brand_check_must_not_run(*args, **kwargs):
        raise AssertionError("Brand check must not misreport an empty workspace")

    flags, degraded = run_pipeline(
        ContentPayload(content_type="text", text="Synthetic copy", org_id="nike"),
        "synthetic-submission", 1,
        retrieval_fn=lambda _: unavailable(),
        verification_fn=lambda _: [],
        brand_check_fn=brand_check_must_not_run,
    )
    assert [module.module for module in degraded] == ["retrieval"]
    assert len(flags) == 1 and flags[0].origin == "error"


def test_retrieval_failure_is_incomplete_and_cannot_be_approved(client, monkeypatch):
    from app.pipeline import retrieval

    def unavailable(_):
        raise ConnectionError("Synthetic retrieval outage")

    monkeypatch.setattr(retrieval, "retrieve_guidelines", unavailable)
    created = client.post("/submissions", data={
        "content_type": "text", "role": "creator", "text": "Synthetic draft claim.",
    })
    sub_id = created.json()["id"]
    checked = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert checked.status_code == 200
    assert checked.json()["readiness_status"] == "review_incomplete"
    detail = client.get(f"/submissions/{sub_id}").json()
    assert detail["readiness_status"] == "review_incomplete"
    assert detail["brand_score"] is None and detail["fact_score"] is None
    assert any(flag["origin"] == "error" for flag in detail["flags"])
    approval = client.post(f"/submissions/{sub_id}/decision", json={
        "role": "manager", "decision": "approve",
    })
    assert approval.status_code == 409
