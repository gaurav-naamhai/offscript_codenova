"""Test full lifecycle path: creator submit -> check -> manager approve -> reviewer approve -> approved."""


def test_full_approval_lifecycle(client):
    # 1. Creator creates submission
    create_res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Inkloom AI ensures enterprise brand compliance with precision.",
        },
    )
    assert create_res.status_code == 201
    sub_id = create_res.json()["id"]
    assert create_res.json()["status"] == "draft"
    assert create_res.json()["version"] == 1

    # 2. Creator triggers check
    check_res = client.post(
        f"/submissions/{sub_id}/check",
        json={"role": "creator"},
    )
    assert check_res.status_code == 200
    check_data = check_res.json()
    assert check_data["submission"]["status"] == "manager_review"
    assert len(check_data["flags"]) == 2
    assert check_data["degraded_modules"] == []

    # 3. Verify GET /submissions/{id}
    detail_res = client.get(f"/submissions/{sub_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["submission"]["status"] == "manager_review"
    assert len(detail_data["flags"]) == 2
    assert detail_data["decisions"] == []
    assert detail_data["comments"] == []

    # 4. Manager reviews and approves -> final_approval
    mgr_dec_res = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "role": "manager",
            "decision": "approve",
            "comment": "Brand alignment looks good.",
        },
    )
    assert mgr_dec_res.status_code == 200
    mgr_dec = mgr_dec_res.json()
    assert mgr_dec["role"] == "manager"
    assert mgr_dec["decision"] == "approve"
    assert mgr_dec["comment"] == "Brand alignment looks good."
    assert mgr_dec["version"] == 1

    # Verify status changed to final_approval
    status_res1 = client.get(f"/submissions/{sub_id}")
    assert status_res1.json()["submission"]["status"] == "final_approval"

    # 5. Authorised reviewer approves -> approved
    rev_dec_res = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "role": "authorised_reviewer",
            "decision": "approve",
            "comment": "Final sign-off granted.",
        },
    )
    assert rev_dec_res.status_code == 200
    rev_dec = rev_dec_res.json()
    assert rev_dec["role"] == "authorised_reviewer"
    assert rev_dec["decision"] == "approve"
    assert rev_dec["version"] == 1

    # Verify final status is approved
    final_res = client.get(f"/submissions/{sub_id}")
    final_data = final_res.json()
    assert final_data["submission"]["status"] == "approved"
    assert len(final_data["decisions"]) == 2

