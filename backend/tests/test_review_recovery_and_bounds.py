"""Regression coverage for responsive auth, abandoned jobs, and bounded provider calls."""

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.ai.client import GeminiClient, GeminiAPIError
from app.config import Settings
from app.main import create_app
from app.models import ContentPayload
from app.pipeline import run_pipeline
from app.repository import InMemorySubmissionRepository


def _app():
    repo = InMemorySubmissionRepository()
    app = create_app(repo=repo, settings=Settings(mock_ai=True, repo_backend="memory", auth_secret="recovery-test-secret"))
    return TestClient(app), repo


def _creator(client):
    response = client.post("/auth/login", json={"email": "creator@inkloom.ai", "password": "inkloom123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_auth_remains_available_while_review_runs_and_duplicate_check_is_rejected(monkeypatch):
    client, _ = _app()
    creator = _creator(client)
    sub_id = client.post("/submissions", data={"content_type": "text", "text": "Synthetic claim."}, headers=creator).json()["id"]
    started, release = threading.Event(), threading.Event()

    def slow_pipeline(*_args):
        started.set()
        assert release.wait(5)
        return [], []

    monkeypatch.setattr("app.main.run_pipeline", slow_pipeline)
    try:
        assert client.post(f"/submissions/{sub_id}/check", json={"async_mode": True}, headers=creator).status_code == 200
        assert started.wait(2)
        assert client.get("/auth/accounts").status_code == 200
        assert client.post("/auth/login", json={"email": "manager@inkloom.ai", "password": "inkloom123"}).status_code == 200
        assert client.post(f"/submissions/{sub_id}/check", json={"async_mode": True}, headers=creator).status_code == 409
    finally:
        release.set()


def test_abandoned_job_keeps_id_and_can_be_retried(monkeypatch):
    client, repo = _app()
    creator = _creator(client)
    sub_id = client.post("/submissions", data={"content_type": "text", "text": "Synthetic claim."}, headers=creator).json()["id"]
    stored = repo._submissions[sub_id]
    stored.status = "ai_review"
    stored.processing_stage = "verifying_and_assessing"
    stored.processing_job_id = "abandoned-job"
    stored.updated_at = (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()
    status = client.get(f"/submissions/{sub_id}/status", headers=creator).json()
    assert status["id"] == sub_id
    assert status["status"] == "draft" and status["processing_stage"] == "failed"
    assert "Retry" in status["processing_error"]
    assert [e["action"] for e in client.get(f"/submissions/{sub_id}/audit", headers=creator).json()].count("check_abandoned") == 1
    monkeypatch.setattr("app.main.run_pipeline", lambda *_args: ([], []))
    retried = client.post(f"/submissions/{sub_id}/retry-check", json={}, headers=creator)
    assert retried.status_code == 200
    assert retried.json()["submission"]["id"] == sub_id
    assert client.get(f"/submissions/{sub_id}/status", headers=creator).json()["status"] == "manager_review"


def test_missing_image_extraction_is_incomplete_not_success(monkeypatch):
    monkeypatch.setattr("retrieval.extractor.extract_from_payload", lambda *_args: "")
    content = ContentPayload(content_type="image", file_name="synthetic.png", file_mime="image/png", file_bytes=b"\x89PNG\r\n\x1a\n")
    flags, degraded = run_pipeline(content, "synthetic-id", retrieval_fn=lambda *_args: [],
                                   verification_fn=lambda *_args: [], brand_check_fn=lambda *_args: [])
    assert any(d.module == "extraction" for d in degraded)
    assert any(f.origin == "error" and "extracted" in f.explanation for f in flags)


class _Response(BaseModel):
    value: str


def test_model_server_errors_have_two_explicit_attempts_and_sdk_retries_disabled(monkeypatch):
    class ServerError(Exception):
        code = 503

    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        raise ServerError("503 service unavailable")

    monkeypatch.setattr("app.ai.client.time.sleep", lambda *_args: None)
    client = GeminiClient(mock_mode=True)
    client.mock_mode = False
    client._genai_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    try:
        client.generate_structured("synthetic", _Response)
    except GeminiAPIError:
        pass
    else:
        raise AssertionError("A provider error must not become a successful review")
    assert len(calls) == 2
    options = calls[0]["config"].http_options
    assert options.timeout == 60000
    assert options.retry_options.attempts == 1
