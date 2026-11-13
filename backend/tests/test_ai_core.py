"""Tests for Sera's AI Intelligence Core: Client, Schemas, and Mock Handling."""

import os
import unittest
from unittest.mock import MagicMock, patch

from app.ai.client import (
    GeminiAPIError,
    GeminiClient,
    GeminiConfigurationError,
    GeminiModelNotFoundError,
    GeminiQuotaError,
    GeminiTimeoutError,
)
from app.ai.schemas import (
    AccessibilityIssue,
    BrandFinding,
    BrandVerificationOutput,
    ClaimFinding,
    ClaimVerificationOutput,
    ContentUnderstandingOutput,
    CorrectionOutput,
    ExtractedClaim,
    GovernanceInsightsOutput,
    PreservedEntity,
    SynthesizedFlag,
    VisualAccessibilityOutput,
)
from app.config import Settings
from app.models import FlagDraft, GuidelineRef, ExternalSource


class TestGeminiClientCore(unittest.TestCase):
    """Verify Gemini client configuration, credential safety, and mock modes."""

    def test_missing_key_in_real_mode_raises_configuration_error(self):
        """Live mode must fail fast and explicitly if no API key is provided."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=True):
            settings = Settings(gemini_api_key="", mock_ai=False)
            with self.assertRaises(GeminiConfigurationError) as ctx:
                GeminiClient(api_key="", mock_mode=False, settings=settings)
            self.assertIn("GEMINI_API_KEY is not configured", str(ctx.exception))

    def test_explicit_mock_mode_initializes_without_key(self):
        """Mock mode must initialize cleanly with no API key or network dependency."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=True):
            client = GeminiClient(mock_mode=True)
            self.assertTrue(client.mock_mode)
            self.assertEqual(client.model, "gemini-2.5-flash")

    def test_masked_api_key_protects_secrets(self):
        """Client must never reveal full raw API key in logs or string representations."""
        client = GeminiClient(api_key="AIzaSy1234567890abcdefSecret", mock_mode=True)
        masked = client.masked_api_key()
        self.assertNotIn("Secret", masked)
        self.assertIn("AIzaSy", masked)
        self.assertIn("cret", masked)
        self.assertIn("...", masked)

    def test_masked_api_key_handles_empty(self):
        client = GeminiClient(api_key="", mock_mode=True)
        self.assertEqual(client.masked_api_key(), "[NONE]")

    def test_custom_mock_handler_override(self):
        """Custom mock responses can be registered for deterministic test scenarios."""
        client = GeminiClient(mock_mode=True)

        custom_output = ContentUnderstandingOutput(
            summary="Custom test summary",
            target_audience="Developers",
            purpose="Unit testing",
            tone="Direct",
            intended_message="Verification passed",
            claims=[
                ExtractedClaim(
                    claim_id="c1",
                    text="FastAPI runs tests quickly.",
                    claim_type="fact",
                    passage="runs tests quickly",
                    location="line 1",
                )
            ],
            preserved_entities=[],
        )

        client.register_mock_handler(ContentUnderstandingOutput, custom_output)
        result = client.generate_structured("prompt", ContentUnderstandingOutput)
        self.assertEqual(result.summary, "Custom test summary")
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].claim_id, "c1")


class TestStructuredSchemas(unittest.TestCase):
    """Verify that structured schemas for all seven areas validate and serialize correctly."""

    def setUp(self):
        self.client = GeminiClient(mock_mode=True)

    def test_content_understanding_schema(self):
        result = self.client.generate_structured("Draft text", ContentUnderstandingOutput)
        self.assertIsInstance(result, ContentUnderstandingOutput)
        self.assertTrue(len(result.summary) > 0)
        self.assertTrue(len(result.target_audience) > 0)
        self.assertTrue(len(result.claims) > 0)
        self.assertIn(result.claims[0].claim_type, ["fact", "opinion", "mixed"])
        self.assertTrue(len(result.preserved_entities) > 0)

    def test_brand_verification_schema(self):
        result = self.client.generate_structured("Draft text", BrandVerificationOutput)
        self.assertIsInstance(result, BrandVerificationOutput)
        self.assertIn(result.overall_alignment, ["aligned", "potential_issue", "unclear"])
        self.assertTrue(len(result.findings) > 0)
        finding = result.findings[0]
        self.assertIn(finding.state, ["aligned", "potential_issue", "unclear"])
        self.assertIn(
            finding.violation_category,
            ["tone", "buzzword", "superlative", "terminology", "visual", "positioning", "other"],
        )

    def test_claim_verification_schema(self):
        result = self.client.generate_structured("Draft text", ClaimVerificationOutput)
        self.assertIsInstance(result, ClaimVerificationOutput)
        self.assertTrue(len(result.findings) > 0)
        finding = result.findings[0]
        self.assertIn(finding.state, ["supported", "contradicted", "insufficient_evidence"])
        self.assertIn(finding.evidence_quality, ["reliable", "outdated", "conflicting", "insufficient", "none"])

    def test_correction_schema(self):
        result = self.client.generate_structured("Draft text", CorrectionOutput)
        self.assertIsInstance(result, CorrectionOutput)
        self.assertTrue(result.recheck_passed)
        self.assertEqual(result.suggested_replacement, "effective collaboration")

    def test_visual_accessibility_schema(self):
        result = self.client.generate_structured("Draft image", VisualAccessibilityOutput)
        self.assertIsInstance(result, VisualAccessibilityOutput)
        self.assertTrue(result.has_visual_content)
        self.assertIsInstance(result.color_palette, list)
        self.assertIn(result.visual_brand_alignment, ["aligned", "potential_issue", "unclear"])

    def test_governance_insights_schema(self):
        result = self.client.generate_structured("Audit logs", GovernanceInsightsOutput)
        self.assertIsInstance(result, GovernanceInsightsOutput)
        self.assertGreater(result.total_reviews_analyzed, 0)
        self.assertTrue(len(result.top_recurring_violations) > 0)

    def test_synthesized_flag_to_flag_draft(self):
        """Verify SynthesizedFlag cleanly bridges to Gaurav's FlagDraft model."""
        synth = SynthesizedFlag(
            finding_type="brand",
            state="potential_issue",
            passage="disruptive synergy",
            location="characters 10-28",
            explanation="Corporate buzzword violates plain-English rule.",
            why_it_matters="Builds enterprise trust.",
            guideline_ref=GuidelineRef(
                document="Brand Playbook",
                passage_ref="1.3",
                excerpt="Avoid buzzwords.",
            ),
            external_sources=[
                ExternalSource(url="https://rules.example.com", excerpt="Plain English standard.")
            ],
            suggested_correction="effective collaboration",
            origin="module",
            status="open",
        )
        draft = synth.to_flag_draft()
        self.assertIsInstance(draft, FlagDraft)
        self.assertEqual(draft.finding_type, "brand")
        self.assertEqual(draft.state, "potential_issue")
        self.assertEqual(draft.suggested_correction, "effective collaboration")
        self.assertEqual(draft.origin, "module")
        # Ensure validation passed and guideline_refs synced
        self.assertEqual(len(draft.guideline_refs), 1)
        self.assertEqual(draft.guideline_refs[0].document, "Brand Playbook")


class TestSettingsAndDotenv(unittest.TestCase):
    """Verify application settings, .env loading, and default fallbacks."""

    def test_settings_mock_ai_and_gemini_defaults(self):
        with patch.dict(os.environ, {"MOCK_AI": "true", "GEMINI_MODEL": "gemini-2.5-pro"}):
            s = Settings()
            self.assertTrue(s.mock_ai)
            self.assertEqual(s.gemini_model, "gemini-2.5-pro")

    def test_settings_default_model_fallback(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": ""}):
            s = Settings(gemini_model="")
            self.assertEqual(s.gemini_model, "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()

