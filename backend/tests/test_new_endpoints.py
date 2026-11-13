"""Tests for newly introduced endpoints and extended capabilities."""

import asyncio
import io
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Submission
from app.repository import InMemorySubmissionRepository


def test_list_submissions_newest_first_and_status_filter(client):
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

    client.post(f"/submissions/{id2}/check", json={"role": "creator"})

    list_res = client.get("/submissions")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 2
    ids = [i["id"] for i in items]
    assert ids.index(id2) < ids.index(id1)

    filtered_res = client.get("/submissions?status=manager_review")
    assert filtered_res.status_code == 200
    filtered_items = filtered_res.json()
    assert len(filtered_items) == 1
    assert filtered_items[0]["id"] == id2
    assert filtered_items[0]["status"] == "manager_review"


def test_revise_submission_text(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Initial text"},
    )
    sub_id = res.json()["id"]

    rev_res = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "role": "creator", "text": "Revised draft"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["text"] == "Revised draft"

    detail = client.get(f"/submissions/{sub_id}").json()
    assert detail["submission"]["text"] == "Revised draft"


def test_revise_submission_permissions_and_state(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft for lock"},
    )
    sub_id = res.json()["id"]

    res_403 = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "role": "manager", "text": "Illegal edit"},
    )
    assert res_403.status_code == 403

    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    res_409 = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "role": "creator", "text": "Illegal state edit"},
    )
    assert res_409.status_code == 409


def test_get_submission_file_and_404_on_text(client):
    t_res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Hello world"},
    )
    t_id = t_res.json()["id"]
    file_404 = client.get(f"/submissions/{t_id}/file")
    assert file_404.status_code == 404
    assert file_404.json()["error"]["code"] == "not_found"

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


def test_text_aware_flags_and_resolution_accept(client):
    text = "Our platform is fastest in the world."
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": text},
    )
    sub_id = res.json()["id"]

    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flags = check_res.json()["flags"]
    assert len(flags) >= 1

    fastest_flag = next((f for f in flags if f["passage"] == "fastest"), None)
    assert fastest_flag is not None
    assert fastest_flag["suggested_correction"] is not None

    resolve_res = client.post(
        f"/submissions/{sub_id}/flags/{fastest_flag['id']}/resolution",
        json={"action": "accept", "role": "creator"},
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "accepted"

    detail = client.get(f"/submissions/{sub_id}").json()
    assert fastest_flag["suggested_correction"] in detail["submission"]["text"]
    assert "fastest" not in detail["submission"]["text"]


def test_image_pdf_placeholder_flags_are_unclear_and_needs_human(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    img_res = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("asset.png", io.BytesIO(png_bytes), "image/png")},
    )
    sub_id = img_res.json()["id"]

    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flags = check_res.json()["flags"]
    assert len(flags) >= 2
    for f in flags:
        assert f["state"] == "unclear"
        assert f["needs_human"] is True
        assert f["passage"] == ""


def test_flag_resolution_on_image_does_not_alter_bytes(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    img_res = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("diagram.png", io.BytesIO(png_bytes), "image/png")},
    )
    sub_id = img_res.json()["id"]
    check_res = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flag_id = check_res.json()["flags"][0]["id"]

    # Accept flag on image
    accept_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/resolution",
        json={"action": "accept", "role": "creator"},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "accepted"

    file_res = client.get(f"/submissions/{sub_id}/file")
    assert file_res.content == png_bytes

    # Dismiss flag on image
    dismiss_res = client.post(
        f"/submissions/{sub_id}/flags/{flag_id}/resolution",
        json={"action": "dismiss", "role": "creator"},
    )
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["status"] == "dismissed"

    file_res2 = client.get(f"/submissions/{sub_id}/file")
    assert file_res2.content == png_bytes


def test_flag_resolution_dismiss_and_permissions(client):
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft content"},
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    flags = client.get(f"/submissions/{sub_id}").json()["flags"]
    target_id = flags[0]["id"]

    non_creator = client.post(
        f"/submissions/{sub_id}/flags/{target_id}/resolution",
        json={"action": "dismiss", "role": "manager"},
    )
    assert non_creator.status_code == 403

    dismiss_res = client.post(
        f"/submissions/{sub_id}/flags/{target_id}/resolution",
        json={"action": "dismiss", "role": "creator", "comment": "Will not fix"},
    )
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["status"] == "dismissed"
    assert "Will not fix" in dismiss_res.json()["comments"]


def test_versions_preservation_and_query_by_version(client):
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Our product is fastest in the world.",
        },
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "request_changes"},
    )
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    versions_res = client.get(f"/submissions/{sub_id}/versions")
    assert versions_res.status_code == 200
    v_items = versions_res.json()
    version_numbers = [v["version"] for v in v_items]
    assert 1 in version_numbers and 2 in version_numbers

    v1_detail = client.get(f"/submissions/{sub_id}?version=1").json()
    assert len(v1_detail["flags"]) >= 1
    for f in v1_detail["flags"]:
        assert f["version"] == 1

    v2_detail = client.get(f"/submissions/{sub_id}?version=2").json()
    assert len(v2_detail["flags"]) >= 1
    for f in v2_detail["flags"]:
        assert f["version"] == 2


def test_recurring_insights_endpoint(client):
    res = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Our product is fastest in the world with 99.9% uptime.",
        },
    )
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    insights_res = client.get("/insights/recurring")
    assert insights_res.status_code == 200
    data = insights_res.json()
    assert "top_guidelines" in data
    assert "state_counts" in data
    assert data["total_flags"] >= 1
    assert isinstance(data["top_guidelines"], list)


def test_disclosures_endpoint(client):
    res = client.get("/disclosures")
    assert res.status_code == 200
    data = res.json()
    assert "external_services" in data
    assert "human_in_the_loop_notice" in data
    assert "human decision" in data["human_in_the_loop_notice"].lower()
    assert data["services_enabled"] == []
    for s in data["external_services"]:
        assert s["enabled"] is False


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


def test_memory_cap_eviction():
    repo = InMemorySubmissionRepository(max_submissions=5)

    async def _populate():
        for i in range(10):
            sub = Submission(
                id=f"sub-{i}",
                content_type="text",
                role="creator",
                created_at=f"2026-11-13T10:00:0{i}Z",
                updated_at=f"2026-11-13T10:00:0{i}Z",
            )
            await repo.create_submission(sub)

    asyncio.run(_populate())
    assert len(repo._submissions) == 5
    for i in range(5):
        assert f"sub-{i}" not in repo._submissions
    for i in range(5, 10):
        assert f"sub-{i}" in repo._submissions
