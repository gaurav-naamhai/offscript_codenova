"""Tests for audit trail recording and verification."""


def test_audit_trail_captures_all_events(client, monkeypatch):
    import app.pipeline

    # Cause one module to fallback to verify module_fallback in audit
    def failing_retrieval(c):
        raise ConnectionResetError("Remote server closed connection")

    monkeypatch.setattr(app.pipeline.retrieval, "retrieve_guidelines", failing_retrieval)

    # 1. Created event
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft for audit testing"},
    )
    sub_id = res.json()["id"]

    # 2. Check (triggers check_started, module_fallback, check_completed)
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    # 3. Comment added event
    client.post(
        f"/submissions/{sub_id}/comments",
        json={"role": "manager", "text": "Looks decent overall."},
    )

    # 4. Decision recorded event
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "approve"},
    )

    # Fetch audit
    audit_res = client.get(f"/submissions/{sub_id}/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()

    # Verify all expected action types are present
    action_types = [e["action"] for e in events]
    expected_actions = [
        "created",
        "check_started",
        "module_fallback",
        "check_completed",
        "comment_added",
        "decision_recorded",
    ]
    for action in expected_actions:
        assert action in action_types, f"Action '{action}' missing from audit events"

    # Verify event structure
    for event in events:
        assert "actor_role" in event
        assert "action" in event
        assert "detail" in event
        assert "timestamp" in event
        assert event["actor_role"] in {"creator", "manager", "authorised_reviewer"}


def test_audit_404_for_unknown_submission(client):
    res = client.get("/submissions/non-existent-sub-id/audit")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"

