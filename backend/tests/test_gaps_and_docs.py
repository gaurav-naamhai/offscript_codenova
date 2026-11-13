"""Tests for backend gaps: flag recheck, guideline_refs list, accept resolution safety, colour contrast, X-Actor audit tracking, and docs endpoints."""

import io
from app.models import Flag, FlagDraft, GuidelineRef


def test_docs_and_openapi_endpoints_return_200(client):
    docs_res = client.get("/docs")
    assert docs_res.status_code == 200
    assert "swagger" in docs_res.text.lower() or "html" in docs_res.text.lower()

    openapi_res = client.get("/openapi.json")
    assert openapi_res.status_code == 200
    data = openapi_res.json()
    assert data["info"]["title"] == "Inkloom Compliance API"
    assert "/health" in data["paths"]
    assert "/tools/contrast" in data["paths"]


def test_flag_guideline_refs_multi_support():
    ref1 = GuidelineRef(
        document="Doc 1", passage_ref="Sec 1", excerpt="Exc 1"
    )
    ref2 = GuidelineRef(
        document="Doc 2", passage_ref="Sec 2", excerpt="Exc 2"
    )

    # Multi-reference flag
    flag = FlagDraft(
        finding_type="brand",
        state="aligned",
        passage="Passage text",
        location="line 1",
        explanation="Brand match",
        why_it_matters="Voice",
        guideline_refs=[ref1, ref2],
        origin="fixture",
    )
    assert len(flag.guideline_refs) == 2
    # Syncs to guideline_ref
    assert flag.guideline_ref == ref1

    # Single reference flag backwards compatibility
    flag_single = FlagDraft(
        finding_type="claim",
        state="supported",
        passage="SLA uptime",
        location="p1",
        explanation="Verified",
        why_it_matters="Integrity",
        guideline_ref=ref1,
        origin="fixture",
    )
    assert flag_single.guideline_ref == ref1
    assert flag_single.guideline_refs == [ref1]


def test_recheck_flag_text_submission_success(client):
    passage = "100% infallible serverless performance."
    correction = "99.9% targeted availability."
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": f"Here is our promise: {passage} Thank you.",
        },
    )
    sub_id = res.json()["id"]

    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flags = check_res.json()["flags"]
    target_flag = flags[0]
    target_flag["passage"] = passage
    target_flag["suggested_correction"] = correction

    app_repo = client.app.state.repo
    import asyncio
    asyncio.run(app_repo.update_flag(sub_id, Flag(**target_flag)))

    # Call recheck
    recheck_res = client.post(
        f"/submissions/{sub_id}/flags/{target_flag['id']}/recheck",
        json={"role": "creator"},
        headers={"X-Actor": "reviewer_alice"},
    )
    assert recheck_res.status_code == 200
    data = recheck_res.json()
    assert "new_flags" in data
    assert "original_flag_gone" in data
    assert "has_needs_human" in data
    assert data["original_flag_gone"] is True

    # Confirm original submission text was NOT changed (without saving)
    detail_res = client.get(f"/submissions/{sub_id}")
    assert passage in detail_res.json()["submission"]["text"]

    # Verify audit event has action recheck and custom actor
    audit_res = client.get(f"/submissions/{sub_id}/audit")
    events = audit_res.json()
    recheck_event = next(e for e in events if e["action"] == "recheck")
    assert recheck_event["actor"] == "reviewer_alice"


def test_recheck_flag_non_text_returns_400(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    res = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("img.png", io.BytesIO(png_bytes), "image/png")},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    detail = client.get(f"/submissions/{sub_id}").json()
    flag_id = detail["flags"][0]["id"]

    recheck_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/recheck",
        json={"role": "creator"},
    )
    assert recheck_res.status_code == 400
    assert recheck_res.json()["error"]["code"] == "bad_request"
    assert "only supported for text" in recheck_res.json()["error"]["message"]


def test_recheck_flag_wrong_role_returns_403(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Some sample text"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    detail = client.get(f"/submissions/{sub_id}").json()
    flag_id = detail["flags"][0]["id"]

    recheck_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/recheck",
        json={"role": "manager"},
    )
    assert recheck_res.status_code == 403
    assert recheck_res.json()["error"]["code"] == "forbidden"


def test_accept_resolution_safety_passage_not_found_returns_409(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Original text without target"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    detail = client.get(f"/submissions/{sub_id}").json()
    flag = detail["flags"][0]

    # Flag passage is not in the submission text
    flag["passage"] = "Text that definitely does not exist in the submission"
    flag["suggested_correction"] = "Something else"

    app_repo = client.app.state.repo
    import asyncio
    asyncio.run(app_repo.update_flag(sub_id, Flag(**flag)))

    res_accept = client.post(
        f"/submissions/{sub_id}/flags/{flag['id']}/resolution",
        json={"action": "accept", "role": "creator"},
    )
    assert res_accept.status_code == 409
    data = res_accept.json()
    assert data["error"]["code"] == "conflict"
    assert "was not found" in data["error"]["message"]


def test_tools_contrast_wcag_known_values(client):
    # Black on White -> exactly 21.0
    res = client.get("/tools/contrast?fg=%23000000&bg=%23FFFFFF")
    assert res.status_code == 200
    data = res.json()
    assert data["contrast_ratio"] == 21.0
    assert data["aa_normal"] is True
    assert data["aa_large"] is True
    assert data["aaa_normal"] is True

    # White on White -> 1.0
    res_white = client.get("/tools/contrast?fg=ffffff&bg=ffffff")
    assert res_white.status_code == 200
    assert res_white.json()["contrast_ratio"] == 1.0
    assert res_white.json()["aa_normal"] is False

    # Standard accessible blue on white
    res_blue = client.get("/tools/contrast?fg=0055aa&bg=ffffff")
    assert res_blue.status_code == 200
    assert res_blue.json()["contrast_ratio"] >= 4.5


def test_tools_contrast_invalid_hex_returns_422(client):
    # Invalid character
    res1 = client.get("/tools/contrast?fg=ZZZZZZ&bg=000000")
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] in {"validation_error", "unprocessable_entity"}

    # Invalid length
    res2 = client.get("/tools/contrast?fg=12&bg=000000")
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] in {"validation_error", "unprocessable_entity"}


def test_audit_event_x_actor_header(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft for actor test"},
        headers={"X-Actor": "gaurav_jha"},
    )
    sub_id = res.json()["id"]

    audit_res = client.get(f"/submissions/{sub_id}/audit")
    events = audit_res.json()
    create_event = next(e for e in events if e["action"] == "created")
    assert create_event["actor_role"] == "creator"
    assert create_event["actor"] == "gaurav_jha"

    # Without header -> defaults to actor_role
    client.post(
        f"/submissions/{sub_id}/comments",
        json={"role": "manager", "text": "Comment without actor header"},
    )
    events2 = client.get(f"/submissions/{sub_id}/audit").json()
    comment_event = next(e for e in events2 if e["action"] == "comment_added")
    assert comment_event["actor"] == "manager"
