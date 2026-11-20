"""Regression tests for unchecked versions, overrides, stale jobs, and guideline publication."""

import io
import threading
import time
import uuid

import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Flag
from app.repository import InMemorySubmissionRepository
from retrieval.brand_rag import (
    clear_local_brand_store,
    get_org_active_chunks,
    list_brand_doc_events,
    list_brand_docs,
    list_brand_doc_versions,
)
from retrieval import brand_rag


def _client():
    repo = InMemorySubmissionRepository()
    app = create_app(repo=repo, settings=Settings(
        frontend_origin="*", repo_backend="memory", require_auth=True,
        enforce_approval_gates=True, mock_ai=True, auth_secret="governance-test-secret",
    ))
    return TestClient(app)


def _auth(client, email, password="inkloom123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create(client, creator, text="This cure is guaranteed to treat every disease."):
    response = client.post("/submissions", data={"content_type": "text", "text": text}, headers=creator)
    assert response.status_code == 201
    return response.json()["id"]


def test_false_claim_draft_has_no_safety_or_confidence_and_request_changes_invalidates_check():
    client = _client()
    creator = _auth(client, "creator@inkloom.ai")
    manager = _auth(client, "manager@inkloom.ai")
    sub_id = _create(client, creator)
    initial = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert initial["readiness_status"] == "not_checked"
    assert initial["brand_score"] is None and initial["fact_score"] is None
    assert client.get("/submissions", headers=creator).json()[0]["readiness_status"] == "not_checked"
    report = client.get(f"/submissions/{sub_id}/certificate", headers=creator).json()
    assert report["certificate_type"] == "review_status_report"
    assert report["publication_status"] == "not_checked"
    assert report["scores"]["fact_confidence_score"] is None

    checked = client.post(f"/submissions/{sub_id}/check", json={}, headers=creator)
    assert checked.status_code == 200
    changed = client.post(f"/submissions/{sub_id}/decision", json={
        "decision": "request_changes", "comment": "Correct this unsupported promise."
    }, headers=manager)
    assert changed.status_code == 200
    draft = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert draft["submission"]["version"] == 2
    assert draft["submission"]["processing_stage"] is None
    assert draft["readiness_status"] == "not_checked"
    assert draft["flags"] == []
    assert draft["brand_score"] is None and draft["fact_score"] is None


def test_approval_override_discloses_risks_and_edit_invalidates_it():
    client = _client()
    creator = _auth(client, "creator@inkloom.ai")
    manager = _auth(client, "manager@inkloom.ai")
    reviewer = _auth(client, "reviewer@inkloom.ai")
    sub_id = _create(client, creator, "Our tool brings disruptive synergy.")
    checked = client.post(f"/submissions/{sub_id}/check", json={}, headers=creator).json()
    assert checked["unresolved_blocking_count"] > 0
    for actor, reason in ((manager, "Manager accepts documented campaign risk."),
                          (reviewer, "Final reviewer accepts documented risk.")):
        approved = client.post(f"/submissions/{sub_id}/decision", json={
            "decision": "approve", "override_unresolved": True, "override_reason": reason,
        }, headers=actor)
        assert approved.status_code == 200, approved.text
    detail = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert detail["readiness_status"] == "approved_with_override"
    certificate = client.get(f"/submissions/{sub_id}/certificate", headers=creator).json()
    assert certificate["publication_status"] == "approved_with_override"
    assert certificate["remaining_risks"]
    assert len(certificate["override_justifications"]) == 2
    assert certificate["scores"]["score_kind"] == "heuristic_indicator_not_probability"

    edited = client.post(f"/submissions/{sub_id}/revise", data={
        "content_type": "text", "text": "This new unchecked claim guarantees results."
    }, headers=creator)
    assert edited.status_code == 200
    current = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert current["submission"]["version"] == 2
    assert current["readiness_status"] == "not_checked"
    assert current["brand_score"] is None
    assert client.get(f"/submissions/{sub_id}/certificate", headers=creator).json()["certificate_type"] == "review_status_report"


def test_older_async_job_cannot_publish_results_to_new_version(monkeypatch):
    client = _client()
    creator = _auth(client, "creator@inkloom.ai")
    sub_id = _create(client, creator)
    started, release = threading.Event(), threading.Event()

    def slow_pipeline(*_args, **_kwargs):
        started.set()
        assert release.wait(5)
        return [], []

    monkeypatch.setattr("app.main.run_pipeline", slow_pipeline)
    first = client.post(f"/submissions/{sub_id}/check", json={"async_mode": True}, headers=creator)
    assert first.status_code == 200
    assert started.wait(2)
    duplicate = client.post(f"/submissions/{sub_id}/check", json={"async_mode": True}, headers=creator)
    assert duplicate.status_code == 409
    assert client.post(f"/submissions/{sub_id}/retry-check", json={}, headers=creator).status_code == 409
    revised = client.post(f"/submissions/{sub_id}/revise", data={
        "content_type": "text", "text": "A newly edited unchecked version.", "create_new_version": "true"
    }, headers=creator)
    assert revised.status_code == 200, revised.text
    release.set()
    for _ in range(50):
        audit = client.get(f"/submissions/{sub_id}/audit", headers=creator).json()
        if any(event["action"] == "stale_check_discarded" for event in audit):
            break
        time.sleep(0.02)
    current = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert current["submission"]["version"] == 2
    assert current["submission"]["status"] == "draft"
    assert current["readiness_status"] == "not_checked"
    assert current["flags"] == []
    assert any(event["action"] == "stale_check_discarded" for event in audit)


def test_accepting_correction_creates_unchecked_version_and_old_finding_cannot_be_reused(monkeypatch):
    client = _client()
    creator = _auth(client, "creator@inkloom.ai")
    sub_id = _create(client, creator, "Welcome to MailChimp. A claim remains unchecked.")
    flag_id = str(uuid.uuid4())

    def synthetic_pipeline(_content, submission_id, version, *_args):
        return [Flag(
            id=flag_id, submission_id=submission_id, version=version,
            finding_type="brand", state="potential_issue", passage="MailChimp",
            location="sentence 1", explanation="Brand spelling", why_it_matters="Use approved spelling",
            suggested_correction="Mailchimp", created_at="2026-11-19T00:00:00Z",
        )], []

    monkeypatch.setattr("app.main.run_pipeline", synthetic_pipeline)
    assert client.post(f"/submissions/{sub_id}/check", json={}, headers=creator).status_code == 200
    accepted = client.post(f"/submissions/{sub_id}/flags/{flag_id}/resolution", json={"action": "accept"}, headers=creator)
    assert accepted.status_code == 200, accepted.text
    current = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert current["submission"]["version"] == 2
    assert current["submission"]["text"] == "Welcome to Mailchimp. A claim remains unchecked."
    assert current["readiness_status"] == "not_checked"
    assert current["flags"] == []
    assert client.post(f"/submissions/{sub_id}/flags/{flag_id}/resolution", json={"action": "dismiss"}, headers=creator).status_code == 409


def test_incomplete_check_cannot_be_approved_even_with_override(monkeypatch):
    client = _client()
    creator = _auth(client, "creator@inkloom.ai")
    manager = _auth(client, "manager@inkloom.ai")
    sub_id = _create(client, creator)

    def incomplete_pipeline(_content, submission_id, version, *_args):
        return [Flag(
            id=str(uuid.uuid4()), submission_id=submission_id, version=version,
            finding_type="brand", state="unclear", origin="error", passage="",
            location="whole submission", explanation="Evidence provider unavailable",
            why_it_matters="The check did not finish", created_at="2026-11-19T00:00:00Z",
        )], []

    monkeypatch.setattr("app.main.run_pipeline", incomplete_pipeline)
    assert client.post(f"/submissions/{sub_id}/check", json={}, headers=creator).status_code == 200
    detail = client.get(f"/submissions/{sub_id}", headers=creator).json()
    assert detail["readiness_status"] == "review_incomplete"
    assert detail["brand_score"] is None
    decision = client.post(f"/submissions/{sub_id}/decision", json={
        "decision": "approve", "override_unresolved": True,
        "override_reason": "Attempted override despite an incomplete check.",
    }, headers=manager)
    assert decision.status_code == 409


def test_stale_rectifications_and_duplicate_publication_are_rejected():
    clear_local_brand_store()
    client = _client()
    manager = _auth(client, "manager@brightleaf.co", "brightleaf123")
    content = ("Tone: Always use an appropriate tone as needed.\n\n"
               "Claims: Use reasonable claims where possible.\n\n"
               "Expiry: Summer 2024 offer ended in 2024.").encode()
    upload = client.post("/brand-docs", data={"title": "Publication Rules"},
                         files={"file": ("rules.txt", io.BytesIO(content), "text/plain")}, headers=manager)
    assert upload.status_code == 201, upload.text
    source = upload.json()
    scan = client.post("/brand-docs/rectifications/scan", headers=manager)
    assert scan.status_code == 200
    proposals = [r for r in scan.json()["rectifications"] if r["document_id"] == source["id"]]
    assert len(proposals) >= 2
    first, second = proposals[:2]
    approved = client.post(f"/brand-docs/rectifications/{first['id']}/approve", json={
        "approved_wording": "Use clear, measured language and cite all factual claims."
    }, headers=manager)
    assert approved.status_code == 200, approved.text
    new_doc = approved.json()["new_document"]
    assert new_doc["family_id"] == source["family_id"]
    assert new_doc["revision"] == source["revision"] + 1
    assert new_doc["version"] == "1.1"
    assert client.post(f"/brand-docs/rectifications/{first['id']}/approve", json={}, headers=manager).status_code == 409
    assert client.post(f"/brand-docs/rectifications/{second['id']}/approve", json={}, headers=manager).status_code == 409
    listed = client.get("/brand-docs/rectifications", headers=manager).json()["rectifications"]
    assert next(r for r in listed if r["id"] == second["id"])["status"] == "stale"
    active = [d for d in list_brand_docs(org_id="brightleaf") if d["family_id"] == source["family_id"]]
    assert len(active) == 1 and active[0]["id"] == new_doc["id"]
    history = list_brand_doc_versions(new_doc["id"], org_id="brightleaf")
    assert len(history) == 2 and {d["is_active"] for d in history} == {True, False}
    assert len(list_brand_doc_events(new_doc["id"], "brightleaf")) == 2
    assert all(chunk["document_id"] == new_doc["id"] for chunk in get_org_active_chunks("brightleaf"))


def test_existing_duplicate_active_family_fails_closed_without_erasing_history():
    clear_local_brand_store()
    from retrieval.brand_rag import ingest_brand_doc
    first = ingest_brand_doc(b"Use clear language.", "rules.txt", "Rules", org_id="inkloom")
    duplicate = dict(brand_rag._LOCAL_DOCS[first.id])
    duplicate["id"] = str(uuid.uuid4())
    duplicate["revision"] = 2
    brand_rag._LOCAL_DOCS[duplicate["id"]] = duplicate
    with pytest.raises(ValueError, match="Multiple active"):
        list_brand_docs(org_id="inkloom")
    assert brand_rag._LOCAL_DOCS[first.id]["is_active"] is True
    assert brand_rag._LOCAL_DOCS[duplicate["id"]]["is_active"] is True
    clear_local_brand_store()
