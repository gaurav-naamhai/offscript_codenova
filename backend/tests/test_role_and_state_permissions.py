"""Tests for state and role permission enforcement (403 and 409 errors)."""


def test_check_wrong_role_returns_403(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]

    for invalid_role in ["manager", "authorised_reviewer", "admin"]:
        check_res = client.post(
            f"/submissions/{sub_id}/check",
            json={"role": invalid_role},
        )
        assert check_res.status_code == 403
        assert check_res.json()["error"]["code"] == "forbidden"


def test_check_wrong_state_returns_409(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]

    # First check succeeds -> moves to manager_review
    res1 = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert res1.status_code == 200

    # Second check while in manager_review -> 409
    res2 = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "conflict"
    assert "manager_review" in res2.json()["error"]["message"]


def test_decision_in_draft_state_returns_409(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]

    for role in ["manager", "authorised_reviewer", "creator"]:
        dec_res = client.post(
            f"/submissions/{sub_id}/decision",
            json={"role": role, "decision": "approve"},
        )
        assert dec_res.status_code == 409
        assert dec_res.json()["error"]["code"] == "conflict"


def test_decision_in_approved_state_returns_409(client):
    # Progress to approved
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "approve"},
    )
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "authorised_reviewer", "decision": "approve"},
    )

    # Any decision in approved state returns 409
    for role in ["manager", "authorised_reviewer", "creator"]:
        dec_res = client.post(
            f"/submissions/{sub_id}/decision",
            json={"role": role, "decision": "approve"},
        )
        assert dec_res.status_code == 409
        assert dec_res.json()["error"]["code"] == "conflict"


def test_decision_in_manager_review_wrong_role_returns_403(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    # In manager_review, role must be manager. Others -> 403
    for invalid_role in ["creator", "authorised_reviewer", "guest"]:
        dec_res = client.post(
            f"/submissions/{sub_id}/decision",
            json={"role": invalid_role, "decision": "approve"},
        )
        assert dec_res.status_code == 403
        assert dec_res.json()["error"]["code"] == "forbidden"


def test_decision_in_final_approval_wrong_role_returns_403(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "approve"},
    )

    # In final_approval, role must be authorised_reviewer. Others -> 403
    for invalid_role in ["creator", "manager", "admin"]:
        dec_res = client.post(
            f"/submissions/{sub_id}/decision",
            json={"role": invalid_role, "decision": "approve"},
        )
        assert dec_res.status_code == 403
        assert dec_res.json()["error"]["code"] == "forbidden"


def test_invalid_decision_action_returns_422(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    dec_res = client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "reject"},  # must be approve or request_changes
    )
    assert dec_res.status_code == 422
    assert dec_res.json()["error"]["code"] == "unprocessable_entity"

