"""Tests for uncertainty detection and needs_human flag assignment."""

from app.models import ContentPayload, FlagDraft
from app.pipeline import run_pipeline
from app.uncertainty import needs_human


def test_needs_human_predicate():
    # Uncertain states -> True
    assert needs_human("unclear") is True
    assert needs_human("contradicted") is True
    assert needs_human("insufficient_evidence") is True

    # Deterministic states -> False
    assert needs_human("aligned") is False
    assert needs_human("potential_issue") is False
    assert needs_human("supported") is False

    # Unknown or empty -> False
    assert needs_human("other") is False
    assert needs_human("") is False


def test_pipeline_assigns_needs_human_correctly():
    content = ContentPayload(content_type="text", text="Checking uncertainty flags")

    # Custom plugin returning various states
    def custom_verification(c):
        return [
            FlagDraft(
                finding_type="claim",
                state="contradicted",
                passage="100% serverless latency guarantee.",
                location="p1",
                explanation="Contradicted by physics and test evidence.",
                why_it_matters="False performance claim.",
                origin="module",
            ),
            FlagDraft(
                finding_type="claim",
                state="insufficient_evidence",
                passage="Voted #1 developer tool in Europe.",
                location="p2",
                explanation="No verifiable citation found.",
                why_it_matters="Unsubstantiated market claim.",
                origin="module",
            ),
            FlagDraft(
                finding_type="claim",
                state="supported",
                passage="Supports Python 3.10 and newer.",
                location="p3",
                explanation="Matches technical specifications.",
                why_it_matters="Accurate system requirements.",
                origin="module",
            ),
        ]

    def custom_brand(c, g):
        return [
            FlagDraft(
                finding_type="brand",
                state="unclear",
                passage="Disruptive synergy for maximal impact.",
                location="header",
                explanation="Excessive jargon may conflict with plain-English tone.",
                why_it_matters="Brand voice ambiguity.",
                origin="module",
            ),
            FlagDraft(
                finding_type="brand",
                state="potential_issue",
                passage="Don't miss out on this deal.",
                location="footer",
                explanation="Borderline aggressive FOMO marketing.",
                why_it_matters="Tone guideline deviation.",
                origin="module",
            ),
            FlagDraft(
                finding_type="brand",
                state="aligned",
                passage="Built for enterprise reliability.",
                location="tagline",
                explanation="Fully aligned with core value propositions.",
                why_it_matters="Consistent messaging.",
                origin="module",
            ),
        ]

    flags, degraded = run_pipeline(
        content=content,
        submission_id="sub-unc-1",
        verification_fn=custom_verification,
        brand_check_fn=custom_brand,
    )

    state_needs_human = {f.state: f.needs_human for f in flags}
    assert state_needs_human["contradicted"] is True
    assert state_needs_human["insufficient_evidence"] is True
    assert state_needs_human["unclear"] is True
    assert state_needs_human["supported"] is False
    assert state_needs_human["potential_issue"] is False
    assert state_needs_human["aligned"] is False

