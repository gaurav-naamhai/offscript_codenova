"""AI Flagging Synthesis module for Inkloom AI.

Owner: Sera
Consolidates findings from Content Understanding, Brand Verification,
and External Claim Verification into unified, prioritized FlagDraft items.
Categorizes issues, attaches guideline/evidence citations, computes human
review escalation, and aligns with Gaurav's domain pipeline schemas.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.ai.schemas import (
    BrandFinding,
    BrandVerificationOutput,
    ClaimFinding,
    ClaimVerificationOutput,
    ContentUnderstandingOutput,
    FlaggingOutput,
    SynthesizedFlag,
)
from app.models import ExternalSource, FlagDraft, GuidelineRef
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)


def synthesize_flag_drafts(
    brand_output: Optional[BrandVerificationOutput] = None,
    claim_output: Optional[ClaimVerificationOutput] = None,
    content_understanding: Optional[ContentUnderstandingOutput] = None,
    include_aligned: bool = True,
) -> List[FlagDraft]:
    """Synthesize Brand and Claim findings into Gaurav's domain FlagDraft objects.

    Includes duplicate prevention, priority ordering, and strict uncertainty mapping.

    Args:
        brand_output: Output from brand verification.
        claim_output: Output from external claim verification.
        content_understanding: Context understanding output.
        include_aligned: Whether to include 'aligned' and 'supported' items for comprehensive review.

    Returns:
        List of deduplicated domain FlagDraft objects ready for pipeline and database storage.
    """
    drafts: List[FlagDraft] = []
    seen_keys: Set[Tuple[str, str, str, str]] = set()

    # 1. Process Brand Findings
    if brand_output and brand_output.findings:
        for bf in brand_output.findings:
            if not include_aligned and bf.state == "aligned":
                continue

            # Deduplication key: (finding_type, normalized_passage, location, state)
            dedup_key = (
                "brand",
                bf.passage.strip().lower(),
                bf.location.strip().lower(),
                bf.state,
            )
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            g_ref = None
            if bf.guideline_document and bf.guideline_document not in ("N/A", "Unverified Reference"):
                g_ref = GuidelineRef(
                    document=bf.guideline_document,
                    passage_ref=bf.guideline_section or "Rule",
                    excerpt=bf.guideline_excerpt or "",
                    source_reference=None,
                )

            drafts.append(
                FlagDraft(
                    finding_type="brand",
                    state=bf.state,
                    passage=bf.passage,
                    location=bf.location,
                    explanation=bf.explanation,
                    why_it_matters=bf.why_it_matters,
                    guideline_ref=g_ref,
                    guideline_refs=[g_ref] if g_ref else [],
                    external_sources=[],
                    uncertainty_note=bf.uncertainty_note,
                    suggested_correction=bf.suggested_fix,
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

    # 2. Process Claim Findings
    if claim_output and claim_output.findings:
        for cf in claim_output.findings:
            if not include_aligned and cf.state == "supported":
                continue

            # Deduplication key: (finding_type, normalized_passage, location, state)
            dedup_key = (
                "claim",
                cf.passage.strip().lower(),
                cf.location.strip().lower(),
                cf.state,
            )
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            ext_sources = list(cf.external_sources)
            if not ext_sources and cf.evidence_source_url and cf.evidence_excerpt:
                ext_sources = [
                    ExternalSource(url=cf.evidence_source_url, excerpt=cf.evidence_excerpt)
                ]

            drafts.append(
                FlagDraft(
                    finding_type="claim",
                    state=cf.state,
                    passage=cf.passage,
                    location=cf.location,
                    explanation=cf.explanation,
                    why_it_matters=cf.why_it_matters,
                    guideline_ref=None,
                    guideline_refs=[],
                    external_sources=ext_sources,
                    uncertainty_note=cf.uncertainty_note,
                    suggested_correction=cf.suggested_fix,
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

    # Sort drafts: actionable issues and human review escalations first, followed by aligned checks
    def sort_key(d: FlagDraft) -> int:
        if d.state in ("contradicted", "potential_issue"):
            return 0  # Highest priority: direct violations
        if d.state in ("unclear", "insufficient_evidence"):
            return 1  # Medium priority: uncertainty / missing evidence
        return 2      # Low priority: aligned / supported

    drafts.sort(key=sort_key)
    return drafts


def consolidate_flags(
    brand_output: Optional[BrandVerificationOutput] = None,
    claim_output: Optional[ClaimVerificationOutput] = None,
    content_understanding: Optional[ContentUnderstandingOutput] = None,
    include_aligned: bool = True,
) -> FlaggingOutput:
    """Consolidate findings into structured SynthesizedFlag objects for AI consumers."""
    flag_drafts = synthesize_flag_drafts(
        brand_output=brand_output,
        claim_output=claim_output,
        content_understanding=content_understanding,
        include_aligned=include_aligned,
    )

    synthesized = [
        SynthesizedFlag(
            finding_type=d.finding_type,
            state=d.state,
            passage=d.passage,
            location=d.location,
            explanation=d.explanation,
            why_it_matters=d.why_it_matters,
            guideline_ref=d.guideline_ref,
            guideline_refs=d.guideline_refs,
            external_sources=d.external_sources,
            uncertainty_note=d.uncertainty_note,
            suggested_correction=d.suggested_correction,
            origin=d.origin,
            status=d.status,
            comments=d.comments,
        )
        for d in flag_drafts
    ]

    return FlaggingOutput(flags=synthesized)


def summarize_flag_metrics(flags: List[FlagDraft]) -> Dict[str, Any]:
    """Compute summary governance metrics from synthesized flags."""
    total = len(flags)
    brand_issues = sum(1 for f in flags if f.finding_type == "brand" and f.state == "potential_issue")
    claim_issues = sum(1 for f in flags if f.finding_type == "claim" and f.state in ("contradicted", "insufficient_evidence"))
    human_escalations = sum(1 for f in flags if needs_human(f.state))

    return {
        "total_flags": total,
        "brand_violations": brand_issues,
        "unverified_claims": claim_issues,
        "human_escalations_required": human_escalations,
        "is_publication_ready": (brand_issues == 0 and claim_issues == 0 and human_escalations == 0),
    }
