"""Unit tests for Batch 2: Content Understanding and Brand Verification."""

import unittest
from unittest.mock import MagicMock

from app.ai.brand_verification import verify_brand
from app.ai.client import GeminiClient
from app.ai.content_understanding import understand_content, understand_text
from app.ai.schemas import (
    BrandFinding,
    BrandVerificationOutput,
    ContentUnderstandingOutput,
    ExtractedClaim,
    PreservedEntity,
)
from app.models import ContentPayload, GuidelineRef


class TestContentUnderstanding(unittest.TestCase):
    """Test text, image, and PDF content understanding, claim extraction, and entity preservation."""

    def setUp(self):
        self.mock_client = GeminiClient(mock_mode=True)

    def test_understand_text_extracts_claims_and_entities(self):
        text = "Inkloom AI accelerates compliance by 40% in Q4 2026. We believe it is the most intuitive review tool."
        result = understand_text(text, client=self.mock_client)

        self.assertIsInstance(result, ContentUnderstandingOutput)
        self.assertTrue(len(result.summary) > 0)
        self.assertTrue(len(result.target_audience) > 0)
        self.assertTrue(len(result.tone) > 0)
        self.assertTrue(len(result.intended_message) > 0)

        # Verify claims extracted
        self.assertGreater(len(result.claims), 0)
        claim_types = [c.claim_type for c in result.claims]
        self.assertTrue(any(t in ("fact", "opinion", "mixed") for t in claim_types))

        # Verify preserved entities (metric "40%", date "2026", proper name "Inkloom AI")
        self.assertGreater(len(result.preserved_entities), 0)
        entity_texts = [e.text for e in result.preserved_entities]
        self.assertTrue(any("40%" in t or "2026" in t or "Inkloom" in t for t in entity_texts))

    def test_understand_image_multimodal_payload(self):
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        payload = ContentPayload(
            content_type="image",
            file_name="social_banner.png",
            file_mime="image/png",
            file_bytes=fake_png,
        )
        result = understand_content(payload, client=self.mock_client)

        self.assertIsInstance(result, ContentUnderstandingOutput)
        self.assertIn("image", result.summary.lower())
        self.assertGreater(len(result.claims), 0)
        self.assertGreater(len(result.preserved_entities), 0)

    def test_understand_pdf_multimodal_payload(self):
        fake_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj"
        payload = ContentPayload(
            content_type="pdf",
            file_name="annual_governance_report.pdf",
            file_mime="application/pdf",
            file_bytes=fake_pdf,
        )
        result = understand_content(payload, client=self.mock_client)

        self.assertIsInstance(result, ContentUnderstandingOutput)
        self.assertIn("pdf", result.summary.lower())
        self.assertGreater(len(result.claims), 0)

    def test_understand_empty_payload_raises_value_error(self):
        payload = ContentPayload(content_type="text", text="", file_bytes=None)
        with self.assertRaises(ValueError):
            understand_content(payload, client=self.mock_client)

    def test_understand_with_custom_mocked_gemini_client(self):
        """Verify custom mocked response handler injection."""
        custom_understanding = ContentUnderstandingOutput(
            summary="Custom mocked summary",
            target_audience="Enterprise CTOs",
            purpose="Product brief",
            tone="Technical",
            intended_message="Deliver reliable APIs",
            claims=[
                ExtractedClaim(
                    claim_id="custom-1",
                    text="Custom benchmark claim",
                    claim_type="fact",
                    passage="Custom benchmark claim",
                    location="paragraph 1",
                )
            ],
            preserved_entities=[
                PreservedEntity(
                    entity_type="metric",
                    text="99.99%",
                    context="99.99% uptime",
                )
            ],
        )

        client = GeminiClient(mock_mode=True)
        client.register_mock_handler(ContentUnderstandingOutput, custom_understanding)

        result = understand_text("Anything", client=client)
        self.assertEqual(result.summary, "Custom mocked summary")
        self.assertEqual(result.target_audience, "Enterprise CTOs")
        self.assertEqual(result.claims[0].claim_id, "custom-1")


class TestBrandVerification(unittest.TestCase):
    """Test guideline comparison, voice and tone checks, uncertainty reporting, and multimodal checks."""

    def setUp(self):
        self.mock_client = GeminiClient(mock_mode=True)
        self.sample_guidelines = [
            GuidelineRef(
                document="Visual and Brand Identity Playbook",
                passage_ref="Section 1.3",
                excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.",
                source_reference="Brand Governance Guide",
            ),
            GuidelineRef(
                document="Visual and Brand Identity Playbook",
                passage_ref="Section 1.1",
                excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.",
                source_reference="Brand Governance Guide",
            ),
            GuidelineRef(
                document="Visual and Brand Identity Playbook",
                passage_ref="Section 2.4",
                excerpt="Visual assets must maintain primary palette balance and clear logo spacing.",
                source_reference="Design Standards",
            ),
        ]

    def test_zero_guidelines_reports_uncertainty_without_inventing_violations(self):
        """When Ken's retrieval returns no guidelines, report uncertainty instead of inventing rules."""
        payload = ContentPayload(content_type="text", text="Our software is completely revolutionary!!")
        result = verify_brand(payload, guidelines=[], client=self.mock_client)

        self.assertIsInstance(result, BrandVerificationOutput)
        self.assertEqual(result.overall_alignment, "unclear")
        self.assertIn("No governing brand guidelines were retrieved", result.voice_and_tone_assessment)

        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.state, "unclear")
        self.assertIsNotNone(finding.uncertainty_note)
        self.assertIn("Missing guideline context", finding.uncertainty_note)
        # Asserts no fake violation was invented
        self.assertNotEqual(finding.state, "potential_issue")

    def test_verify_brand_detects_prohibited_buzzwords(self):
        payload = ContentPayload(
            content_type="text",
            text="We utilize disruptive synergy to transform enterprise workflow automation.",
        )
        result = verify_brand(payload, guidelines=self.sample_guidelines, client=self.mock_client)

        self.assertEqual(result.overall_alignment, "potential_issue")
        self.assertGreater(len(result.findings), 0)

        buzzword_findings = [f for f in result.findings if f.violation_category == "buzzword"]
        self.assertGreater(len(buzzword_findings), 0)

        passages = [f.passage.lower() for f in buzzword_findings]
        self.assertTrue(any("disruptive" in p for p in passages))
        self.assertTrue(any("synergy" in p for p in passages))
        self.assertEqual(buzzword_findings[0].state, "potential_issue")
        self.assertIn("Section 1.3", buzzword_findings[0].guideline_section)
        self.assertIn("Visual and Brand Identity Playbook", buzzword_findings[0].guideline_document)
        self.assertIsNotNone(buzzword_findings[0].suggested_fix)

    def test_verify_brand_clean_text_returns_aligned(self):
        payload = ContentPayload(
            content_type="text",
            text="Inkloom AI helps distributed teams review publications with structured human approvals.",
        )
        result = verify_brand(payload, guidelines=self.sample_guidelines, client=self.mock_client)

        self.assertEqual(result.overall_alignment, "aligned")
        self.assertGreater(len(result.findings), 0)
        self.assertTrue(all(f.state == "aligned" for f in result.findings))
        self.assertIn("Visual and Brand Identity Playbook", result.findings[0].guideline_document)

    def test_verify_brand_multimodal_image_checks_visual_identity(self):
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        payload = ContentPayload(
            content_type="image",
            file_name="brand_header.png",
            file_mime="image/png",
            file_bytes=fake_png,
        )
        result = verify_brand(payload, guidelines=self.sample_guidelines, client=self.mock_client)

        self.assertIsNotNone(result.visual_brand_assessment)
        visual_findings = [f for f in result.findings if f.violation_category == "visual"]
        self.assertGreater(len(visual_findings), 0)
        self.assertEqual(visual_findings[0].guideline_section, "Section 2.4")

    def test_verify_brand_with_custom_mocked_gemini_client(self):
        """Verify injecting a custom mocked brand verification output."""
        custom_brand_output = BrandVerificationOutput(
            overall_alignment="aligned",
            voice_and_tone_assessment="Perfect tone match",
            terminology_assessment="Clean vocabulary",
            visual_brand_assessment=None,
            findings=[
                BrandFinding(
                    state="aligned",
                    passage="Clean text",
                    location="all",
                    violation_category="tone",
                    explanation="Meets standard",
                    why_it_matters="Trust",
                    guideline_document="Playbook",
                    guideline_section="1.1",
                    guideline_excerpt="Tone excerpt",
                    suggested_fix=None,
                )
            ],
        )

        client = GeminiClient(mock_mode=True)
        client.register_mock_handler(BrandVerificationOutput, custom_brand_output)

        payload = ContentPayload(content_type="text", text="Any text")
        result = verify_brand(payload, guidelines=self.sample_guidelines, client=client)
        self.assertEqual(result.voice_and_tone_assessment, "Perfect tone match")
        self.assertEqual(result.findings[0].guideline_section, "Section 1.1")

    def test_hallucinated_guideline_converted_to_unclear(self):
        """Audit requirement 1: Hallucinated guideline citations must be converted to unclear."""
        hallucinated_output = BrandVerificationOutput(
            overall_alignment="potential_issue",
            voice_and_tone_assessment="Tone violation",
            terminology_assessment="Bad wording",
            visual_brand_assessment=None,
            findings=[
                BrandFinding(
                    state="potential_issue",
                    passage="Some phrase",
                    location="para 1",
                    violation_category="other",
                    explanation="Violates fictional rule",
                    why_it_matters="Matters",
                    guideline_document="Fictional Policy 2099",
                    guideline_section="Rule 99",
                    guideline_excerpt="Invented rule excerpt",
                    suggested_fix="Better phrase",
                )
            ],
        )

        client = GeminiClient(mock_mode=True)
        client.register_mock_handler(BrandVerificationOutput, hallucinated_output)

        payload = ContentPayload(content_type="text", text="Draft")
        result = verify_brand(payload, guidelines=self.sample_guidelines, client=client)

        self.assertEqual(result.overall_alignment, "unclear")
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.state, "unclear")
        self.assertIn("Unverified guideline citation", finding.uncertainty_note)
        self.assertEqual(finding.guideline_document, "Unverified Reference")

    def test_buzzwords_not_flagged_if_no_language_guideline_present(self):
        """Audit requirement 2: Rules not in retrieved guidelines must not trigger false positive violations."""
        color_only_guideline = [
            GuidelineRef(
                document="Color System",
                passage_ref="Palette 1",
                excerpt="All buttons must use primary indigo #4F46E5.",
            )
        ]
        # Text has corporate buzzword 'synergy', but guideline only addresses button color
        payload = ContentPayload(
            content_type="text",
            text="Our cross-functional synergy drives excellent product outcomes.",
        )
        result = verify_brand(payload, guidelines=color_only_guideline, client=self.mock_client)

        # No buzzword rule exists in guidelines -> should NOT flag buzzwords as potential_issue
        buzzword_violations = [f for f in result.findings if f.violation_category == "buzzword" and f.state == "potential_issue"]
        self.assertEqual(len(buzzword_violations), 0)

    def test_brand_finding_to_flag_draft_compatibility(self):
        """Audit requirement 4: Verify compatibility with Gaurav's FlagDraft model."""
        from app.ai.brand_verification import brand_finding_to_flag_draft
        finding = BrandFinding(
            state="potential_issue",
            passage="cheap alternative",
            location="chars 10-25",
            violation_category="positioning",
            explanation="Violates premium standard",
            why_it_matters="Brand trust",
            guideline_document="Playbook",
            guideline_section="1.2",
            guideline_excerpt="Use cost-effective",
            suggested_fix="cost-effective",
        )
        draft = brand_finding_to_flag_draft(finding, guideline=self.sample_guidelines[0])
        self.assertEqual(draft.finding_type, "brand")
        self.assertEqual(draft.state, "potential_issue")
        self.assertEqual(draft.passage, "cheap alternative")
        self.assertEqual(draft.guideline_ref.document, self.sample_guidelines[0].document)
        self.assertEqual(draft.suggested_correction, "cost-effective")

    def test_resolve_media_mime(self):
        """Audit requirement 5: Verify MIME resolution for multimodal assets."""
        from app.ai.brand_verification import resolve_media_mime
        p1 = ContentPayload(content_type="image", file_mime="image/jpg")
        self.assertEqual(resolve_media_mime(p1), "image/jpeg")

        p2 = ContentPayload(content_type="image", file_name="sample.png")
        self.assertEqual(resolve_media_mime(p2), "image/png")

        p3 = ContentPayload(content_type="pdf", file_name="document.pdf")
        self.assertEqual(resolve_media_mime(p3), "application/pdf")


if __name__ == "__main__":
    unittest.main()
