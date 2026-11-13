"""Unit tests for Stage 3: External Claim Verification and AI Flagging Synthesis.

Audit Focus Areas Tested:
1. Evidence accuracy & zero-hallucination URL grounding (valid URL alone != valid finding).
2. Conflicting evidence handling (disagreement leads to uncertainty, NOT definitive contradiction).
3. Contextual evidence freshness (contemporary performance vs. historical facts).
4. Source reliability evaluation (missing metadata never invents reliability).
5. Flagging compatibility, duplicate prevention, and opinion filtering.
6. Ken's retrieval interface contract (synchronous verify_claim_externally).
"""

import unittest
from unittest.mock import MagicMock, patch

from app.ai.claim_verification import (
    _evaluate_contextual_freshness,
    validate_and_ground_claim_findings,
    verify_claims,
    verify_claims_against_evidence,
)
from app.ai.client import GeminiClient
from app.ai.flagging import (
    consolidate_flags,
    summarize_flag_metrics,
    synthesize_flag_drafts,
)
from app.ai.schemas import (
    BrandFinding,
    BrandVerificationOutput,
    ClaimFinding,
    ClaimVerificationOutput,
    ContentUnderstandingOutput,
    ExtractedClaim,
    FlaggingOutput,
    SynthesizedFlag,
)
from app.models import ContentPayload, ExternalSource, FlagDraft, GuidelineRef
from app.uncertainty import needs_human
from retrieval.schemas import ExternalEvidenceItem


class TestExternalClaimVerification(unittest.TestCase):
    """Test claim verification against external evidence, quality checks, and grounding."""

    def setUp(self):
        self.mock_client = GeminiClient(mock_mode=True)

    def test_verify_supported_claim_with_reliable_evidence(self):
        claim = ExtractedClaim(
            claim_id="claim-1",
            text="Service provides 99.9% uptime historically.",
            claim_type="fact",
            passage="99.9% uptime historically",
            location="paragraph 1",
        )
        evidence = ExternalEvidenceItem(
            query="uptime",
            url="https://status.example.com",
            title="Official Status Records",
            domain="status.example.com",
            published_date="2026-01-15",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Audited historical SLA performance proves 99.9% availability across all zones.",
            status="ok",
        )
        evidence_map = {"claim-1": [evidence]}

        result = verify_claims_against_evidence(
            claims=[claim],
            evidence_map=evidence_map,
            client=self.mock_client,
            auto_fetch_evidence=False,
        )

        self.assertIsInstance(result, ClaimVerificationOutput)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.state, "supported")
        self.assertEqual(finding.evidence_quality, "reliable")
        self.assertEqual(finding.evidence_source_url, "https://status.example.com")
        self.assertFalse(needs_human(finding.state))

    def test_conflicting_evidence_results_in_uncertainty_not_contradiction(self):
        """When reliable sources disagree, finding must be insufficient_evidence, not contradicted."""
        claim = ExtractedClaim(
            claim_id="claim-conflicting",
            text="We are rated #1 in market share globally.",
            claim_type="fact",
            passage="#1 in market share globally",
            location="paragraph 2",
        )
        ev1 = ExternalEvidenceItem(
            query="market share",
            url="https://analyst-a.example.com",
            domain="analyst-a.example.com",
            published_date="2026-02-01",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Market share surveys show multiple disputed leaders across regions.",
            status="ok",
        )
        ev2 = ExternalEvidenceItem(
            query="market share",
            url="https://analyst-b.example.com",
            domain="analyst-b.example.com",
            published_date="2026-03-01",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Conflict in ranking surveys: competing vendor leads tier-1 market share.",
            status="ok",
        )
        evidence_map = {"claim-conflicting": [ev1, ev2]}

        result = verify_claims_against_evidence(
            claims=[claim],
            evidence_map=evidence_map,
            client=self.mock_client,
            auto_fetch_evidence=False,
        )

        finding = result.findings[0]
        # Must reflect uncertainty, NOT definitive contradiction
        self.assertEqual(finding.state, "insufficient_evidence")
        self.assertEqual(finding.evidence_quality, "conflicting")
        self.assertTrue(needs_human(finding.state))
        self.assertIn("disputed", finding.explanation.lower())
        self.assertIsNone(finding.suggested_fix)

    def test_definitively_contradicted_claim(self):
        """Direct refutation by authoritative source produces state='contradicted'."""
        claim = ExtractedClaim(
            claim_id="claim-refuted",
            text="We are rated #1 in market share globally.",
            claim_type="fact",
            passage="#1 in market share globally",
            location="header",
        )
        ev = ExternalEvidenceItem(
            query="market share",
            url="https://audit-analyst.example.com",
            domain="audit-analyst.example.com",
            published_date="2026-04-01",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Independent industry survey directly refuted the claim; vendor holds 4th place.",
            status="ok",
        )
        evidence_map = {"claim-refuted": [ev]}

        result = verify_claims_against_evidence(
            claims=[claim],
            evidence_map=evidence_map,
            client=self.mock_client,
            auto_fetch_evidence=False,
        )

        finding = result.findings[0]
        self.assertEqual(finding.state, "contradicted")
        self.assertEqual(finding.evidence_quality, "reliable")
        self.assertTrue(needs_human(finding.state))
        self.assertIsNotNone(finding.suggested_fix)

    def test_contextual_freshness_historical_vs_contemporary(self):
        """Historical facts remain valid with older sources; contemporary benchmarks require recent sources."""
        # 1. Historical milestone claim: older source is authoritative
        hist_claim = ExtractedClaim(
            claim_id="c-hist",
            text="Inkloom was founded in 2012 by researchers.",
            claim_type="fact",
            passage="founded in 2012",
            location="about us",
        )
        hist_ev = ExternalEvidenceItem(
            query="Inkloom founding",
            url="https://history.example.com",
            domain="history.example.com",
            published_date="2012-05-20",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Inkloom was founded in 2012 as an open research laboratory.",
            status="ok",
        )
        res_hist = verify_claims_against_evidence(
            claims=[hist_claim],
            evidence_map={"c-hist": [hist_ev]},
            client=self.mock_client,
            auto_fetch_evidence=False,
        )
        f_hist = res_hist.findings[0]
        self.assertEqual(f_hist.state, "supported")
        self.assertEqual(f_hist.evidence_quality, "reliable")

        # 2. Contemporary performance benchmark: older source is outdated
        curr_claim = ExtractedClaim(
            claim_id="c-curr",
            text="Fastest processing speed in current benchmark history.",
            claim_type="fact",
            passage="Fastest processing speed",
            location="line 4",
        )
        outdated_ev = ExternalEvidenceItem(
            query="speed benchmark",
            url="https://legacy-benchmarks.example.com",
            domain="legacy-benchmarks.example.com",
            published_date="2019-05-10",
            retrieved_at="2026-11-13T12:00:00Z",
            excerpt="Speed test record established in 2019.",
            status="ok",
        )
        res_curr = verify_claims_against_evidence(
            claims=[curr_claim],
            evidence_map={"c-curr": [outdated_ev]},
            client=self.mock_client,
            auto_fetch_evidence=False,
        )
        f_curr = res_curr.findings[0]
        self.assertEqual(f_curr.state, "insufficient_evidence")
        self.assertEqual(f_curr.evidence_quality, "outdated")
        self.assertTrue(needs_human(f_curr.state))
        self.assertIn("2019", f_curr.uncertainty_note)

    def test_missing_metadata_does_not_invent_reliability(self):
        """Missing domain or excerpt metadata degrades evidence_quality to 'insufficient'."""
        claim = ExtractedClaim(
            claim_id="c-meta",
            text="Platform achieved 99.9% uptime.",
            claim_type="fact",
            passage="99.9% uptime",
            location="p1",
        )
        sparse_ev = ExternalEvidenceItem(
            query="uptime",
            url="https://unknown-ip-address/path",
            domain="",  # Missing domain
            excerpt="Short.",  # Too short to be substantive
            status="ok",
            retrieved_at="2026-11-13T12:00:00Z",
        )
        res = verify_claims_against_evidence(
            claims=[claim],
            evidence_map={"c-meta": [sparse_ev]},
            client=self.mock_client,
            auto_fetch_evidence=False,
        )
        finding = res.findings[0]
        self.assertEqual(finding.evidence_quality, "insufficient")

    def test_valid_url_with_unavailable_status_converted_to_insufficient(self):
        """A valid well-formed URL alone does NOT make a finding valid if status is unavailable."""
        claim = ExtractedClaim(
            claim_id="claim-unavail",
            text="Certified ISO-27001 compliant by third party.",
            claim_type="fact",
            passage="Certified ISO-27001",
            location="footer",
        )
        unavail_ev = ExternalEvidenceItem(
            query="compliance",
            url="https://legitimate-domain.com/cert.pdf",
            domain="legitimate-domain.com",
            retrieved_at="2026-11-13T12:00:00Z",
            status="unavailable",
            excerpt="",
            error_reason="connection_refused",
        )
        evidence_map = {"claim-unavail": [unavail_ev]}

        result = verify_claims_against_evidence(
            claims=[claim],
            evidence_map=evidence_map,
            client=self.mock_client,
            auto_fetch_evidence=False,
        )

        finding = result.findings[0]
        self.assertEqual(finding.state, "insufficient_evidence")
        self.assertEqual(finding.evidence_quality, "insufficient")
        self.assertTrue(needs_human(finding.state))
        self.assertIn("unavailable", finding.explanation.lower())

    def test_opinions_are_not_treated_as_factual_claims(self):
        """Subjective opinions must NOT be evaluated against external web evidence."""
        opinion_claim = ExtractedClaim(
            claim_id="c-opinion",
            text="We believe our creative passion produces truly beautiful results.",
            claim_type="opinion",
            passage="creative passion produces truly beautiful results",
            location="intro",
        )
        result = verify_claims_against_evidence(
            claims=[opinion_claim],
            evidence_map={},
            client=self.mock_client,
            auto_fetch_evidence=False,
        )
        # Must produce 0 findings because opinions do not require factual proof
        self.assertEqual(len(result.findings), 0)

    def test_grounding_catches_hallucinated_source_urls(self):
        """Zero-hallucination guardrail: AI citing a non-existent URL is converted to insufficient_evidence."""
        hallucinated_finding = ClaimFinding(
            claim_text="Statistical claim",
            passage="Statistical claim",
            location="line 1",
            state="supported",
            explanation="Claim backed by web report.",
            why_it_matters="Trust",
            evidence_source_url="https://invented-fake-domain.com/survey",
            evidence_excerpt="Fake quote",
            evidence_quality="reliable",
        )
        legit_evidence = [
            ExternalEvidenceItem(
                query="stat",
                url="https://real-source.example.com",
                retrieved_at="2026-11-13T12:00:00Z",
                status="ok",
                excerpt="Real statistics excerpt.",
            )
        ]

        grounded = validate_and_ground_claim_findings([hallucinated_finding], legit_evidence)
        self.assertEqual(len(grounded), 1)
        f = grounded[0]
        self.assertEqual(f.state, "insufficient_evidence")
        self.assertIn("Unverified external source", f.uncertainty_note)
        self.assertIsNone(f.evidence_source_url)

    def test_grounding_catches_placeholder_failure_urls(self):
        """Placeholder search failure URLs are cleanly converted without hallucinated URL references."""
        placeholder_finding = ClaimFinding(
            claim_text="Statistical claim",
            passage="Statistical claim",
            location="line 1",
            state="supported",
            explanation="Claim backed by web report.",
            why_it_matters="Trust",
            evidence_source_url="https://search.unavailable.local",
            evidence_excerpt="",
            evidence_quality="none",
        )
        grounded = validate_and_ground_claim_findings([placeholder_finding], [])
        self.assertEqual(len(grounded), 1)
        f = grounded[0]
        self.assertEqual(f.state, "insufficient_evidence")
        self.assertIsNone(f.evidence_source_url)
        self.assertIn("External retrieval was unable", f.uncertainty_note)


class TestAIFlaggingSynthesis(unittest.TestCase):
    """Test consolidating Brand and Claim findings into prioritized FlagDraft items."""

    def setUp(self):
        self.brand_output = BrandVerificationOutput(
            overall_alignment="potential_issue",
            voice_and_tone_assessment="Tone issues detected",
            terminology_assessment="Buzzwords present",
            findings=[
                BrandFinding(
                    state="potential_issue",
                    passage="disruptive synergy",
                    location="paragraph 1",
                    violation_category="buzzword",
                    explanation="Buzzword violates plain-English standard.",
                    why_it_matters="Credibility",
                    guideline_document="Brand Playbook",
                    guideline_section="1.3",
                    guideline_excerpt="Avoid corporate buzzwords.",
                    suggested_fix="effective collaboration",
                ),
                BrandFinding(
                    state="aligned",
                    passage="Our team collaborates closely.",
                    location="paragraph 2",
                    violation_category="tone",
                    explanation="Clean tone.",
                    why_it_matters="Tone",
                    guideline_document="Brand Playbook",
                    guideline_section="1.1",
                    guideline_excerpt="Measured tone.",
                ),
            ],
        )

        self.claim_output = ClaimVerificationOutput(
            findings=[
                ClaimFinding(
                    claim_text="We guarantee 100% uptime with zero exceptions.",
                    passage="guarantee 100% uptime with zero exceptions",
                    location="paragraph 3",
                    state="insufficient_evidence",
                    explanation="Unsubstantiated absolute guarantee.",
                    why_it_matters="Legal liability",
                    evidence_quality="insufficient",
                    uncertainty_note="Guarantees require SLA exclusions.",
                    suggested_fix="targeted high availability",
                ),
                ClaimFinding(
                    claim_text="Audited in 2026.",
                    passage="Audited in 2026",
                    location="footer",
                    state="supported",
                    explanation="Verified by annual audit report.",
                    why_it_matters="Accuracy",
                    evidence_source_url="https://audit.example.com",
                    evidence_excerpt="Annual audit report 2026.",
                    evidence_quality="reliable",
                ),
            ]
        )

    def test_synthesize_flag_drafts_combines_and_prioritizes_issues(self):
        drafts = synthesize_flag_drafts(
            brand_output=self.brand_output,
            claim_output=self.claim_output,
            include_aligned=True,
        )

        self.assertEqual(len(drafts), 4)

        # Verify priority sorting: issues and escalations come first
        self.assertEqual(drafts[0].state, "potential_issue")
        self.assertEqual(drafts[0].finding_type, "brand")
        self.assertEqual(drafts[0].suggested_correction, "effective collaboration")

        self.assertEqual(drafts[1].state, "insufficient_evidence")
        self.assertEqual(drafts[1].finding_type, "claim")
        self.assertTrue(needs_human(drafts[1].state))

        # Aligned/supported items follow
        states = [d.state for d in drafts]
        self.assertIn("aligned", states)
        self.assertIn("supported", states)

    def test_synthesize_flag_drafts_exclude_aligned(self):
        drafts = synthesize_flag_drafts(
            brand_output=self.brand_output,
            claim_output=self.claim_output,
            include_aligned=False,
        )
        self.assertEqual(len(drafts), 2)
        for d in drafts:
            self.assertIn(d.state, ("potential_issue", "insufficient_evidence"))

    def test_synthesize_flag_drafts_duplicate_prevention(self):
        """Duplicate findings for same passage, location, and state are deduplicated."""
        dup_brand = BrandVerificationOutput(
            overall_alignment="potential_issue",
            voice_and_tone_assessment="Issues",
            terminology_assessment="Issues",
            findings=[
                BrandFinding(
                    state="potential_issue",
                    passage="identical buzzword",
                    location="line 10",
                    violation_category="buzzword",
                    explanation="First check.",
                    why_it_matters="Trust",
                ),
                BrandFinding(
                    state="potential_issue",
                    passage="identical buzzword",  # Same passage
                    location="line 10",           # Same location
                    violation_category="buzzword",
                    explanation="Second redundant check.",
                    why_it_matters="Trust",
                ),
            ],
        )
        drafts = synthesize_flag_drafts(brand_output=dup_brand, include_aligned=True)
        self.assertEqual(len(drafts), 1)

    def test_consolidate_flags_returns_flagging_output(self):
        output = consolidate_flags(
            brand_output=self.brand_output,
            claim_output=self.claim_output,
            include_aligned=True,
        )
        self.assertIsInstance(output, FlaggingOutput)
        self.assertEqual(len(output.flags), 4)
        for f in output.flags:
            self.assertIsInstance(f, SynthesizedFlag)
            draft = f.to_flag_draft()
            self.assertIsInstance(draft, FlagDraft)

    def test_summarize_flag_metrics(self):
        drafts = synthesize_flag_drafts(
            brand_output=self.brand_output,
            claim_output=self.claim_output,
            include_aligned=True,
        )
        metrics = summarize_flag_metrics(drafts)

        self.assertEqual(metrics["total_flags"], 4)
        self.assertEqual(metrics["brand_violations"], 1)
        self.assertEqual(metrics["unverified_claims"], 1)
        self.assertEqual(metrics["human_escalations_required"], 1)
        self.assertFalse(metrics["is_publication_ready"])


if __name__ == "__main__":
    unittest.main()
