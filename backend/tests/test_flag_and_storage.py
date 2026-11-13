"""Tests for Flag schema validation and storage backend switching."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import FlagDraft
from app.repository import SupabaseRepository, get_repository


def test_flag_state_validation():
    # Valid brand states
    for state in ["aligned", "potential_issue", "unclear"]:
        flag = FlagDraft(
            finding_type="brand",
            state=state,
            passage="Passage",
            location="loc",
            explanation="exp",
            why_it_matters="wim",
            origin="fixture",
        )
        assert flag.state == state

    # Invalid brand state (e.g. claim state)
    with pytest.raises(ValidationError):
        FlagDraft(
            finding_type="brand",
            state="supported",
            passage="Passage",
            location="loc",
            explanation="exp",
            why_it_matters="wim",
            origin="fixture",
        )

    # Valid claim states
    for state in ["supported", "contradicted", "insufficient_evidence"]:
        flag = FlagDraft(
            finding_type="claim",
            state=state,
            passage="Passage",
            location="loc",
            explanation="exp",
            why_it_matters="wim",
            origin="fixture",
        )
        assert flag.state == state

    # Invalid claim state (e.g. brand state)
    with pytest.raises(ValidationError):
        FlagDraft(
            finding_type="claim",
            state="aligned",
            passage="Passage",
            location="loc",
            explanation="exp",
            why_it_matters="wim",
            origin="fixture",
        )


def test_supabase_repository_raises_not_implemented():
    with pytest.raises(NotImplementedError) as exc_info:
        SupabaseRepository()
    assert "fill in after Ken shares the schema" in str(exc_info.value)


def test_storage_backend_factory_selection():
    with pytest.raises(NotImplementedError) as exc_info:
        get_repository("supabase")
    assert "fill in after Ken shares the schema" in str(exc_info.value)

    memory_repo = get_repository("memory")
    assert memory_repo is not None


def test_app_factory_with_supabase_backend_fails_gracefully():
    settings = Settings(repo_backend="supabase")
    with pytest.raises(NotImplementedError):
        create_app(settings=settings)

