"""End-to-End integration tests for Sera's AI Pipeline & Brand Check (Stage 5).

Owner: Sera
Tests end-to-end execution of Content Understanding, Brand Verification,
Visual & Accessibility Intelligence, Suggestions & Corrections, and Gaurav's
FastAPI compliance review pipeline.
"""

from typing import List
import pytest

from app.ai.client import GeminiClient
from app.config import Settings
from app.models import ContentPayload, FlagDraft, GuidelineRef
from app.pipeline import run_pipeline
from app.plugins.brand_check import check_brand
from app.plugins.retrieval import retrieve_guidelines


@pytest.fixture
def mock_client() -> GeminiClient:
    return GeminiClient(settings=Settings(mock_ai=True))


@pytest.fixture
def retrieved_guidelines() -> List[GuidelineRef]:
    return [
        GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.3",
            excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.",
        ),
        GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.1",
            excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.",
        ),
        GuidelineRef(
            document="Brand Identity Guidelines",
            passage_ref="Section 2.4",
            excerpt="Ensure 4.5:1 contrast for normal text and do not distort brand logos.",
        ),
    ]


class TestBrandCheckIntegration:
    """Test suite for check_brand integration into the review pipeline."""

    def test_check_brand_fixture_fallback_when_unconfigured(
        self, monkeypatch
    ):
        """When mock_ai is False and GEMINI_API_KEY is empty, check_brand returns fixture flags."""
        monkeypatch.setenv("MOCK_AI", "false")
        monkeypatch.setenv("GEMINI_API_KEY", "")

        content = ContentPayload(
            content_type="text",
            text="Inkloom AI delivers disruptive synergy with cheap pricing!!",
        )
        flags = check_brand(content, guidelines=[])

        assert len(flags) >= 2
        for f in flags:
            assert f.origin == "fixture"
            assert f.finding_type == "brand"

        # Check that fixture replacement is provided
        buzzword_flag = next((f for f in flags if "synergy" in f.passage.lower() or "disruptive" in f.passage.lower()), None)
        assert buzzword_flag is not None
        assert buzzword_flag.suggested_correction == "effective collaboration"

    def test_check_brand_text_with_mock_ai(
        self, retrieved_guidelines: List[GuidelineRef], mock_client: GeminiClient
    ):
        """In AI mode, check_brand runs Content Understanding, Brand Verification, and Suggestions."""
        content = ContentPayload(
            content_type="text",
            text="Inkloom AI drives disruptive synergy across enterprise marketing teams.",
        )
        flags = check_brand(content, guidelines=retrieved_guidelines, client=mock_client)

        assert len(flags) >= 1
        for f in flags:
            assert f.origin == "module"
            assert f.finding_type == "brand"

        buzzword_flag = next((f for f in flags if "synergy" in f.passage.lower()), None)
        assert buzzword_flag is not None
        assert buzzword_flag.state == "potential_issue"
        assert buzzword_flag.suggested_correction is not None
        assert buzzword_flag.guideline_ref is not None
        assert "Section 1.3" in buzzword_flag.guideline_ref.passage_ref

    def test_check_brand_image_with_mock_ai(
        self, retrieved_guidelines: List[GuidelineRef], mock_client: GeminiClient
    ):
        """In AI mode, check_brand runs Visual & Accessibility Intelligence on images."""
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        content = ContentPayload(
            content_type="image",
            file_name="banner.png",
            file_bytes=png_bytes,
            file_mime="image/png",
        )
        flags = check_brand(content, guidelines=retrieved_guidelines, client=mock_client)

        assert len(flags) >= 1
        for f in flags:
            assert f.origin == "module"
            assert f.finding_type == "brand"

        # Verify accessibility or visual layout issue is reported
        acc_flag = next((f for f in flags if "Accessibility" in f.passage or "Visual asset" in f.passage), None)
        assert acc_flag is not None

    def test_check_brand_empty_text_handled_gracefully(
        self, retrieved_guidelines: List[GuidelineRef], mock_client: GeminiClient
    ):
        """Empty text draft produces a clear finding without raising unhandled exceptions."""
        content = ContentPayload(content_type="text", text="   ")
        flags = check_brand(content, guidelines=retrieved_guidelines, client=mock_client)

        assert len(flags) == 1
        assert flags[0].state == "unclear"
        assert "empty" in flags[0].explanation.lower()


class TestPipelineEndToEndIntegration:
    """Test suite for full pipeline execution with Sera's integrated check_brand."""

    def test_run_pipeline_full_execution(self, monkeypatch):
        """run_pipeline executes retrieval -> verification -> brand_check smoothly."""
        monkeypatch.setenv("MOCK_AI", "true")

        content = ContentPayload(
            content_type="text",
            text="Inkloom AI is the #1 platform, achieving 99.9% uptime and disruptive synergy.",
        )

        flags, degraded = run_pipeline(
            content=content,
            submission_id="sub-stage5-e2e",
            version=1,
        )

        assert degraded == []
        assert len(flags) >= 2

        # Check claim flags from verification
        claim_flags = [f for f in flags if f.finding_type == "claim"]
        assert len(claim_flags) >= 1
        for cf in claim_flags:
            assert cf.submission_id == "sub-stage5-e2e"
            assert cf.version == 1

        # Check brand flags from integrated brand_check
        brand_flags = [f for f in flags if f.finding_type == "brand"]
        assert len(brand_flags) >= 1
        for bf in brand_flags:
            assert bf.submission_id == "sub-stage5-e2e"
            assert bf.version == 1
            assert bf.origin == "module"
            if bf.state == "potential_issue":
                assert bf.suggested_correction is not None

    def test_run_pipeline_clean_content_produces_aligned_flags(self, monkeypatch):
        """Clean content without violations returns aligned status flags."""
        monkeypatch.setenv("MOCK_AI", "true")

        content = ContentPayload(
            content_type="text",
            text="Inkloom AI delivers clear, plain-English collaboration tools for marketing teams.",
        )

        flags, degraded = run_pipeline(
            content=content,
            submission_id="sub-clean-e2e",
            version=1,
        )

        assert degraded == []
        brand_flags = [f for f in flags if f.finding_type == "brand"]
        assert any(bf.state == "aligned" for bf in brand_flags)

