"""Pipeline coordinator executing compliance review plugins with explicit error flags."""

from datetime import datetime, timezone
import logging
from typing import Callable, List, Optional, Tuple
import uuid

from app.models import ContentPayload, DegradedModule, Flag, FlagDraft, GuidelineRef
from app.plugins import brand_check, retrieval, verification
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)


def _draft_to_flag(draft: FlagDraft, submission_id: str, version: int, now_iso: str) -> Flag:
    return Flag(
        id=str(uuid.uuid4()), submission_id=submission_id, version=version,
        finding_type=draft.finding_type, state=draft.state, passage=draft.passage,
        location=draft.location, explanation=draft.explanation, why_it_matters=draft.why_it_matters,
        guideline_ref=draft.guideline_ref,
        guideline_refs=draft.guideline_refs or ([draft.guideline_ref] if draft.guideline_ref else []),
        external_sources=draft.external_sources, uncertainty_note=draft.uncertainty_note,
        suggested_correction=draft.suggested_correction, origin=draft.origin,
        status=draft.status, comments=list(draft.comments),
        needs_human=needs_human(draft.state), created_at=now_iso,
    )


def _make_error_flag(module: str, submission_id: str, version: int, now_iso: str) -> Flag:
    finding_type = "claim" if module == "verification" else "brand"
    state = "insufficient_evidence" if module == "verification" else "unclear"
    return Flag(
        id=str(uuid.uuid4()), submission_id=submission_id, version=version,
        finding_type=finding_type, state=state, passage="(whole submission)", location="submission",
        explanation=f"Automated check failed ({module}). A human must review this submission.",
        why_it_matters="System failure during compliance check requires human intervention.",
        guideline_ref=None, guideline_refs=[], external_sources=[], uncertainty_note=None,
        suggested_correction=None, origin="error", status="open", comments=[],
        needs_human=True, created_at=now_iso,
    )


def run_pipeline(
    content: ContentPayload,
    submission_id: str,
    version: int = 1,
    retrieval_fn: Optional[Callable] = None,
    verification_fn: Optional[Callable] = None,
    brand_check_fn: Optional[Callable] = None,
) -> Tuple[List[Flag], List[DegradedModule]]:
    """Execute plugins in order: retrieval -> verification -> brand_check."""
    flags: List[Flag] = []
    degraded_modules: List[DegradedModule] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    r_fn = retrieval_fn or retrieval.retrieve_guidelines
    v_fn = verification_fn or verification.verify_claims
    b_fn = brand_check_fn or brand_check.check_brand

    # 1. Retrieval
    guidelines: List[GuidelineRef] = []
    try:
        raw_guidelines = r_fn(content)
        if not isinstance(raw_guidelines, list) or not all(isinstance(i, GuidelineRef) for i in raw_guidelines):
            raise TypeError("retrieve_guidelines must return list[GuidelineRef]")
        guidelines = raw_guidelines
    except Exception as exc:
        logger.error("Plugin 'retrieval' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="retrieval", error=type(exc).__name__))
        flags.append(_make_error_flag("retrieval", submission_id, version, now_iso))

    # 2. Verification
    try:
        raw_claims = v_fn(content)
        if not isinstance(raw_claims, list) or not all(isinstance(i, FlagDraft) for i in raw_claims):
            raise TypeError("verify_claims must return list[FlagDraft]")
        flags.extend(_draft_to_flag(d, submission_id, version, now_iso) for d in raw_claims)
    except Exception as exc:
        logger.error("Plugin 'verification' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="verification", error=type(exc).__name__))
        flags.append(_make_error_flag("verification", submission_id, version, now_iso))

    # 3. Brand Check
    try:
        raw_brands = b_fn(content, guidelines)
        if not isinstance(raw_brands, list) or not all(isinstance(i, FlagDraft) for i in raw_brands):
            raise TypeError("check_brand must return list[FlagDraft]")
        flags.extend(_draft_to_flag(d, submission_id, version, now_iso) for d in raw_brands)
    except Exception as exc:
        logger.error("Plugin 'brand_check' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="brand_check", error=type(exc).__name__))
        flags.append(_make_error_flag("brand_check", submission_id, version, now_iso))

    return flags, degraded_modules
