"""Tests for plugin failure and malformed return fallbacks."""

from app.models import ContentPayload, FlagDraft
from app.pipeline import run_pipeline


def test_pipeline_catches_exceptions_and_falls_back():
    content = ContentPayload(content_type="text", text="Sample draft content")

    def failing_retrieval(c):
        raise ConnectionError("Vector store unreachable")

    def failing_verification(c):
        raise RuntimeError("TinySearch rate limited")

    def failing_brand_check(c, g):
        raise ValueError("Model format corrupted")

    flags, degraded = run_pipeline(
        content=content,
        submission_id="sub-123",
        retrieval_fn=failing_retrieval,
        verification_fn=failing_verification,
        brand_check_fn=failing_brand_check,
    )

    # 3 degraded modules recorded with exception type only
    assert len(degraded) == 3
    modules = {d.module: d.error for d in degraded}
    assert modules["retrieval"] == "ConnectionError"
    assert modules["verification"] == "RuntimeError"
    assert modules["brand_check"] == "ValueError"

    # All flags successfully recovered via fallback fixtures
    assert len(flags) == 2
    for flag in flags:
        assert flag.origin == "fixture"
        assert flag.submission_id == "sub-123"


def test_pipeline_catches_malformed_returns_and_falls_back():
    content = ContentPayload(content_type="text", text="Sample draft content")

    # Malformed: returns string instead of list[GuidelineRef]
    def bad_retrieval(c):
        return "invalid string return"

    # Malformed: returns list containing non-FlagDraft item
    def bad_verification(c):
        return [{"invalid": "dict"}]

    # Malformed: returns None
    def bad_brand_check(c, g):
        return None

    flags, degraded = run_pipeline(
        content=content,
        submission_id="sub-456",
        retrieval_fn=bad_retrieval,
        verification_fn=bad_verification,
        brand_check_fn=bad_brand_check,
    )

    assert len(degraded) == 3
    for d in degraded:
        assert d.error == "TypeError"

    assert len(flags) == 2
    for flag in flags:
        assert flag.origin == "fixture"


def test_check_endpoint_with_degraded_modules_records_audit_event(client, monkeypatch):
    import app.pipeline

    def broken_retrieval(c):
        raise TimeoutError("Retrieval timed out")

    monkeypatch.setattr(app.pipeline.retrieval, "retrieve_guidelines", broken_retrieval)

    # Create submission
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft with error"},
    )
    sub_id = res.json()["id"]

    # Run check
    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert check_res.status_code == 200
    check_data = check_res.json()

    assert len(check_data["degraded_modules"]) == 1
    assert check_data["degraded_modules"][0]["module"] == "retrieval"
    assert check_data["degraded_modules"][0]["error"] == "TimeoutError"
    assert len(check_data["flags"]) == 2

    # Check audit trail includes module_fallback event
    audit_res = client.get(f"/submissions/{sub_id}/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()
    actions = [e["action"] for e in events]
    assert "module_fallback" in actions

    fallback_event = next(e for e in events if e["action"] == "module_fallback")
    assert "retrieval: TimeoutError" in fallback_event["detail"]
    assert fallback_event["actor_role"] == "creator"

