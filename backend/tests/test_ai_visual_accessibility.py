"""Unit tests for Stage 4 Part B: AI Visual and Accessibility Intelligence.

Tests:
1. Visual brand analysis and logo identification using Gemini client.
2. Empirical contrast ratio calculation using WCAG 2.1 relative luminance.
3. Strict separation of [Measurable] findings from [Visual Estimate] findings.
4. Zero-guideline uncertainty handling (escalates to human review instead of inventing brand rules).
5. Visual brand inconsistency detection (e.g. distorted logo).
6. Graceful handling of text-only submissions (has_visual_content=False, no crashes).
7. Graceful handling of invalid or unsupported media bytes.
8. Compliance disclaimers (does NOT claim certified WCAG compliance without empirical audit).
"""

import unittest

from app.ai.client import GeminiClient
from app.ai.schemas import AccessibilityIssue, VisualAccessibilityOutput
from app.ai.visual_accessibility import (
    analyze_visual_accessibility,
    calculate_contrast_ratio,
    calculate_relative_luminance,
)
from app.models import ContentPayload, GuidelineRef


class TestAIVisualAccessibility(unittest.TestCase):
    """Test multimodal visual identity, logo compliance, and accessibility heuristics."""

    def setUp(self):
        self.mock_client = GeminiClient(mock_mode=True)
        # 1x1 valid PNG bytes
        self.dummy_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def test_empirical_contrast_ratio_calculation(self):
        """Validates WCAG 2.1 relative luminance and contrast ratio mathematics."""
        # Pure black on pure white -> maximum contrast 21:1
        black_on_white = calculate_contrast_ratio("#000000", "#FFFFFF")
        self.assertEqual(black_on_white, 21.0)

        # Pure white on pure white -> no contrast 1:1
        white_on_white = calculate_contrast_ratio("#FFFFFF", "#FFFFFF")
        self.assertEqual(white_on_white, 1.0)

        # Light gray (#94A3B8) on white (#FFFFFF) -> low contrast ~2.61:1
        gray_on_white = calculate_contrast_ratio("#94A3B8", "#FFFFFF")
        self.assertIsNotNone(gray_on_white)
        self.assertAlmostEqual(gray_on_white, 2.61, places=1)
        self.assertLess(gray_on_white, 4.5)  # Fails WCAG AA 4.5:1 requirement

        # High contrast brand navy (#0F172A) on white -> passes WCAG AA
        navy_on_white = calculate_contrast_ratio("#0F172A", "#FFFFFF")
        self.assertIsNotNone(navy_on_white)
        self.assertGreater(navy_on_white, 12.0)

    def test_visual_analysis_with_image_payload(self):
        """Analyzes image payload, extracts color palette, and detects accessibility issues."""
        payload = ContentPayload(
            content_type="image",
            file_name="marketing_banner.png",
            file_mime="image/png",
            file_bytes=self.dummy_png,
        )
        guidelines = [
            GuidelineRef(
                document="Brand Visual Guide",
                passage_ref="Section 2.1",
                excerpt="Official brand colors are Inkloom Navy #0F172A and Brand Blue #3B82F6.",
            )
        ]

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=guidelines,
            client=self.mock_client,
        )

        self.assertIsInstance(result, VisualAccessibilityOutput)
        self.assertTrue(result.has_visual_content)
        self.assertEqual(result.visual_brand_alignment, "aligned")
        self.assertIn("#0F172A", result.color_palette)
        self.assertIn("#3B82F6", result.color_palette)
        self.assertGreaterEqual(len(result.accessibility_issues), 1)

    def test_distinguishes_measurable_from_visual_estimates(self):
        """Accessibility findings strictly distinguish calculated estimates from raw visual estimates."""
        payload = ContentPayload(
            content_type="image",
            file_name="landing_page.png",
            file_mime="image/png",
            file_bytes=self.dummy_png,
        )
        guidelines = [
            GuidelineRef(
                document="Brand Guide",
                passage_ref="1.0",
                excerpt="Maintain clean visual design.",
            )
        ]

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=guidelines,
            client=self.mock_client,
        )

        descriptions = [i.description for i in result.accessibility_issues]

        # Verify calculated contrast from estimated colors prefix
        calc_estimate_found = any(d.startswith("[Visual Estimate: Calculated Contrast]") for d in descriptions)
        self.assertTrue(calc_estimate_found, "Expected [Visual Estimate: Calculated Contrast] finding.")

        # Verify visual estimate prefix for heuristic readability/hierarchy
        estimate_found = any(d.startswith("[Visual Estimate]") for d in descriptions)
        self.assertTrue(estimate_found, "Expected [Visual Estimate] finding.")

        # Ensure no visually estimated colors are deceptively labeled as raw '[Measurable]'
        bare_measurable_found = any(d.startswith("[Measurable]") for d in descriptions)
        self.assertFalse(bare_measurable_found, "Estimated colors must not be labeled as raw '[Measurable]'.")

    def test_large_text_contrast_threshold_distinction(self):
        """Normal text requires >= 4.5:1; large text (>= 18pt / 24px) requires >= 3.0:1."""
        from app.ai.visual_accessibility import evaluate_wcag_contrast

        # Brand Blue (#3B82F6) on White (#FFFFFF) has contrast ratio ~3.68:1
        # 1. For normal body text, 3.68:1 fails the 4.5:1 requirement
        eval_normal = evaluate_wcag_contrast("#3B82F6", "#FFFFFF", is_large_text=False)
        self.assertFalse(eval_normal["passes_aa"])
        self.assertEqual(eval_normal["threshold"], 4.5)
        self.assertEqual(eval_normal["text_type"], "normal text")

        # 2. For large text (>= 24px / 18pt), 3.68:1 passes the 3.0:1 requirement
        eval_large = evaluate_wcag_contrast("#3B82F6", "#FFFFFF", is_large_text=True)
        self.assertTrue(eval_large["passes_aa"])
        self.assertEqual(eval_large["threshold"], 3.0)
        self.assertEqual(eval_large["text_type"], "large text")

    def test_measured_vs_estimated_contrast_labeling(self):
        """Differentiates [Measured Contrast] from [Visual Estimate: Calculated Contrast]."""
        from app.ai.visual_accessibility import evaluate_wcag_contrast

        # When colors are visually estimated by AI (is_measured=False)
        eval_est = evaluate_wcag_contrast("#94A3B8", "#FFFFFF", is_measured=False)
        self.assertEqual(eval_est["prefix"], "[Visual Estimate: Calculated Contrast]")

        # When colors are verified from extracted pixels or design tokens (is_measured=True)
        eval_meas = evaluate_wcag_contrast("#94A3B8", "#FFFFFF", is_measured=True)
        self.assertEqual(eval_meas["prefix"], "[Measured Contrast]")

    def test_zero_guidelines_reports_uncertainty_and_escalates(self):
        """Zero-guideline safety: without guidelines, reports uncertainty rather than inventing rules."""
        payload = ContentPayload(
            content_type="image",
            file_name="brand_banner.png",
            file_mime="image/png",
            file_bytes=self.dummy_png,
        )

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=None,  # No guidelines provided!
            client=self.mock_client,
        )

        self.assertEqual(result.visual_brand_alignment, "unclear")
        self.assertTrue(result.needs_human)
        self.assertIsNotNone(result.uncertainty_note)
        self.assertIn("guidelines were not supplied", result.uncertainty_note.lower())

    def test_visual_brand_inconsistency_detected(self):
        """Detects potential brand issues such as distorted logos or unapproved styling."""
        payload = ContentPayload(
            content_type="image",
            file_name="distorted_logo_banner.png",
            file_mime="image/png",
            file_bytes=self.dummy_png,
        )
        guidelines = [
            GuidelineRef(
                document="Brand Logo Guide",
                passage_ref="3.2",
                excerpt="Never stretch, compress, or distort the Inkloom brand mark.",
            )
        ]

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=guidelines,
            client=self.mock_client,
        )

        self.assertEqual(result.visual_brand_alignment, "potential_issue")
        self.assertTrue(result.needs_human)
        self.assertIn("distorted", result.visual_brand_notes.lower())

    def test_text_only_submission_handled_gracefully(self):
        """Text submissions gracefully skip visual analysis without raising errors."""
        payload = ContentPayload(
            content_type="text",
            text="This is a text press release with no imagery.",
        )

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=None,
            client=self.mock_client,
        )

        self.assertIsInstance(result, VisualAccessibilityOutput)
        self.assertFalse(result.has_visual_content)
        self.assertEqual(result.visual_consistency_score, "not_applicable")
        self.assertEqual(len(result.accessibility_issues), 0)
        self.assertFalse(result.needs_human)

    def test_invalid_mime_type_handled_gracefully(self):
        """Invalid or corrupted visual media escalates to human review gracefully."""
        payload = ContentPayload(
            content_type="image",
            file_name="corrupted.exe",
            file_mime="application/x-msdownload",
            file_bytes=b"MZ\x90\x00",
        )

        result = analyze_visual_accessibility(
            content=payload,
            guidelines=None,
            client=self.mock_client,
        )

        self.assertFalse(result.has_visual_content)
        self.assertEqual(result.visual_brand_alignment, "unclear")
        self.assertTrue(result.needs_human)
        self.assertIn("Unsupported visual MIME type", result.visual_brand_notes)


if __name__ == "__main__":
    unittest.main()

