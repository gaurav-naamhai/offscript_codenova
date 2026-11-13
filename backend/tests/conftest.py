"""Pytest fixtures for backend tests."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repository import InMemorySubmissionRepository


@pytest.fixture
def repo():
    return InMemorySubmissionRepository()


@pytest.fixture
def settings():
    return Settings(
        frontend_origin="http://allowed.test,http://app.test/",
        repo_backend="memory",
    )


@pytest.fixture
def app(repo, settings):
    return create_app(repo=repo, settings=settings)


@pytest.fixture
def client(app):
    return TestClient(app)

