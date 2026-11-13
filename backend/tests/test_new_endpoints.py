"""Tests for new endpoints: list submissions, revise, file download, flag resolution, versioning, insights, disclosures, and demo seed."""

import io
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ContentPayload, FlagDraft
from app.pipeline import run_pipeline
from app.repository import InMemorySubmissionRepository


def test_list_submissions_newest_first_and_status_filter(client):
    # Create two submissions
    r1 = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "First"},
    )
    r2 = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Second"},
    )
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]

    # Check second to move it to manager_review
    client.post(f"/submissions/{id2}/check", json={"role": "creator"})

    # List all
    list_res = client.get("/submissions")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 2
    # Newest first: id2 before id1
    ids = [i["id"] for i in items]
    assert ids.index(id2) < ids.index(id1)

    # Filter by draft status
    draft_res = client.get("/submissions?status=draft")
    assert draft_res.status_code == 200
    draft_ids = [i["id"] for i in draft_res.json()]
    assert id1 in draft_ids
    assert id2 not in draft_ids

    # Verify counts on id2
    id2_item = next(i for i in items if i["id"] == id2)
    assert id2_item["flag_count"] == 2
    assert "needs_human_count" in id2_item


def test_revise_submission_text(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Initial text"},
    )
    sub_id = res.json()["id"]

    # Revise text
    rev_res = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "role": "creator", "text": "Revised text"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["text"] == "Revised text"

    # Verify audit event "revised"
    audit_res = client.get(f"/submissions/{sub_id}/audit")
    actions = [e["action"] for e in audit_res.json()]
    assert "revised" in actions


def test_revise_submission_permissions_and_state(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Initial text"},
    )
    sub_id = res.json()["id"]

    # Non-creator cannot revise
    for r in ["manager", "authorised_reviewer"]:
        rev_fail = client.post(
            f"/submissions/{sub_id}/revise",
            data={"content_type": "text", "role": r, "text": "Hacked"},
        )
        assert rev_fail.status_code == 403

    # Move to manager_review -> cannot revise (must be draft)
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    rev_state_fail = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "role": "creator", "text": "After check"},
    )
    assert rev_state_fail.status_code == 409
    assert rev_state_fail.json()["error"]["code"] == "conflict"


def test_get_submission_file_and_404_on_text(client):
    # Text submission -> 404 on /file
    t_res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Hello world"},
    )
    t_id = t_res.json()["id"]
    file_404 = client.get(f"/submissions/{t_id}/file")
    assert file_404.status_code == 404
    assert file_404.json()["error"]["code"] == "not_found"

    # Image submission -> returns file bytes and media type
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    img_res = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("logo.png", io.BytesIO(png_bytes), "image/png")},
    )
    img_id = img_res.json()["id"]
    file_ok = client.get(f"/submissions/{img_id}/file")
    assert file_ok.status_code == 200
    assert file_ok.content == png_bytes
    assert "image/png" in file_ok.headers.get("content-type", "")


def test_flag_resolution_accept_applies_correction(client):
    # Create submission with text containing passage
    passage = "We guarantee 100% zero downtime always."
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": f"Introduction. {passage} Conclusion.",
        },
    )
    sub_id = res.json()["id"]

    # Run check
    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flags = check_res.json()["flags"]
    target_flag = flags[0]

    # Inject passage and suggested correction on target flag for test
    target_flag["passage"] = passage
    target_flag["suggested_correction"] = "We offer 99.9% target uptime SLA."

    # Update in repo
    from app.models import Flag
    app_repo = client.app.state.repo
    import asyncio
    asyncio.run(app_repo.update_flag(sub_id, Flag(**target_flag)))

    # Resolve with accept
    res_accept = client.post(
        f"/submissions/{sub_id}/flags/{target_flag['id']}/resolution",
        json={
            "action": "accept",
            "comment": "Accepted suggested SLA wording.",
            "role": "creator",
        },
    )
    assert res_accept.status_code == 200
    resolved = res_accept.json()
    assert resolved["status"] == "accepted"
    assert "Accepted suggested SLA wording." in resolved["comments"]

    # Verify text was updated in submission
    detail = client.get(f"/submissions/{sub_id}").json()
    assert "We offer 99.9% target uptime SLA." in detail["submission"]["text"]
    assert passage not in detail["submission"]["text"]

    # Verify audit event
    audit_res = client.get(f"/submissions/{sub_id}/audit")
    actions = [e["action"] for e in audit_res.json()]
    assert "flag_resolved" in actions


def test_flag_resolution_dismiss_and_permissions(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft text"},
    )
    sub_id = res.json()["id"]
    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flag_id = check_res.json()["flags"][0]["id"]

    # Non-creator cannot resolve
    fail_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/resolution",
        json={"action": "dismiss", "role": "manager"},
    )
    assert fail_res.status_code == 403

    # Dismiss by creator
    dismiss_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/resolution",
        json={"action": "dismiss", "comment": "Intentional wording."},
    )
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["status"] == "dismissed"


def test_versions_preservation_and_query_by_version(client):
    # v1
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Version 1 text"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    # Manager requests changes -> bumps to v2
    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "request_changes"},
    )

    # v2 check
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    # Versions list endpoint
    versions_res = client.get(f"/submissions/{sub_id}/versions")
    assert versions_res.status_code == 200
    v_items = versions_res.json()
    version_numbers = [v["version"] for v in v_items]
    assert 1 in version_numbers
    assert 2 in version_numbers

    # Query specific version: ?version=1
    v1_detail = client.get(f"/submissions/{sub_id}?version=1").json()
    assert len(v1_detail["flags"]) == 2
    for f in v1_detail["flags"]:
        assert f["version"] == 1

    # Query ?version=2
    v2_detail = client.get(f"/submissions/{sub_id}?version=2").json()
    assert len(v2_detail["flags"]) == 2
    for f in v2_detail["flags"]:
        assert f["version"] == 2


def test_recurring_insights_endpoint(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft for insights"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    insights_res = client.get("/insights/recurring")
    assert insights_res.status_code == 200
    data = insights_res.json()
    assert "top_guidelines" in data
    assert "state_counts" in data
    assert data["total_flags"] >= 2
    assert isinstance(data["top_guidelines"], list)
    assert "aligned" in data["state_counts"]
    assert "supported" in data["state_counts"]


def test_disclosures_endpoint(client):
    res = client.get("/disclosures")
    assert res.status_code == 200
    data = res.json()
    assert "external_services" in data
    assert "human_in_the_loop_notice" in data
    assert "human decision" in data["human_in_the_loop_notice"].lower()
    services = [s["service_id"] for s in data["external_services"]]
    assert "gemini" in services
    assert "supabase" in services


def test_demo_seed_disabled_by_default(client):
    res = client.post("/demo/seed")
    assert res.status_code == 403
    assert "Demo mode is disabled" in res.json()["error"]["message"]


def test_demo_seed_enabled(repo):
    demo_settings = Settings(demo_mode=True, repo_backend="memory")
    demo_app = create_app(repo=repo, settings=demo_settings)
    demo_client = TestClient(demo_app)

    res = demo_client.post("/demo/seed")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert len(data["submissions"]) == 3

    statuses = [s["status"] for s in data["submissions"]]
    assert "draft" in statuses
    assert "manager_review" in statuses
    assert "approved" in statuses


def test_cors_wildcard_for_local_development(repo):
    dev_settings = Settings(frontend_origin="*")
    dev_app = create_app(repo=repo, settings=dev_settings)
    dev_client = TestClient(dev_app)

    headers = {
        "Origin": "http://anything.local:5173",
        "Access-Control-Request-Method": "GET",
    }
    response = dev_client.options("/health", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "*"

