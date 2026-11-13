"""Tests for request_changes transition bumping version and allowing re-checks."""


def test_manager_request_changes_bumps_version_and_allows_recheck(client):
    # 1. Create initial draft (version 1)
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Initial copy version 1.",
        },
    )
    sub_id = res.json()["id"]
    assert res.json()["version"] == 1
    assert res.json()["status"] == "draft"

    # 2. Check moves to manager_review
    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert check_res.status_code == 200
    assert check_res.json()["submission"]["status"] == "manager_review"
    assert check_res.json()["submission"]["version"] == 1

    # 3. Add a comment from manager
    comment_res = client.post(
        f"/submissions/{sub_id}/comments",
        json={"role": "manager", "text": "Please soften the claim in paragraph 1."},
    )
    assert comment_res.status_code == 201
    assert comment_res.json()["version"] == 1

    # 4. Manager requests changes
    dec_res = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "role": "manager",
            "decision": "request_changes",
            "comment": "Needs clarification.",
        },
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["decision"] == "request_changes"
    assert dec_res.json()["version"] == 2

    # Check updated submission status and version
    detail_res = client.get(f"/submissions/{sub_id}")
    sub = detail_res.json()["submission"]
    assert sub["status"] == "draft"
    assert sub["version"] == 2

    # 5. Creator re-checks version 2
    recheck_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert recheck_res.status_code == 200
    assert recheck_res.json()["submission"]["status"] == "manager_review"
    assert recheck_res.json()["submission"]["version"] == 2


def test_reviewer_request_changes_bumps_version_and_allows_recheck(client):
    # Setup up to final_approval
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Draft for final review.",
        },
    )
    sub_id = res.json()["id"]

    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "approve"},
    )

    detail_res = client.get(f"/submissions/{sub_id}")
    assert detail_res.json()["submission"]["status"] == "final_approval"
    assert detail_res.json()["submission"]["version"] == 1

    # Reviewer requests changes
    dec_res = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "role": "authorised_reviewer",
            "decision": "request_changes",
            "comment": "Legal review requires citation tweak.",
        },
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["version"] == 2

    detail_res2 = client.get(f"/submissions/{sub_id}")
    assert detail_res2.json()["submission"]["status"] == "draft"
    assert detail_res2.json()["submission"]["version"] == 2

    # Creator can re-check again
    recheck_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert recheck_res.status_code == 200
    assert recheck_res.json()["submission"]["status"] == "manager_review"

