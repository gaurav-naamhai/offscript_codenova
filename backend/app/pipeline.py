"""Pipeline coordinator for executing compliance review plugins with resilient fallbacks."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from app.models import (
    ContentPayload,
    DegradedModule,
    ExternalSource,
    Flag,
    FlagDraft,
    GuidelineRef,
)
from app.plugins import brand_check, retrieval, verification
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)


def _fixture_retrieval(content: ContentPayload) -> List[GuidelineRef]:
    return [
        GuidelineRef(
            document="Brand Tone and Claim Guidelines v2.1",
            passage_ref="Section 3.2",
            excerpt="All factual and statistical claims must be substantiated with verifiable sources.",
            source_reference="Compliance Manual Rev 2026",
        ),
        GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.1",
            excerpt="Brand terminology must adhere to our approved naming taxonomy.",
            source_reference="Design Standards Sec 1",
        ),
    ]


def _fixture_verification(content: ContentPayload) -> List[FlagDraft]:
    return [
        FlagDraft(
            finding_type="claim",
            state="supported",
            passage="Industry-leading 99.9% uptime SLA.",
            location="paragraph 1",
            explanation="Claim matches verified benchmark and SLA reports.",
            why_it_matters="Ensures commercial claims reflect real capabilities.",
            guideline_ref=None,
            external_sources=[
                ExternalSource(
                    url="https://status.example.com",
                    excerpt="Historical SLA benchmark records 99.95% uptime.",
                )
            ],
            uncertainty_note=None,
            suggested_correction=None,
            origin="fixture",
            status="open",
            comments=[],
        )
    ]


def _fixture_brand_check(
    content: ContentPayload, guidelines: List[GuidelineRef]
) -> List[FlagDraft]:
    ref = guidelines[0] if guidelines else None
    return [
        FlagDraft(
            finding_type="brand",
            state="aligned",
            passage="Empowering modern teams with confidence.",
            location="headline",
            explanation="Aligned with core brand voice principles.",
            why_it_matters="Maintains consistent brand voice across channels.",
            guideline_ref=ref,
            external_sources=[],
            uncertainty_note=None,
            suggested_correction=None,
            origin="fixture",
            status="open",
            comments=[],
        )
    ]


def run_pipeline(
    content: ContentPayload,
    submission_id: str,
    version: int = 1,
    retrieval_fn: Optional[Callable] = None,
    verification_fn: Optional[Callable] = None,
    brand_check_fn: Optional[Callable] = None,
) -> Tuple[List[Flag], List[DegradedModule]]:
    """Execute pipeline in order: retrieval -> verification -> brand_check.

    Each module is wrapped with try/except and type validation. On failure,
    logs full error server-side, records degraded module with exception type only,
    and falls back to fixture data.
    """
    degraded_modules: List[DegradedModule] = []
    r_fn = retrieval_fn or retrieval.retrieve_guidelines
    v_fn = verification_fn or verification.verify_claims
    b_fn = brand_check_fn or brand_check.check_brand

    # 1. Retrieval
    guidelines: List[GuidelineRef] = []
    try:
        raw_guidelines = r_fn(content)
        if not isinstance(raw_guidelines, list) or not all(
            isinstance(item, GuidelineRef) for item in raw_guidelines
        ):
            raise TypeError("retrieve_guidelines must return list[GuidelineRef]")
        guidelines = raw_guidelines
    except Exception as exc:
        err_type = type(exc).__name__
        logger.error("Plugin 'retrieval' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="retrieval", error=err_type))
        guidelines = _fixture_retrieval(content)

    # 2. Verification
    claim_drafts: List[FlagDraft] = []
    try:
        raw_claims = v_fn(content)
        if not isinstance(raw_claims, list) or not all(
            isinstance(item, FlagDraft) for item in raw_claims
        ):
            raise TypeError("verify_claims must return list[FlagDraft]")
        claim_drafts = raw_claims
    except Exception as exc:
        err_type = type(exc).__name__
        logger.error("Plugin 'verification' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="verification", error=err_type))
        claim_drafts = _fixture_verification(content)

    # 3. Brand Check
    brand_drafts: List[FlagDraft] = []
    try:
        raw_brands = b_fn(content, guidelines)
        if not isinstance(raw_brands, list) or not all(
            isinstance(item, FlagDraft) for item in raw_brands
        ):
            raise TypeError("check_brand must return list[FlagDraft]")
        brand_drafts = raw_brands
    except Exception as exc:
        err_type = type(exc).__name__
        logger.error("Plugin 'brand_check' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="brand_check", error=err_type))
        brand_drafts = _fixture_brand_check(content, guidelines)

    # Combine and convert drafts to Flags
    all_drafts = claim_drafts + brand_drafts
    flags: List[Flag] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for draft in all_drafts:
        flag = Flag(
            id=str(uuid.uuid4()),
            submission_id=submission_id,
            version=version,
            finding_type=draft.finding_type,
            state=draft.state,
            passage=draft.passage,
            location=draft.location,
            explanation=draft.explanation,
            why_it_matters=draft.why_it_matters,
            guideline_ref=draft.guideline_ref,
            external_sources=draft.external_sources,
            uncertainty_note=draft.uncertainty_note,
            suggested_correction=draft.suggested_correction,
            origin=draft.origin,
            status=draft.status,
            comments=list(draft.comments),
            needs_human=needs_human(draft.state),
            created_at=now_iso,
        )
        flags.append(flag)

    return flags, degraded_modules
