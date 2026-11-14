"""Unit tests for Evidence-First finding presentation, verification grounding, and span validation."""

import pytest

from app.ai.brand_verification import (
    brand_finding_to_flag_draft,
    extract_verbatim_guideline_passage,
    locate_flagged_span,
)
from app.ai.claim_verification import claim_finding_to_flag_draft
from app.ai.flagging import deduplicate_and_synthesize_flag_drafts
from app.ai.schemas import BrandFinding, ClaimFinding
from app.models import (
    ExternalEvidence,
    ExternalSource,
    Flag,
    FlagDraft,
    FlaggedSpan,
    GuidelineRef,
    InternalEvidence,
    SuggestionDetails,
)
from app.pipeline import _draft_to_flag, _make_error_flag


class TestVerbatimGuidelineExtraction:
    def test_verbatim_substring_extracted_cleanly(self):
        chunk_text = (
            "Section 2: Typography and Logo Usage. "
            "Never use drop shadows or gradients behind the primary brand mark. "
            "Maintain at least 20px clear margin around the symbol."
        )
        candidate = "Never use drop shadows or gradients behind the primary brand mark."
        result = extract_verbatim_guideline_passage(candidate, chunk_text)
        assert result == candidate

    def test_case_insensitive_verbatim_preserves_chunk_casing(self):
        chunk_text = "Always use clear, plain English and avoid buzzwords."
        candidate = "always use clear, plain english and avoid buzzwords."
        result = extract_verbatim_guideline_passage(candidate, chunk_text)
        assert result == "Always use clear, plain English and avoid buzzwords."

    def test_ai_paraphrase_is_rejected_never_labeled_verbatim(self):
        chunk_text = "Always use clear, plain English and avoid buzzwords."
        paraphrase = "The guidelines require using simple words and no jargon whatsoever."
        result = extract_verbatim_guideline_passage(paraphrase, chunk_text)
        assert result is None

    def test_empty_or_none_inputs_return_none_safely(self):
        assert extract_verbatim_guideline_passage(None, "Some chunk text") is None
        assert extract_verbatim_guideline_passage("Rule sentence", None) is None
        assert extract_verbatim_guideline_passage("", "") is None


class TestFlaggedSpanLocation:
    def test_unique_phrase_offsets_validated(self):
        full_text = "Welcome to Inkloom. We deliver disruptive synergy for enterprises across the globe."
        phrase = "disruptive synergy"
        span = locate_flagged_span(full_text=full_text, passage=phrase)

        assert span.exact_text == phrase
        assert span.start_char == 31
        assert span.end_char == 49
        assert full_text[span.start_char : span.end_char] == phrase

    def test_repeated_phrase_handles_offsets_safely(self):
        full_text = "High performance. We guarantee high performance throughout all operations."
        phrase = "high performance"
        # Without context, matches first occurrence
        span1 = locate_flagged_span(full_text=full_text, passage=phrase)
        assert span1.start_char == 0
        assert span1.end_char == 16

        # With surrounding context as passage, matches second occurrence
        span2 = locate_flagged_span(
            full_text=full_text,
            passage="We guarantee high performance throughout all operations.",
            offending_words="high performance",
        )
        assert span2.start_char == 31
        assert span2.end_char == 47
        assert full_text[span2.start_char : span2.end_char].lower() == phrase

    def test_missing_phrase_returns_safe_fallback_without_invented_offsets(self):
        full_text = "Completely different text content here."
        phrase = "unmatched target phrase"
        span = locate_flagged_span(full_text=full_text, passage=phrase)

        assert span.exact_text == phrase
        assert span.start_char is None
        assert span.end_char is None
        assert span.surrounding_passage == phrase


class TestEvidenceModelsAndSyncing:
    def test_internal_only_mode_determined_and_legacy_synced(self):
        draft = FlagDraft(
            finding_type="brand",
            state="potential_issue",
            passage="buzzword phrase",
            location="para 1",
            explanation="Violates tone guidelines",
            why_it_matters="Credibility",
            internal_evidence=[
                InternalEvidence(
                    document="Tone Guide",
                    passage_ref="1.2",
                    excerpt="Avoid buzzwords.",
                    chunk_id="chunk-42",
                    section="Tone",
                    page_number=3,
                    similarity=0.91,
                    exact_violated_passage="Avoid buzzwords.",
                )
            ],
            external_evidence=[],
        )

        assert draft.evidence_mode == "internal_only"
        assert draft.guideline_ref is not None
        assert draft.guideline_ref.document == "Tone Guide"
        assert draft.guideline_ref.chunk_id == "chunk-42"
        assert draft.guideline_ref.page_number == 3
        assert draft.guideline_ref.exact_violated_passage == "Avoid buzzwords."
        assert draft.exact_violated_passage == "Avoid buzzwords."
        assert len(draft.guideline_refs) == 1

    def test_external_only_mode_determined_and_legacy_synced(self):
        draft = FlagDraft(
            finding_type="claim",
            state="contradicted",
            passage="100% uptime guaranteed",
            location="para 2",
            explanation="SLA reports monthly maintenance windows",
            why_it_matters="Warranty risk",
            internal_evidence=[],
            external_evidence=[
                ExternalEvidence(
                    title="Uptime Status",
                    url="https://status.example.com",
                    domain="status.example.com",
                    published_date="2026-01-15",
                    excerpt="Maintenance occurs monthly.",
                    evidence_quality="reliable",
                )
            ],
        )

        assert draft.evidence_mode == "external_only"
        assert len(draft.external_sources) == 1
        assert draft.external_sources[0].url == "https://status.example.com"
        assert draft.external_sources[0].domain == "status.example.com"
        assert draft.external_sources[0].published_date == "2026-01-15"

    def test_combined_mode_determined_when_both_present(self):
        draft = FlagDraft(
            finding_type="claim",
            state="contradicted",
            passage="Test passage",
            location="para 1",
            explanation="Explanation",
            why_it_matters="Impact",
            internal_evidence=[
                InternalEvidence(document="Doc A", passage_ref="1", excerpt="Guideline A")
            ],
            external_evidence=[
                ExternalEvidence(url="https://exa.ai/ref", excerpt="External ref")
            ],
        )
        assert draft.evidence_mode == "combined"
        assert len(draft.internal_evidence) == 1
        assert len(draft.external_evidence) == 1

    def test_insufficient_evidence_mode_assigned(self):
        draft = FlagDraft(
            finding_type="claim",
            state="insufficient_evidence",
            passage="Unsubstantiated novel claim",
            location="para 3",
            explanation="No internal or external proof found",
            why_it_matters="Accuracy risk",
            internal_evidence=[],
            external_evidence=[],
        )
        assert draft.evidence_mode == "insufficient_evidence"

    def test_legacy_construction_populates_new_fields_backward_compatibly(self):
        draft = FlagDraft(
            finding_type="brand",
            state="potential_issue",
            passage="legacy passage text",
            location="para 1",
            explanation="Legacy explanation",
            why_it_matters="Legacy impact",
            guideline_ref=GuidelineRef(
                document="Brand Book",
                passage_ref="Sec 3",
                excerpt="Rule excerpt text",
                document_id="doc-1",
                chunk_id="chk-99",
                page_number=12,
            ),
            external_sources=[
                ExternalSource(
                    url="https://example.com/source",
                    excerpt="External excerpt",
                    title="Example Source",
                    domain="example.com",
                )
            ],
            suggested_correction="modern replacement text",
        )

        assert draft.evidence_mode == "combined"
        assert len(draft.internal_evidence) == 1
        assert draft.internal_evidence[0].document == "Brand Book"
        assert draft.internal_evidence[0].chunk_id == "chk-99"
        assert draft.internal_evidence[0].page_number == 12

        assert len(draft.external_evidence) == 1
        assert draft.external_evidence[0].title == "Example Source"
        assert draft.external_evidence[0].domain == "example.com"

        assert draft.flagged_span is not None
        assert draft.flagged_span.exact_text == "legacy passage text"

        assert draft.suggestion is not None
        assert draft.suggestion.suggested_replacement == "modern replacement text"
        assert draft.suggested_correction == "modern replacement text"


class TestPipelineEvidencePreservation:
    def test_draft_to_flag_preserves_all_evidence_and_span_fields(self):
        draft = FlagDraft(
            finding_type="brand",
            state="potential_issue",
            passage="disruptive synergy",
            location="para 1",
            explanation="Avoid buzzwords",
            why_it_matters="Trust",
            internal_evidence=[
                InternalEvidence(
                    document="Brand Playbook",
                    passage_ref="2.1",
                    excerpt="Avoid buzzwords such as disruptive synergy.",
                    chunk_id="chk-55",
                    section="Voice",
                    page_number=4,
                    similarity=0.88,
                    exact_violated_passage="Avoid buzzwords such as disruptive synergy.",
                )
            ],
            external_evidence=[],
            flagged_span=FlaggedSpan(
                exact_text="disruptive synergy",
                start_char=10,
                end_char=28,
                surrounding_passage="We value disruptive synergy.",
                location_label="para 1",
            ),
            suggestion=SuggestionDetails(
                suggested_replacement="meaningful collaboration",
                change_rationale="Plain English",
                preserved_entities=["enterprise"],
            ),
        )

        flag = _draft_to_flag(draft, "sub-123", 1, "2026-11-14T10:00:00Z")

        assert isinstance(flag, Flag)
        assert flag.submission_id == "sub-123"
        assert flag.evidence_mode == "internal_only"
        assert len(flag.internal_evidence) == 1
        assert flag.internal_evidence[0].chunk_id == "chk-55"
        assert flag.internal_evidence[0].page_number == 4
        assert flag.exact_violated_passage == "Avoid buzzwords such as disruptive synergy."
        assert flag.flagged_span.start_char == 10
        assert flag.flagged_span.end_char == 28
        assert flag.suggestion.suggested_replacement == "meaningful collaboration"
        assert flag.suggested_correction == "meaningful collaboration"
        assert flag.passage == "disruptive synergy"

    def test_make_error_flag_initializes_insufficient_evidence(self):
        flag = _make_error_flag("verification", "sub-456", 2, "2026-11-14T10:00:00Z")
        assert flag.evidence_mode == "insufficient_evidence"
        assert flag.state == "insufficient_evidence"
        assert flag.needs_human is True
        assert flag.internal_evidence == []
        assert flag.external_evidence == []
