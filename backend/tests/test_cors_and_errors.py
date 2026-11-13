"""Tests for CORS origin restrictions and unified JSON error envelope formatting."""


def test_cors_allows_configured_origin(client):
    headers = {
        "Origin": "http://allowed.test",
        "Access-Control-Request-Method": "GET",
    }
    response = client.options("/health", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "http://allowed.test"


def test_cors_allows_configured_origin_with_stripped_slash(client):
    headers = {
        "Origin": "http://app.test",
        "Access-Control-Request-Method": "GET",
    }
    response = client.options("/health", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "http://app.test"


def test_cors_blocks_unauthorized_origin(client):
    headers = {
        "Origin": "http://unauthorized-domain.com",
        "Access-Control-Request-Method": "GET",
    }
    response = client.options("/health", headers=headers)
    assert "access-control-allow-origin" not in response.headers


def test_error_envelope_404(client):
    response = client.get("/submissions/does-not-exist")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"
    assert "message" in data["error"]
    assert "Traceback" not in response.text


def test_error_envelope_403(client):
    response = client.post(
        "/submissions",
        data={"content_type": "text", "role": "manager", "text": "Hello"},
    )
    assert response.status_code == 403
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "forbidden"
    assert "message" in data["error"]
    assert "Traceback" not in response.text


def test_error_envelope_409(client):
    # Create draft
    res = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "Draft"},
    )
    sub_id = res.json()["id"]

    # First check moves to manager_review
    client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})

    # Second check is 409
    response = client.post(f"/submissions/{sub_id}/check", json={"role": "creator"})
    assert response.status_code == 409
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "conflict"
    assert "message" in data["error"]
    assert "Traceback" not in response.text


def test_error_envelope_422_pydantic_validation(client):
    # Invalid JSON body structure for decision endpoint
    response = client.post(
        "/submissions/any-id/decision",
        content="not-even-valid-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    assert "message" in data["error"]
    assert "Traceback" not in response.text

