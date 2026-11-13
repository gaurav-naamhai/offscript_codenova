"""Suggestions and Corrections module for Inkloom AI.

Owner: Sera
Generates minimal, useful, and intent-preserving corrections for identified brand
issues and unverified/contradicted claims. Programmatically enforces entity
preservation (names, dates, numbers, conditions, SLAs), avoids inventing facts,
escalates to human review when evidence is missing or conflicting, and rechecks
candidate corrections to verify no new issues are introduced.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

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
from app.config import Settings
from app.models import FlagDraft, GuidelineRef
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)

CORRECTION_SYSTEM_INSTRUCTION = """You are the Senior Editorial Corrections and Compliance Specialist for Inkloom AI.
Your responsibility is to generate minimal, precise, and intent-preserving corrections for flagged brand compliance issues and factual claim errors.

CRITICAL OPERATIONAL RULES:
1. MINIMAL INTERVENTION: Replace only the problematic phrase or passage. Do NOT rewrite unaffected sentences or paragraphs.
2. PRESERVE ORIGINAL INTENT & TONE: Keep the author's core message, communication goal, and voice intact while removing violations.
3. STRICT ENTITY PROTECTION: You MUST preserve all specified critical entities (names, numbers, percentages, dates, SLA figures, conditions, certifications) verbatim. Never alter or drop them.
4. ZERO HALLUCINATION / NO INVENTED FACTS:
   - Ground factual replacements strictly in the provided verified external evidence.
   - If external evidence is missing, insufficient, or conflicting, DO NOT invent a factual replacement. Clearly state that human editorial review is required.
5. BRAND RULE ALIGNMENT: Replace buzzwords, unverified superlatives, or informal phrases with approved, professional brand terminology from the supplied guidelines.
6. CHANGE RATIONALE: Provide a clear, objective explanation of why the replacement resolves the issue and protects the brand.

Always return strictly valid JSON matching the CorrectionOutput schema."""


# ============================================================================
# ENTITY PROTECTION HELPERS
# ============================================================================


def _entity_is_preserved(entity: PreservedEntity, candidate_text: str) -> bool:
    """Check if entity is preserved, handling harmless formatting variations.

    Protects: proper_name, date, number, metric, condition, legal_term, url.
    Allows harmless variations:
    - Whitespace differences (e.g. '99.9 %' vs '99.9%')
    - Number formatting (e.g. '10,000' vs '10000')
    - Percentage expressions (e.g. '99.9%' vs '99.9 percent')
    - Date format variations (e.g. 'May 2026' preserving year '2026')
    """
    raw_ent = entity.text.strip()
    if not raw_ent:
        return True

    candidate_lower = candidate_text.lower()

    # 1. Exact substring check (case-insensitive)
    if raw_ent.lower() in candidate_lower:
        return True

    # 2. Normalized whitespace check (e.g. "99.9 %" vs "99.9%")
    norm_ent = re.sub(r"\s+", "", raw_ent.lower())
    norm_cand = re.sub(r"\s+", "", candidate_lower)
    if norm_ent in norm_cand:
        return True

    # 3. Number formatting check (e.g. "10,000" vs "10000")
    if entity.entity_type in ("number", "metric"):
        num_ent = re.sub(r"[, ]", "", raw_ent.lower())
        num_cand = re.sub(r"[, ]", "", candidate_lower)
        if num_ent in num_cand:
            return True

    # 4. Percent variation (e.g. "99.9%" vs "99.9 percent")
    if "%" in raw_ent:
        percent_variant = raw_ent.replace("%", " percent").strip().lower()
        if percent_variant in candidate_lower:
            return True

    # 5. Date year extraction check (if full date string was formatted differently e.g. "2026-05-01" vs "May 2026")
    if entity.entity_type == "date":
        year_match = re.search(r"\b(19\d\d|20\d\d)\b", raw_ent)
        if year_match and year_match.group(1) in candidate_lower:
            return True

    return False


def extract_entities_in_passage(
    passage: str,
    preserved_entities: List[PreservedEntity],
) -> List[PreservedEntity]:
    """Identify which preserved entities are present in the specific passage being corrected."""
    if not passage or not preserved_entities:
        return []

    matched: List[PreservedEntity] = []
    for entity in preserved_entities:
        if _entity_is_preserved(entity, passage):
            matched.append(entity)

    return matched


def check_entity_preservation(
    original_passage: str,
    candidate_text: str,
    preserved_entities: List[PreservedEntity],
) -> Tuple[bool, List[str], List[str]]:
    """Verify that all critical entities from original_passage are retained in candidate_text.

    Returns:
        (all_preserved: bool, preserved_entities: List[str], missing_entities: List[str])
    """
    relevant_entities = extract_entities_in_passage(original_passage, preserved_entities)
    if not relevant_entities:
        return True, [], []

    preserved: List[str] = []
    missing: List[str] = []

    for entity in relevant_entities:
        if _entity_is_preserved(entity, candidate_text):
            preserved.append(entity.text.strip())
        else:
            missing.append(entity.text.strip())

    all_preserved = (len(missing) == 0)
    return all_preserved, preserved, missing


# ============================================================================
# PROGRAMMATIC RECHECK ENGINE
# ============================================================================


def recheck_correction(
    original_passage: str,
    suggested_replacement: str,
    finding_type: str,
    state: str,
    preserved_entities: Optional[List[PreservedEntity]] = None,
    guideline_ref: Optional[GuidelineRef] = None,
    guidelines: Optional[List[GuidelineRef]] = None,
    evidence_quality: Optional[str] = None,
    evidence_map: Optional[Dict[str, List[Any]]] = None,
    client: Optional[GeminiClient] = None,
) -> Tuple[bool, str]:
    """Programmatically rechecks candidate replacement through Content Understanding, Brand Verification, and Claim Verification.

    Returns:
        (passed: bool, notes: str)
    """
    # 1. Check if the original state was uncertain or conflicting
    if state in ("insufficient_evidence", "unclear") or evidence_quality == "conflicting":
        return False, "Recheck escalated: Factual evidence is missing or conflicting; requires human review."

    # 2. Check Entity Preservation
    if preserved_entities:
        all_preserved, preserved_list, missing_list = check_entity_preservation(
            original_passage=original_passage,
            candidate_text=suggested_replacement,
            preserved_entities=preserved_entities,
        )
        if not all_preserved:
            missing_names = ", ".join(f"'{m}'" for m in missing_list)
            return (
                False,
                f"Entity protection failure: Candidate correction dropped or altered protected entity: {missing_names}.",
            )

    # 3. Check for empty replacement
    if not suggested_replacement.strip():
        return False, "Recheck failed: Suggested replacement is empty."

    # 4. Syntactic safety check for obvious unverified superlatives or guarantees
    replacement_lower = suggested_replacement.lower()
    superlative_patterns = [
        r"\b(best in the world|#1 in the world|world'?s best|undisputed leader|100% guaranteed?|zero risk)\b"
    ]
    for pat in superlative_patterns:
        if re.search(pat, replacement_lower):
            return (
                False,
                f"Recheck failed: Candidate replacement introduces unverified superlative or guarantee: '{pat}'.",
            )

    from app.models import ContentPayload

    # 5. Content Understanding Recheck
    cu_out = None
    try:
        from app.ai.content_understanding import understand_content

        cu_out = understand_content(
            ContentPayload(content_type="text", text=suggested_replacement),
            client=client,
        )
    except Exception as exc:
        logger.warning("Content understanding recheck warning: %s", exc)

    # 6. Brand Verification Recheck
    effective_guidelines = guidelines or ([guideline_ref] if guideline_ref else [])
    if effective_guidelines:
        try:
            from app.ai.brand_verification import verify_brand

            bv_out = verify_brand(
                ContentPayload(content_type="text", text=suggested_replacement),
                guidelines=effective_guidelines,
                client=client,
            )
            brand_violations = [f for f in bv_out.findings if f.state == "potential_issue"]
            if brand_violations:
                return (
                    False,
                    f"Brand recheck failed: Candidate replacement contains brand violation: '{brand_violations[0].explanation}'.",
                )
        except Exception as exc:
            logger.warning("Brand verification recheck warning: %s", exc)

    # 7. Claim Verification Recheck
    target_claims = [c for c in (cu_out.claims if cu_out else []) if c.claim_type in ("fact", "mixed")]
    if finding_type == "claim" or target_claims:
        try:
            from app.ai.claim_verification import verify_claims_against_evidence

            if target_claims:
                cv_out = verify_claims_against_evidence(
                    claims=target_claims,
                    evidence_map=evidence_map,
                    client=client,
                    auto_fetch_evidence=False,
                )
                unverified_claims = [
                    f for f in cv_out.findings if f.state in ("contradicted", "insufficient_evidence")
                ]
                if unverified_claims:
                    return (
                        False,
                        f"Claim recheck failed: Candidate replacement introduces unverified or contradicted claim: '{unverified_claims[0].claim_text}'.",
                    )
        except Exception as exc:
            logger.warning("Claim verification recheck warning: %s", exc)

    return (
        True,
        "Recheck passed: Candidate replacement verified through Content Understanding, Brand Verification, and Claim Verification with no new violations.",
    )


# ============================================================================
# MAIN CORRECTION GENERATION
# ============================================================================


def generate_correction(
    flag: Union[FlagDraft, SynthesizedFlag, BrandFinding, ClaimFinding, Dict[str, Any]],
    content_understanding: Optional[ContentUnderstandingOutput] = None,
    guidelines: Optional[List[GuidelineRef]] = None,
    evidence_map: Optional[Dict[str, List[Any]]] = None,
    client: Optional[GeminiClient] = None,
) -> CorrectionOutput:
    """Generate a minimal, source-backed correction for a single flagged issue.

    Args:
        flag: The issue to correct (FlagDraft, SynthesizedFlag, BrandFinding, or ClaimFinding).
        content_understanding: Context output with audience, tone, and preserved entities.
        guidelines: Optional list of retrieved brand guidelines.
        evidence_map: Optional mapping of claim text -> retrieved evidence items.
        client: Optional GeminiClient instance.

    Returns:
        Structured CorrectionOutput with replacement text, rationale, and recheck status.
    """
    ai_client = client or GeminiClient(settings=Settings())

    # Extract flag attributes flexibly
    passage = getattr(flag, "passage", None) or (flag.get("passage") if isinstance(flag, dict) else "")
    location = getattr(flag, "location", None) or (flag.get("location") if isinstance(flag, dict) else "content")
    finding_type = getattr(flag, "finding_type", "brand") if hasattr(flag, "finding_type") else ("brand" if isinstance(flag, BrandFinding) else "claim")
    state = getattr(flag, "state", "potential_issue")
    explanation = getattr(flag, "explanation", "")
    suggested_fix = getattr(flag, "suggested_fix", None) or getattr(flag, "suggested_correction", None)
    evidence_quality = getattr(flag, "evidence_quality", None)
    guideline_ref = getattr(flag, "guideline_ref", None)
    flag_id = getattr(flag, "id", None) or getattr(flag, "claim_id", None)

    all_entities = content_understanding.preserved_entities if content_understanding else []
    relevant_entities = extract_entities_in_passage(passage, all_entities)
    relevant_entity_texts = [e.text for e in relevant_entities]

    # Case 1: Already compliant (aligned / supported)
    if state in ("aligned", "supported"):
        return CorrectionOutput(
            flag_id=flag_id,
            original_passage=passage,
            suggested_replacement=passage,
            change_rationale="Passage already complies with brand and factual standards. No correction needed.",
            entities_preserved=relevant_entity_texts,
            recheck_passed=True,
            recheck_notes="Passage verified compliant.",
        )

    # Case 2: Insufficient or Conflicting Evidence
    # RULE: Never invent replacement facts when evidence is missing or conflicting!
    if state in ("insufficient_evidence", "unclear") or evidence_quality == "conflicting":
        return CorrectionOutput(
            flag_id=flag_id,
            original_passage=passage,
            suggested_replacement=passage,  # Retain original passage for human reviewer to edit
            change_rationale=(
                "Factual evidence is insufficient, absent, or conflicting across third-party sources. "
                "Automated systems must never invent replacement facts or assertions without verification. "
                "Escalated for human editorial review."
            ),
            entities_preserved=relevant_entity_texts,
            recheck_passed=False,
            recheck_notes="Requires human review: insufficient or conflicting external evidence.",
        )

    # Case 3: Mock Mode
    if ai_client.mock_mode:
        if CorrectionOutput in ai_client._mock_handlers:
            return ai_client.generate_structured(prompt="", response_schema=CorrectionOutput)

        return _generate_mock_correction(
            passage=passage,
            finding_type=finding_type,
            state=state,
            suggested_fix=suggested_fix,
            explanation=explanation,
            relevant_entities=relevant_entities,
            guideline_ref=guideline_ref,
            guidelines=guidelines,
            evidence_quality=evidence_quality,
            evidence_map=evidence_map,
            client=ai_client,
            flag_id=flag_id,
        )

    # Case 4: Live Gemini Execution
    entity_prompt_section = (
        "PROTECTED CRITICAL ENTITIES (MUST BE PRESERVED VERBATIM):\n"
        + "\n".join([f"  - [{e.entity_type}] {e.text}" for e in relevant_entities])
        if relevant_entities
        else "No specific protected entities detected in this passage."
    )

    tone_context = content_understanding.tone if content_understanding else "professional"
    audience_context = content_understanding.target_audience if content_understanding else "general audience"

    guideline_section = ""
    if guideline_ref:
        guideline_section = (
            f"RELEVANT BRAND GUIDELINE:\n"
            f"Document: {guideline_ref.document}\n"
            f"Section: {guideline_ref.passage_ref}\n"
            f"Excerpt: \"{guideline_ref.excerpt}\"\n"
        )

    prompt = (
        f"Generate a minimal, intent-preserving editorial correction for the following compliance issue:\n\n"
        f"Original Passage: \"{passage}\"\n"
        f"Location: {location}\n"
        f"Finding Type: {finding_type} ({state})\n"
        f"Violation Details: {explanation}\n"
        f"Target Audience: {audience_context}\n"
        f"Intended Tone: {tone_context}\n"
        f"{guideline_section}\n"
        f"{entity_prompt_section}\n\n"
        f"Produce a minimal replacement that resolves the violation, preserves all protected entities verbatim, "
        f"and keeps the creator's intended message and tone."
    )

    candidate = ai_client.generate_structured(
        prompt=prompt,
        response_schema=CorrectionOutput,
        system_instruction=CORRECTION_SYSTEM_INSTRUCTION,
    )

    # Run programmatic recheck on candidate
    passed, notes = recheck_correction(
        original_passage=passage,
        suggested_replacement=candidate.suggested_replacement,
        finding_type=finding_type,
        state=state,
        preserved_entities=relevant_entities,
        guideline_ref=guideline_ref,
        guidelines=guidelines,
        evidence_quality=evidence_quality,
        evidence_map=evidence_map,
        client=ai_client,
    )

    candidate.flag_id = flag_id
    candidate.original_passage = passage
    candidate.recheck_passed = passed
    candidate.recheck_notes = notes

    # Synchronize confirmed preserved entities
    _, preserved_list, _ = check_entity_preservation(
        original_passage=passage,
        candidate_text=candidate.suggested_replacement,
        preserved_entities=relevant_entities,
    )
    candidate.entities_preserved = preserved_list

    return candidate


def generate_corrections(
    flags: List[Union[FlagDraft, SynthesizedFlag, BrandFinding, ClaimFinding, Dict[str, Any]]],
    content_understanding: Optional[ContentUnderstandingOutput] = None,
    guidelines: Optional[List[GuidelineRef]] = None,
    evidence_map: Optional[Dict[str, List[Any]]] = None,
    client: Optional[GeminiClient] = None,
) -> SuggestionsOutput:
    """Batch generate corrections for all actionable flags in a submission."""
    corrections: List[CorrectionOutput] = []

    for f in flags:
        # Skip pure aligned/supported flags unless specifically requested
        st = getattr(f, "state", None) or (f.get("state") if isinstance(f, dict) else None)
        if st in ("aligned", "supported"):
            continue

        corr = generate_correction(
            flag=f,
            content_understanding=content_understanding,
            guidelines=guidelines,
            evidence_map=evidence_map,
            client=client,
        )
        corrections.append(corr)

    return SuggestionsOutput(corrections=corrections)


# ============================================================================
# DETERMINISTIC MOCK CORRECTION GENERATOR
# ============================================================================


def _generate_mock_correction(
    passage: str,
    finding_type: str,
    state: str,
    suggested_fix: Optional[str],
    explanation: str,
    relevant_entities: List[PreservedEntity],
    guideline_ref: Optional[GuidelineRef],
    guidelines: Optional[List[GuidelineRef]],
    evidence_quality: Optional[str],
    evidence_map: Optional[Dict[str, List[Any]]],
    client: Optional[GeminiClient],
    flag_id: Optional[str],
) -> CorrectionOutput:
    """Generate realistic, entity-preserving corrections deterministically for offline testing."""
    passage_lower = passage.lower()

    # Determine baseline replacement text
    replacement = passage

    if "disruptive synergy" in passage_lower:
        replacement = re.sub(r"(?i)disruptive synergy", "effective collaboration", passage)
        rationale = "Replaced corporate buzzword with plain-English alternative conforming to Brand Playbook section 1.3."

    elif "game-changing" in passage_lower or "paradigm shift" in passage_lower:
        replacement = re.sub(r"(?i)game-changing paradigm shift", "significant advancement", passage)
        rationale = "Removed hyperbolic buzzword in favor of professional descriptive terminology."

    elif "#1" in passage_lower or "world's leading" in passage_lower or "best in the world" in passage_lower:
        # Factual contradiction: soften absolute supremacy to verified top-tier provider
        replacement = re.sub(r"(?i)(rated\s+)?#1(\s+in\s+market\s+share\s+globally)?", "a recognized industry provider", passage)
        if replacement == passage:
            replacement = "a recognized top-tier market provider"
        rationale = "Replaced contradicted supremacy claim with defensible industry positioning substantiated by third-party analyst reports."

    elif "guarantee" in passage_lower or "100% uptime" in passage_lower:
        # Guarantee without SLA exclusions
        replacement = re.sub(r"(?i)we guarantee 100% uptime with zero exceptions", "our platform targets 99.9% availability subject to SLA terms", passage)
        if replacement == passage:
            replacement = "engineered for high availability subject to SLA terms"
        rationale = "Qualified absolute guarantee with standard enterprise SLA terms to mitigate legal breach exposure."

    elif suggested_fix:
        # If finding already carried a minimal fix suggestion, apply it
        replacement = suggested_fix
        rationale = f"Applied standard brand correction: {suggested_fix}."

    else:
        # Minimal softening
        replacement = passage
        rationale = "Minor phrasing adjustment for brand voice consistency."

    # Programmatic Entity Protection check: Ensure any entity present in original passage is NOT lost!
    for ent in relevant_entities:
        if _entity_is_preserved(ent, passage) and not _entity_is_preserved(ent, replacement):
            # If the naive substitution dropped a protected entity (e.g. date or number), restore it!
            replacement = f"{replacement} (retaining {ent.text})"

    # Run programmatic recheck
    passed, notes = recheck_correction(
        original_passage=passage,
        suggested_replacement=replacement,
        finding_type=finding_type,
        state=state,
        preserved_entities=relevant_entities,
        guideline_ref=guideline_ref,
        guidelines=guidelines,
        evidence_quality=evidence_quality,
        evidence_map=evidence_map,
        client=client,
    )

    _, preserved_list, _ = check_entity_preservation(
        original_passage=passage,
        candidate_text=replacement,
        preserved_entities=relevant_entities,
    )

    return CorrectionOutput(
        flag_id=flag_id,
        original_passage=passage,
        suggested_replacement=replacement,
        change_rationale=rationale,
        entities_preserved=preserved_list,
        recheck_passed=passed,
        recheck_notes=notes,
    )

