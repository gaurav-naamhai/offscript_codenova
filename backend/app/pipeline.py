"""Pipeline coordinator executing compliance review plugins concurrently with live progress and error flags."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import inspect
import logging
import re
from typing import Callable, List, Optional, Tuple
import uuid

from app.config import Settings
from app.models import ContentPayload, DegradedModule, Flag, FlagDraft, FlaggedSpan, GuidelineRef
from app.plugins import brand_check, retrieval, verification
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)


def ground_visual_finding(draft: FlagDraft, guidelines: List[GuidelineRef]) -> FlagDraft:
    """Keep general visual advice separate from evidence-backed brand rules."""
    text = ' '.join([draft.passage, draft.location, draft.explanation]).lower()
    topics = [topic for topic, pattern in (
        ('logo', r'logo|wordmark|clearspace'),
        ('typography', r'typograph|font|text size|readab'),
        ('contrast', r'contrast|accessibility'),
    ) if re.search(pattern, text)]
    if draft.finding_type != 'brand' or not topics:
        return draft
    patterns = {'logo': r'logo|wordmark|clearspace', 'typography': r'typograph|font|text size|readab', 'contrast': r'contrast|accessibility'}
    cited = draft.guideline_refs or ([draft.guideline_ref] if draft.guideline_ref else [])
    relevant = [g for g in cited if g in guidelines and all(re.search(patterns[t], g.excerpt.lower()) for t in topics)]
    if relevant:
        draft.guideline_ref, draft.guideline_refs = relevant[0], relevant
        return draft
    draft.state = 'unclear'
    draft.guideline_ref, draft.guideline_refs, draft.internal_evidence = None, [], []
    draft.explanation = 'General visual/accessibility observation — not an established brand-rule violation. ' + draft.explanation
    draft.uncertainty_note = 'No matching rule was found in the supplied guidance. Visual estimates require human review.'
    draft.suggested_correction = None
    draft.suggestion = None
    return draft


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
        evidence_mode=draft.evidence_mode,
        internal_evidence=draft.internal_evidence,
        external_evidence=draft.external_evidence,
        exact_violated_passage=draft.exact_violated_passage,
        flagged_span=draft.flagged_span,
        suggestion=draft.suggestion,
    )


def _make_error_flag(
    module: str,
    submission_id: str,
    version: int,
    now_iso: str,
    detail: Optional[str] = None,
) -> Flag:
    finding_type = "claim" if module == "verification" else "brand"
    state = "insufficient_evidence" if module == "verification" else "unclear"
    suffix = f" ({detail})" if detail else ""
    return Flag(
        id=str(uuid.uuid4()), submission_id=submission_id, version=version,
        finding_type=finding_type, state=state, passage="(whole submission)", location="submission",
        explanation=f"Automated check failed ({module}){suffix}. Retry or review manually before publication.",
        why_it_matters="System failure during compliance check requires human intervention or retry.",
        guideline_ref=None, guideline_refs=[], external_sources=[], uncertainty_note=detail,
        suggested_correction=None, origin="error", status="open", comments=[],
        needs_human=True, created_at=now_iso,
        evidence_mode="insufficient_evidence",
        internal_evidence=[],
        external_evidence=[],
        flagged_span=FlaggedSpan(
            exact_text="(whole submission)",
            surrounding_passage="(whole submission)",
            location_label="submission",
        ),
    )


def _call_verification(v_fn: Callable, content: ContentPayload, guidelines: List[GuidelineRef], cu: object):
    try:
        sig = inspect.signature(v_fn)
        if "guidelines" in sig.parameters:
            return v_fn(content, guidelines=guidelines, content_understanding=cu)
    except (ValueError, TypeError):
        pass
    return v_fn(content)


def _call_brand_check(b_fn: Callable, content: ContentPayload, guidelines: List[GuidelineRef], cu: object):
    try:
        sig = inspect.signature(b_fn)
        if "content_understanding" in sig.parameters:
            return b_fn(content, guidelines, content_understanding=cu)
    except (ValueError, TypeError):
        pass
    return b_fn(content, guidelines)


def run_pipeline(
    content: ContentPayload,
    submission_id: str,
    version: int = 1,
    retrieval_fn: Optional[Callable] = None,
    verification_fn: Optional[Callable] = None,
    brand_check_fn: Optional[Callable] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Flag], List[DegradedModule]]:
    """Execute compliance review pipeline: extract -> retrieve -> understand -> parallel(verify, brand_check) -> synthesize."""
    flags: List[Flag] = []
    degraded_modules: List[DegradedModule] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    def _notify(stage: str) -> None:
        if progress_cb:
            try:
                progress_cb(stage)
            except Exception:
                pass

    r_fn = retrieval_fn or retrieval.retrieve_guidelines
    v_fn = verification_fn or verification.verify_claims
    b_fn = brand_check_fn or brand_check.check_brand

    # 0. Pre-extract text once for PDF / Image so RAG, verification, and brand check share it
    _notify("extracting")
    if content.content_type in ("pdf", "image") and content.file_bytes and not getattr(content, "extracted_text", None):
        try:
            from retrieval.extractor import extract_from_payload
            from retrieval.schemas import ContentPayload as RetrievalPayload

            r_payload = RetrievalPayload(
                content_type=content.content_type,
                text=content.text,
                file_name=content.file_name,
                file_mime=content.file_mime,
                file_bytes=content.file_bytes,
            )
            extracted = extract_from_payload(r_payload)
            if extracted:
                content.extracted_text = extracted
        except Exception as exc:
            logger.warning("Pre-extraction failed (%s): %s", content.content_type, exc)

    # 1. Retrieval (org-isolated Brand RAG)
    _notify("retrieving_guidelines")
    guidelines: List[GuidelineRef] = []
    retrieval_failed = False
    try:
        raw_guidelines = r_fn(content)
        if not isinstance(raw_guidelines, list) or not all(isinstance(i, GuidelineRef) for i in raw_guidelines):
            raise TypeError("retrieve_guidelines must return list[GuidelineRef]")
        guidelines = raw_guidelines
    except Exception as exc:
        retrieval_failed = True
        logger.error("Plugin 'retrieval' failed: %s", exc, exc_info=True)
        degraded_modules.append(DegradedModule(module="retrieval", error=type(exc).__name__))
        flags.append(_make_error_flag("retrieval", submission_id, version, now_iso, detail=str(exc)))

    # 2. Shared Content Understanding (runs once for both Verification & Brand Check when AI is active)
    _notify("understanding_content")
    shared_cu = None
    settings = Settings()
    if (
        (verification_fn is None or brand_check_fn is None)
        and (settings.mock_ai or bool(settings.gemini_api_key))
        and ((content.text and content.text.strip()) or (content.file_bytes and len(content.file_bytes) > 0))
    ):
        try:
            from app.ai.content_understanding import understand_content

            shared_cu = understand_content(content)
        except Exception as exc:
            logger.warning("Shared ContentUnderstanding step degraded: %s", exc)
            shared_cu = None

    # 3. Execute Verification & Brand Check concurrently
    _notify("verifying_and_assessing")
    candidate_drafts: List[FlagDraft] = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        v_fut = pool.submit(_call_verification, v_fn, content, guidelines, shared_cu)
        # An unavailable retrieval service is not an empty brand workspace.
        b_fut = None if retrieval_failed else pool.submit(_call_brand_check, b_fn, content, guidelines, shared_cu)

        try:
            raw_claims = v_fut.result()
            if not isinstance(raw_claims, list) or not all(isinstance(i, FlagDraft) for i in raw_claims):
                raise TypeError("verify_claims must return list[FlagDraft]")
            candidate_drafts.extend(raw_claims)
        except Exception as exc:
            logger.error("Plugin 'verification' failed: %s", exc, exc_info=True)
            degraded_modules.append(DegradedModule(module="verification", error=type(exc).__name__))
            flags.append(_make_error_flag("verification", submission_id, version, now_iso, detail=str(exc)))

        if b_fut is not None:
            try:
                raw_brands = b_fut.result()
                if not isinstance(raw_brands, list) or not all(isinstance(i, FlagDraft) for i in raw_brands):
                    raise TypeError("check_brand must return list[FlagDraft]")
                candidate_drafts.extend(ground_visual_finding(draft, guidelines) for draft in raw_brands)
            except Exception as exc:
                logger.error("Plugin 'brand_check' failed: %s", exc, exc_info=True)
                degraded_modules.append(DegradedModule(module="brand_check", error=type(exc).__name__))
                flags.append(_make_error_flag("brand_check", submission_id, version, now_iso, detail=str(exc)))

    # 4. AI Flagging Synthesis & Deduplication
    _notify("synthesizing")
    from app.ai.flagging import deduplicate_and_synthesize_flag_drafts

    synthesized_drafts = deduplicate_and_synthesize_flag_drafts(
        candidate_drafts, include_aligned=True
    )
    flags.extend(_draft_to_flag(d, submission_id, version, now_iso) for d in synthesized_drafts)

    _notify("completed")
    return flags, degraded_modules
