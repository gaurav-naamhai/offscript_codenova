"""Tests for plugin failure handling and explicit error flags."""

from app.models import ContentPayload
from app.pipeline import run_pipeline


def test_pipeline_catches_exceptions_and_generates_error_flags():
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

    assert len(degraded) == 3
    modules = {d.module: d.error for d in degraded}
    assert modules["retrieval"] == "ConnectionError"
    assert modules["verification"] == "RuntimeError"
    assert modules["brand_check"] == "ValueError"

    # Explicit failure flags produced, no fixture flags
    assert len(flags) == 3
    for flag in flags:
        assert flag.origin == "error"
        assert flag.needs_human is True
        assert flag.passage == "(whole submission)"
        assert "Automated check failed" in flag.explanation

    types = {f.finding_type: f.state for f in flags}
    assert "claim" in types
    assert "brand" in types


def test_pipeline_catches_malformed_returns_and_generates_error_flags():
    content = ContentPayload(content_type="text", text="Sample draft content")

    flags, degraded = run_pipeline(
        content=content,
        submission_id="sub-456",
        retrieval_fn=lambda c: "invalid string return",
        verification_fn=lambda c: [{"invalid": "dict"}],
        brand_check_fn=lambda c, g: None,
    )

    assert len(degraded) == 3
    for d in degraded:
        assert d.error == "TypeError"

    assert len(flags) == 3
    for flag in flags:
        assert flag.origin == "error"
        assert flag.needs_human is True


def test_retrieval_failure_still_runs_other_modules():
    content = ContentPayload(
        content_type="text",
        text="Our product is the fastest in the world with 99.9% uptime.",
    )

    def failing_retrieval(c):
        raise ConnectionError("DB offline")

    flags, degraded = run_pipeline(
        content=content,
        submission_id="sub-789",
        retrieval_fn=failing_retrieval,
    )

    assert len(degraded) == 1
    assert degraded[0].module == "retrieval"
    # Retrieval failed -> produced 1 error flag; verification and brand_check still ran on the text!
    origins = [f.origin for f in flags]
    assert "error" in origins
    assert "fixture" in origins
    assert any(f.finding_type == "claim" and f.origin == "fixture" for f in flags)


def test_check_endpoint_with_degraded_modules_records_audit_event(client, monkeypatch):
    import app.pipeline

    def broken_retrieval(c):
        raise TimeoutError("Retrieval timed out")

    monkeypatch.setattr(app.pipeline.retrieval, "retrieve_guidelines", broken_retrieval)

    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft with error"},
    )
    sub_id = res.json()["id"]

    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert check_res.status_code == 200
    check_data = check_res.json()

    assert len(check_data["degraded_modules"]) == 1
    assert check_data["degraded_modules"][0]["module"] == "retrieval"
    assert check_data["degraded_modules"][0]["error"] == "TimeoutError"
    assert any(f["origin"] == "error" for f in check_data["flags"])

    audit_res = client.get(f"/submissions/{sub_id}/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()
    actions = [e["action"] for e in events]
    assert "module_fallback" in actions

    fallback_event = next(e for e in events if e["action"] == "module_fallback")
    assert "retrieval: TimeoutError" in fallback_event["detail"]
    assert fallback_event["actor_role"] == "creator"
