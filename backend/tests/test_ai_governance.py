"""Unit tests for Inkloom AI Governance Intelligence (Stage 5).

Owner: Sera
Tests empirical aggregation, recurring violation clustering, ambiguous guideline detection,
executive narrative generation, and deterministic mock mode execution.
"""

from typing import List
import pytest

from app.ai.client import GeminiClient
from app.ai.governance_intelligence import generate_governance_insights
from app.ai.schemas import (
    AmbiguousGuideline,
    GovernanceInsightsOutput,
    RecurringViolation,
)
from app.config import Settings
from app.models import Flag, FlagDraft, GuidelineRef


@pytest.fixture
def mock_client() -> GeminiClient:
    return GeminiClient(settings=Settings(mock_ai=True))


@pytest.fixture
def sample_guideline() -> GuidelineRef:
    return GuidelineRef(
        document="Brand Playbook v3",
        passage_ref="Section 1.3",
        excerpt="Avoid corporate buzzwords like synergy or disruptive.",
    )


@pytest.fixture
def sample_flags(sample_guideline: GuidelineRef) -> List[Flag]:
    return [
        Flag(
            id="f1",
            submission_id="sub-101",
            version=1,
            finding_type="brand",
            state="potential_issue",
            passage="disruptive synergy",
            location="characters 10-28",
            explanation="The buzzword 'synergy' contradicts plain-English communication principles.",
            why_it_matters="Corporate jargon damages credibility.",
            guideline_ref=sample_guideline,
            suggested_correction="effective collaboration",
            origin="module",
            status="open",
            needs_human=False,
            created_at="2026-11-13T10:00:00Z",
        ),
        Flag(
            id="f2",
            submission_id="sub-101",
            version=1,
            finding_type="brand",
            state="potential_issue",
            passage="disruptive",
            location="characters 35-45",
            explanation="The buzzword 'disruptive' contradicts plain-English communication principles.",
            why_it_matters="Corporate jargon damages credibility.",
            guideline_ref=sample_guideline,
            suggested_correction="innovative",
            origin="module",
            status="open",
            needs_human=False,
            created_at="2026-11-13T10:00:00Z",
        ),
        Flag(
            id="f3",
            submission_id="sub-102",
            version=1,
            finding_type="brand",
            state="unclear",
            passage="industry-leading agility",
            location="characters 0-24",
            explanation="Guideline on industry agility is ambiguous.",
            why_it_matters="Ambiguity leads to subjective reviews.",
            guideline_ref=sample_guideline,
            uncertainty_note="Ambiguous benchmark criteria.",
            suggested_correction=None,
            origin="module",
            status="open",
            needs_human=True,
            created_at="2026-11-13T11:00:00Z",
        ),
        Flag(
            id="f4",
            submission_id="sub-103",
            version=1,
            finding_type="claim",
            state="insufficient_evidence",
            passage="rated #1 worldwide",
            location="characters 5-24",
            explanation="No third-party independent benchmark was found for ranking assertion.",
            why_it_matters="Market supremacy requires verifiable citations.",
            guideline_ref=None,
            suggested_correction=None,
            origin="module",
            status="open",
            needs_human=True,
            created_at="2026-11-13T12:00:00Z",
        ),
    ]


class TestGovernanceIntelligence:
    """Test suite for Governance Intelligence aggregation and narrative synthesis."""

    def test_governance_empty_flags_handling(self, mock_client: GeminiClient):
        """Empty flags list returns graceful explanation without crashing or hallucinating."""
        res = generate_governance_insights(flags=[], total_reviews_analyzed=0, client=mock_client)
        assert isinstance(res, GovernanceInsightsOutput)
        assert res.total_reviews_analyzed == 0
        assert res.top_recurring_violations == []
        assert res.ambiguous_guidelines == []
        assert "Insufficient historical review data" in res.summary_narrative

    def test_governance_recurring_violation_aggregation(
        self, sample_flags: List[Flag], mock_client: GeminiClient
    ):
        """Aggregates recurring violations, sets frequencies and recommendations."""
        res = generate_governance_insights(flags=sample_flags, total_reviews_analyzed=3, client=mock_client)
        assert isinstance(res, GovernanceInsightsOutput)
        assert res.total_reviews_analyzed == 3
        assert len(res.top_recurring_violations) >= 1

        buzzword_item = next(
            (v for v in res.top_recurring_violations if "Buzzword" in v.rule_or_topic),
            None,
        )
        assert buzzword_item is not None
        assert buzzword_item.frequency == 2
        assert buzzword_item.severity == "high"
        assert "plain-English" in buzzword_item.recommendation or "training" in buzzword_item.recommendation

    def test_governance_ambiguous_guidelines_detection(
        self, sample_flags: List[Flag], mock_client: GeminiClient
    ):
        """Identifies ambiguous guidelines causing high human reviewer escalation."""
        res = generate_governance_insights(flags=sample_flags, client=mock_client)
        assert isinstance(res, GovernanceInsightsOutput)
        assert len(res.ambiguous_guidelines) >= 1

        ambiguous = res.ambiguous_guidelines[0]
        assert isinstance(ambiguous, AmbiguousGuideline)
        assert ambiguous.human_escalation_count >= 1
        assert len(ambiguous.reason_for_ambiguity) > 10
        assert len(ambiguous.suggested_clarification) > 10

    def test_governance_executive_summary_narrative(
        self, sample_flags: List[Flag], mock_client: GeminiClient
    ):
        """Formulates an objective, executive health summary from empirical flag metrics."""
        res = generate_governance_insights(flags=sample_flags, client=mock_client)
        assert isinstance(res.summary_narrative, str)
        assert "Executive Governance Review" in res.summary_narrative
        assert "Analyzed 3 submissions" in res.summary_narrative
        assert "4 total compliance checks" in res.summary_narrative

    def test_governance_custom_mock_handler_override(self):
        """Custom mock handler in GeminiClient correctly overrides default mock generation."""
        custom_insights = GovernanceInsightsOutput(
            total_reviews_analyzed=99,
            top_recurring_violations=[
                RecurringViolation(
                    rule_or_topic="Custom Violation",
                    frequency=10,
                    severity="high",
                    recommendation="Custom training",
                )
            ],
            ambiguous_guidelines=[],
            summary_narrative="Custom executive summary.",
        )
        client = GeminiClient(settings=Settings(mock_ai=True))
        client.register_mock_handler(GovernanceInsightsOutput, lambda prompt, **kw: custom_insights)

        res = generate_governance_insights(flags=[{"state": "potential_issue"}], client=client)
        assert res.total_reviews_analyzed == 99
        assert res.summary_narrative == "Custom executive summary."
        assert res.top_recurring_violations[0].rule_or_topic == "Custom Violation"

