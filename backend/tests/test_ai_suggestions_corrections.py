"""Unit tests for Stage 4 Part A: AI Suggestions and Corrections Engine.

Tests:
1. Minimal corrections for brand violations and contradicted claims.
2. Active programmatic preservation of critical entities (names, numbers, dates, conditions).
3. Rejection or flagging when a candidate correction drops or alters a protected entity.
4. Refusal to invent replacement facts when evidence is missing or conflicting (human escalation).
5. Programmatic recheck verifying candidate corrections resolve issues without introducing new violations.
6. Detection when a candidate correction introduces an unverified superlative or forbidden buzzword.
7. Batch correction generation across multiple flags.
"""

import unittest
from unittest.mock import MagicMock

from app.ai.client import GeminiClient
from app.ai.schemas import (
    BrandFinding,
    ClaimFinding,
    ContentUnderstandingOutput,
    CorrectionOutput,
    ExtractedClaim,
    PreservedEntity,
    SuggestionsOutput,
    SynthesizedFlag,
)
from app.ai.suggestions_corrections import (
    check_entity_preservation,
    extract_entities_in_passage,
    generate_correction,
    generate_corrections,
    recheck_correction,
)
from app.models import FlagDraft, GuidelineRef


class TestAISuggestionsAndCorrections(unittest.TestCase):
    """Test editorial correction generation, entity preservation, and programmatic rechecking."""

    def setUp(self):
        self.mock_client = GeminiClient(mock_mode=True)
        self.sample_entities = [
            PreservedEntity(entity_type="date", text="2026", context="published in 2026"),
            PreservedEntity(entity_type="metric", text="99.9%", context="99.9% uptime"),
            PreservedEntity(entity_type="proper_name", text="Inkloom AI", context="developed by Inkloom AI"),
            PreservedEntity(entity_type="condition", text="subject to SLA", context="subject to SLA exclusions"),
        ]
        self.sample_context = ContentUnderstandingOutput(
            summary="A technical release announcement.",
            target_audience="Enterprise IT leaders",
            purpose="Product announcement",
            tone="Professional and confident",
            intended_message="Inkloom provides high-availability AI governance tools.",
            claims=[],
            preserved_entities=self.sample_entities,
        )

    def test_minimal_brand_buzzword_correction(self):
        """Replaces corporate buzzword with plain-English approved term."""
        flag = FlagDraft(
            finding_type="brand",
            state="potential_issue",
            passage="Our team leverages disruptive synergy across all departments.",
            location="paragraph 1",
            explanation="Corporate buzzword 'disruptive synergy' violates Brand Playbook 1.3.",
            why_it_matters="Credibility",
            guideline_ref=GuidelineRef(
                document="Brand Playbook",
                passage_ref="1.3",
                excerpt="Avoid corporate buzzwords like disruptive synergy.",
            ),
        )

        correction = generate_correction(
            flag=flag,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        self.assertIsInstance(correction, CorrectionOutput)
        self.assertIn("effective collaboration", correction.suggested_replacement.lower())
        self.assertNotIn("disruptive synergy", correction.suggested_replacement.lower())
        self.assertTrue(correction.recheck_passed)
        self.assertIn("Brand Playbook", correction.change_rationale)

    def test_entity_protection_preserves_numbers_and_names(self):
        """Protected entities (names, numbers, dates) present in passage must be preserved."""
        passage = "Inkloom AI guarantees 99.9% uptime with disruptive synergy."
        flag = FlagDraft(
            finding_type="brand",
            state="potential_issue",
            passage=passage,
            location="section 2",
            explanation="Contains buzzword 'disruptive synergy'.",
            why_it_matters="Trust",
        )

        correction = generate_correction(
            flag=flag,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        # Verified that protected entities 'Inkloom AI' and '99.9%' are preserved
        self.assertIn("Inkloom AI", correction.suggested_replacement)
        self.assertIn("99.9%", correction.suggested_replacement)
        self.assertIn("Inkloom AI", correction.entities_preserved)
        self.assertIn("99.9%", correction.entities_preserved)
        self.assertTrue(correction.recheck_passed)

    def test_entity_protection_fails_if_candidate_drops_protected_entity(self):
        """Programmatic recheck must fail if candidate correction strips a protected date or metric."""
        original = "Published in 2026 with 99.9% uptime guarantee."
        candidate_with_missing_date = "Published recently with high uptime guarantee."

        passed, notes = recheck_correction(
            original_passage=original,
            suggested_replacement=candidate_with_missing_date,
            finding_type="claim",
            state="potential_issue",
            preserved_entities=self.sample_entities,
        )

        self.assertFalse(passed)
        self.assertIn("Entity protection failure", notes)
        self.assertIn("2026", notes)

    def test_insufficient_or_conflicting_evidence_escalates_to_human(self):
        """If evidence is insufficient or conflicting, do NOT invent a replacement; escalate to human."""
        unverified_flag = FlagDraft(
            finding_type="claim",
            state="insufficient_evidence",
            passage="We achieve 40% faster latency than all competitors.",
            location="hero section",
            explanation="Third-party benchmarks conflict and show disputed latency rankings.",
            why_it_matters="Advertising compliance",
            uncertainty_note="Conflicting benchmark records require human verification.",
        )

        correction = generate_correction(
            flag=unverified_flag,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        # Must NOT invent arbitrary latency numbers
        self.assertFalse(correction.recheck_passed)
        self.assertIn("human editorial review", correction.change_rationale.lower())
        self.assertIn("insufficient or conflicting", correction.recheck_notes.lower())
        # Original passage is retained for human reviewer
        self.assertEqual(correction.suggested_replacement, unverified_flag.passage)

    def test_soften_contradicted_supremacy_claim(self):
        """Contradicted supremacy claims are softened to verifiable market standing without inventing facts."""
        contradicted_flag = FlagDraft(
            finding_type="claim",
            state="contradicted",
            passage="Rated #1 in market share globally by independent analysts.",
            location="header",
            explanation="Third-party market report proves vendor is 4th in market share.",
            why_it_matters="Legal truthfulness",
        )

        correction = generate_correction(
            flag=contradicted_flag,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        self.assertNotIn("#1", correction.suggested_replacement)
        self.assertIn("recognized", correction.suggested_replacement.lower())
        self.assertTrue(correction.recheck_passed)
        self.assertIn("contradicted supremacy claim", correction.change_rationale.lower())

    def test_recheck_detects_new_forbidden_superlative(self):
        """Programmatic recheck catches if a candidate replacement introduces a new absolute superlative."""
        original = "We provide great cloud software."
        bad_replacement = "We are the undisputed leader and best in the world."

        passed, notes = recheck_correction(
            original_passage=original,
            suggested_replacement=bad_replacement,
            finding_type="brand",
            state="potential_issue",
        )

        self.assertFalse(passed)
        self.assertIn("unverified superlative", notes)

    def test_already_compliant_flag_requires_no_change(self):
        """Compliant flags (aligned or supported) return unchanged with passing recheck."""
        aligned_flag = FlagDraft(
            finding_type="brand",
            state="aligned",
            passage="Our team collaborates closely to deliver reliable software.",
            location="p2",
            explanation="Meets all brand voice criteria.",
            why_it_matters="Consistency",
        )

        correction = generate_correction(
            flag=aligned_flag,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        self.assertEqual(correction.suggested_replacement, aligned_flag.passage)
        self.assertTrue(correction.recheck_passed)
        self.assertIn("already complies", correction.change_rationale.lower())

    def test_entity_preservation_handles_harmless_formatting_changes(self):
        """Entity protection should not fail due to harmless spacing, comma, or percentage notation differences."""
        entities = [
            PreservedEntity(entity_type="number", text="10,000", context="10,000 active users"),
            PreservedEntity(entity_type="metric", text="99.9%", context="99.9% uptime"),
            PreservedEntity(entity_type="date", text="2026", context="in 2026"),
            PreservedEntity(entity_type="proper_name", text="Inkloom AI", context="by Inkloom AI"),
        ]

        # Candidate uses '10000' (no comma), '99.9 %' (space), 'May 2026', and lowercase 'inkloom ai'
        candidate = "Developed by inkloom ai in May 2026, supporting 10000 users with 99.9 % uptime."

        all_preserved, preserved_list, missing_list = check_entity_preservation(
            original_passage="Developed by Inkloom AI in 2026, supporting 10,000 users with 99.9% uptime.",
            candidate_text=candidate,
            preserved_entities=entities,
        )

        self.assertTrue(all_preserved)
        self.assertEqual(len(missing_list), 0)
        self.assertEqual(len(preserved_list), 4)

    def test_recheck_actually_runs_content_brand_and_claim_verification(self):
        """Recheck pipeline runs candidate text through Content Understanding, Brand Verification, and Claim Verification."""
        guidelines = [
            GuidelineRef(
                document="Brand Playbook",
                passage_ref="1.3",
                excerpt="Avoid corporate buzzwords like disruptive synergy.",
            )
        ]

        # 1. Candidate introduces forbidden buzzword -> brand recheck fails
        bad_brand_candidate = "We deliver disruptive synergy across our product suite."
        passed_b, notes_b = recheck_correction(
            original_passage="Old text.",
            suggested_replacement=bad_brand_candidate,
            finding_type="brand",
            state="potential_issue",
            guidelines=guidelines,
            client=self.mock_client,
        )
        self.assertFalse(passed_b)
        self.assertIn("brand", notes_b.lower())

        # 2. Candidate introduces unverified supremacy -> claim recheck fails
        bad_claim_candidate = "We are the undisputed leader and best in the world."
        passed_c, notes_c = recheck_correction(
            original_passage="Old text.",
            suggested_replacement=bad_claim_candidate,
            finding_type="claim",
            state="potential_issue",
            client=self.mock_client,
        )
        self.assertFalse(passed_c)
        self.assertIn("superlative", notes_c.lower())

        # 3. Clean candidate replacement -> recheck passes
        clean_candidate = "We deliver effective collaboration across our product suite."
        passed_clean, notes_clean = recheck_correction(
            original_passage="Old text.",
            suggested_replacement=clean_candidate,
            finding_type="brand",
            state="potential_issue",
            guidelines=guidelines,
            client=self.mock_client,
        )
        self.assertTrue(passed_clean)
        self.assertIn("recheck passed", notes_clean.lower())

    def test_batch_generate_corrections(self):
        """Batch generation produces structured SuggestionsOutput for all non-aligned issues."""
        flags = [
            FlagDraft(
                finding_type="brand",
                state="potential_issue",
                passage="Leveraging disruptive synergy.",
                location="p1",
                explanation="Buzzword",
                why_it_matters="Brand",
            ),
            FlagDraft(
                finding_type="brand",
                state="aligned",  # Should be skipped in batch
                passage="Clean text.",
                location="p2",
                explanation="Good",
                why_it_matters="Brand",
            ),
            FlagDraft(
                finding_type="claim",
                state="contradicted",
                passage="Rated #1 in market share globally.",
                location="p3",
                explanation="Contradicted",
                why_it_matters="Legal",
            ),
        ]

        batch_output = generate_corrections(
            flags=flags,
            content_understanding=self.sample_context,
            client=self.mock_client,
        )

        self.assertIsInstance(batch_output, SuggestionsOutput)
        self.assertEqual(len(batch_output.corrections), 2)  # 2 actionable issues corrected
        for c in batch_output.corrections:
            self.assertIsInstance(c, CorrectionOutput)


if __name__ == "__main__":
    unittest.main()
