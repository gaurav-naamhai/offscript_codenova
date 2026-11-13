"""Brand Verification module for Inkloom AI.

Owner: Sera
Evaluates submitted draft content against brand guidelines retrieved via
Ken's retrieval interface. Checks voice, tone, terminology, messaging,
and visual consistency. Reports uncertainty when guidelines are missing or ambiguous.
"""

import logging
import re
from typing import List, Optional

from app.ai.client import GeminiClient
from app.ai.schemas import (
    BrandFinding,
    BrandVerificationOutput,
    ContentUnderstandingOutput,
)
from app.config import Settings
from app.models import ContentPayload, FlagDraft, GuidelineRef

logger = logging.getLogger(__name__)

BRAND_SYSTEM_INSTRUCTION = """You are the Senior Brand Compliance and Voice Guardian for Inkloom AI.
Your role is to rigorously evaluate draft publications against authoritative, retrieved brand guidelines.

CRITICAL OPERATIONAL RULES:
1. STRICT GROUNDING: You must ONLY evaluate against the provided brand guidelines. NEVER invent unwritten corporate rules, subjective stylistic preferences, or fictional guidelines.
2. CITATION REQUIREMENT: Every finding MUST explicitly cite the exact guideline_document, guideline_section, and guideline_excerpt from the provided guidelines.
3. UNCERTAINTY HANDLING: If a guideline is ambiguous, incomplete, or if the submission is borderline, set state='unclear' and supply a clear uncertainty_note. Do not fabricate an authoritative violation when guidelines are unclear.
4. VIOLATION CLASSIFICATION: For violations (state='potential_issue'):
   - Specify violation_category ('tone', 'buzzword', 'superlative', 'terminology', 'visual', 'positioning', 'other').
   - Provide an objective, clear explanation of the conflict.
   - Explain 'why_it_matters' from a brand equity, risk, or clarity perspective.
   - Propose an intent-preserving, minimal replacement (suggested_fix).
5. ALIGNED FINDINGS: For compliant sections adhering to specific guidelines, include findings with state='aligned'.
6. MULTIMODAL VERIFICATION: For image or PDF assets, check visual brand consistency (logo placement, typography, color harmony, visual tone) against visual guidelines.

Always return valid JSON adhering strictly to the BrandVerificationOutput schema."""


def resolve_media_mime(content: ContentPayload) -> str:
    """Resolve and normalize MIME type from file_mime, file_name, or content_type."""
    if content.file_mime:
        raw_mime = content.file_mime.strip().lower()
        if raw_mime == "image/jpg":
            return "image/jpeg"
        return raw_mime
    if content.file_name:
        fn = content.file_name.lower()
        if fn.endswith(".png"):
            return "image/png"
        if fn.endswith(".jpg") or fn.endswith(".jpeg"):
            return "image/jpeg"
        if fn.endswith(".webp"):
            return "image/webp"
        if fn.endswith(".pdf"):
            return "application/pdf"
    if content.content_type == "image":
        return "image/png"
    if content.content_type == "pdf":
        return "application/pdf"
    return "application/octet-stream"


def validate_and_ground_findings(
    findings: List[BrandFinding],
    guidelines: List[GuidelineRef],
) -> List[BrandFinding]:
    """Audit and validate that every finding is grounded in the retrieved guidelines.

    If a finding cites a guideline document or excerpt that does not match
    any of the supplied guidelines, it is converted to state='unclear' with
    an uncertainty note requiring human review.
    """
    grounded_findings: List[BrandFinding] = []

    for f in findings:
        matched_g: Optional[GuidelineRef] = None

        doc_cited = (f.guideline_document or "").strip().lower()
        sec_cited = (f.guideline_section or "").strip().lower()
        exc_cited = (f.guideline_excerpt or "").strip().lower()

        # 1. First priority: Match BOTH document and section
        if sec_cited:
            for g in guidelines:
                g_doc = g.document.strip().lower()
                g_sec = g.passage_ref.strip().lower()
                if (doc_cited and (doc_cited in g_doc or g_doc in doc_cited)) and (
                    sec_cited in g_sec or g_sec in sec_cited
                ):
                    matched_g = g
                    break

        # 2. Second priority: Match by excerpt overlap
        if not matched_g and exc_cited and len(exc_cited) > 10:
            for g in guidelines:
                g_exc = g.excerpt.strip().lower()
                if exc_cited in g_exc or g_exc in exc_cited:
                    matched_g = g
                    break

        # 3. Third priority: Match by document name ONLY if section was unspecified
        if not matched_g and doc_cited and not sec_cited:
            for g in guidelines:
                g_doc = g.document.strip().lower()
                if doc_cited == g_doc or doc_cited in g_doc or g_doc in doc_cited:
                    matched_g = g
                    break

        if matched_g:
            # Synchronize with the authoritative guideline reference
            f.guideline_document = matched_g.document
            f.guideline_section = matched_g.passage_ref
            f.guideline_excerpt = matched_g.excerpt
            grounded_findings.append(f)
        else:
            # Finding cites an ungrounded or hallucinated guideline
            if f.state == "potential_issue":
                logger.warning(
                    "Ungrounded guideline citation detected: '%s' (%s). Converting to state='unclear'.",
                    f.guideline_document,
                    f.guideline_section,
                )
                f.state = "unclear"
                f.uncertainty_note = (
                    f"Unverified guideline citation: The cited guideline standard '{f.guideline_document}' "
                    f"was not found in retrieved brand guidelines. Escalated for human review."
                )
                f.guideline_document = "Unverified Reference"
                f.guideline_section = "N/A"
                f.guideline_excerpt = "Citation not present in retrieved guidelines."
            grounded_findings.append(f)

    return grounded_findings


def brand_finding_to_flag_draft(
    finding: BrandFinding,
    guideline: Optional[GuidelineRef] = None,
) -> FlagDraft:
    """Convert a BrandFinding directly to Gaurav's domain FlagDraft model.

    Ensures seamless compatibility with backend/app/pipeline.py and repository.
    """
    g_ref = None
    if guideline:
        g_ref = guideline
    elif (
        finding.guideline_document
        and finding.guideline_document not in ("N/A", "Unverified Reference")
    ):
        g_ref = GuidelineRef(
            document=finding.guideline_document,
            passage_ref=finding.guideline_section or "Rule",
            excerpt=finding.guideline_excerpt or "",
            source_reference=None,
        )

    return FlagDraft(
        finding_type="brand",
        state=finding.state,
        passage=finding.passage,
        location=finding.location,
        explanation=finding.explanation,
        why_it_matters=finding.why_it_matters,
        guideline_ref=g_ref,
        guideline_refs=[g_ref] if g_ref else [],
        external_sources=[],
        uncertainty_note=finding.uncertainty_note,
        suggested_correction=finding.suggested_fix,
        origin="module",
        status="open",
        comments=[],
    )


def verify_brand(
    content: ContentPayload,
    guidelines: List[GuidelineRef],
    content_understanding: Optional[ContentUnderstandingOutput] = None,
    client: Optional[GeminiClient] = None,
) -> BrandVerificationOutput:
    """Verify submitted content against retrieved brand guidelines.

    Args:
        content: Domain ContentPayload (text, image, or PDF).
        guidelines: Authoritative brand guidelines retrieved by Ken's module.
        content_understanding: Optional pre-computed context understanding.
        client: Optional GeminiClient instance.

    Returns:
        BrandVerificationOutput containing granular findings and overall alignment status.
    """
    ai_client = client or GeminiClient(settings=Settings())

    # Validate multimodal file bytes if image or PDF
    if content.content_type in ("image", "pdf") and not (content.file_bytes and len(content.file_bytes) > 0):
        if not (content.text and content.text.strip()):
            raise ValueError(f"{content.content_type.capitalize()} submission requires non-empty file_bytes.")

    # 1. Zero Guidelines Rule: Report uncertainty rather than hallucinating violations
    if not guidelines:
        sample_passage = (
            content.text[:80].strip()
            if content.text
            else f"{content.content_type.capitalize()} asset ({content.file_name or 'unnamed'})"
        )
        logger.warning("Brand verification invoked with zero retrieved guidelines. Reporting uncertainty.")
        return BrandVerificationOutput(
            overall_alignment="unclear",
            voice_and_tone_assessment="No governing brand guidelines were retrieved for this submission.",
            terminology_assessment="Unable to verify terminology against brand standards without retrieved guidelines.",
            visual_brand_assessment=(
                "Visual brand verification cannot proceed without visual identity guidelines."
                if content.content_type != "text"
                else None
            ),
            findings=[
                BrandFinding(
                    state="unclear",
                    passage=sample_passage,
                    location="submission",
                    violation_category="other",
                    explanation="No brand guidelines were provided by the retrieval interface. Brand verification cannot invent rules in the absence of authoritative guidelines.",
                    why_it_matters="Grounding checks in explicit guidelines prevents arbitrary enforcement and protects creator trust.",
                    guideline_document="N/A",
                    guideline_section="N/A",
                    guideline_excerpt="No guidelines supplied by retrieval layer.",
                    suggested_fix=None,
                    uncertainty_note="Missing guideline context. A human brand reviewer must inspect this submission manually.",
                )
            ],
        )

    # 2. Format Retrieved Guidelines for Context
    guidelines_formatted = "\n\n".join(
        [
            f"[{idx+1}] Document: {g.document}\n"
            f"    Section: {g.passage_ref}\n"
            f"    Rule Excerpt: \"{g.excerpt}\"\n"
            f"    Source: {g.source_reference or 'Brand Guidelines'}"
            for idx, g in enumerate(guidelines)
        ]
    )

    # Context understanding summary if available
    context_prefix = ""
    if content_understanding:
        context_prefix = (
            f"Content Context Summary:\n"
            f"- Audience: {content_understanding.target_audience}\n"
            f"- Purpose: {content_understanding.purpose}\n"
            f"- Observed Tone: {content_understanding.tone}\n\n"
        )

    # 3. Handle Mock Mode Deterministically
    if ai_client.mock_mode:
        if BrandVerificationOutput in ai_client._mock_handlers:
            output = ai_client.generate_structured(prompt="", response_schema=BrandVerificationOutput)
        else:
            output = _generate_mock_brand_verification(
                content=content,
                guidelines=guidelines,
                content_understanding=content_understanding,
            )
        output.findings = validate_and_ground_findings(output.findings, guidelines)
        output.overall_alignment = _compute_overall_alignment(output.findings)
        return output

    # 4. Live Gemini Execution
    mime_type = resolve_media_mime(content)

    if content.content_type == "text" or (content.text and not content.file_bytes):
        prompt = (
            f"{context_prefix}"
            f"Evaluate the following draft text submission against the authoritative brand guidelines below.\n\n"
            f"=== RETRIEVED BRAND GUIDELINES ===\n"
            f"{guidelines_formatted}\n\n"
            f"=== SUBMISSION DRAFT TEXT ===\n"
            f"{content.text}\n\n"
            f"Check brand voice, tone, terminology, and messaging consistency against every applicable guideline."
        )
        output = ai_client.generate_structured(
            prompt=prompt,
            response_schema=BrandVerificationOutput,
            system_instruction=BRAND_SYSTEM_INSTRUCTION,
        )
    elif content.content_type == "image":
        prompt = (
            f"{context_prefix}"
            f"Evaluate this visual brand asset against the authoritative brand guidelines below.\n\n"
            f"=== RETRIEVED BRAND GUIDELINES ===\n"
            f"{guidelines_formatted}\n\n"
            f"Assess visual identity, logo usage, color palette, typography, visual hierarchy, "
            f"and any visible text against the brand guidelines."
        )
        output = ai_client.generate_structured(
            prompt=prompt,
            response_schema=BrandVerificationOutput,
            system_instruction=BRAND_SYSTEM_INSTRUCTION,
            media_bytes=content.file_bytes,
            media_mime=mime_type,
        )
    elif content.content_type == "pdf":
        prompt = (
            f"{context_prefix}"
            f"Evaluate this multi-page PDF publication against the authoritative brand guidelines below.\n\n"
            f"=== RETRIEVED BRAND GUIDELINES ===\n"
            f"{guidelines_formatted}\n\n"
            f"Check document typography, layout consistency, voice, terminology, and messaging across pages."
        )
        output = ai_client.generate_structured(
            prompt=prompt,
            response_schema=BrandVerificationOutput,
            system_instruction=BRAND_SYSTEM_INSTRUCTION,
            media_bytes=content.file_bytes,
            media_mime=mime_type,
        )
    else:
        raise ValueError(f"Unsupported content_type: '{content.content_type}'")

    # Post-validation: ground findings against authoritative guidelines
    output.findings = validate_and_ground_findings(output.findings, guidelines)
    output.overall_alignment = _compute_overall_alignment(output.findings)
    return output


def _compute_overall_alignment(findings: List[BrandFinding]) -> str:
    """Compute overall status based on grounded findings."""
    if any(f.state == "potential_issue" for f in findings):
        return "potential_issue"
    if any(f.state == "unclear" for f in findings):
        return "unclear"
    return "aligned"


# ============================================================================
# DETERMINISTIC MOCK BRAND VERIFICATION GENERATOR
# ============================================================================


def _generate_mock_brand_verification(
    content: ContentPayload,
    guidelines: List[GuidelineRef],
    content_understanding: Optional[ContentUnderstandingOutput],
) -> BrandVerificationOutput:
    """Generate realistic, guideline-grounded mock brand verification for offline testing."""
    findings: List[BrandFinding] = []
    text = content.text or ""

    # Determine what guidelines are actually present to avoid false positives
    has_buzzword_rule = any(
        any(
            k in g.excerpt.lower() or k in g.document.lower()
            for k in ("buzzword", "jargon", "plain english", "plain-english", "language", "terminology")
        )
        for g in guidelines
    )
    has_punctuation_rule = any(
        any(
            k in g.excerpt.lower() or k in g.document.lower()
            for k in ("punctuation", "exclamation", "measured", "hyperbolic", "tone")
        )
        for g in guidelines
    )
    has_positioning_rule = any(
        any(
            k in g.excerpt.lower() or k in g.document.lower()
            for k in ("positioning", "cheap", "cost", "pricing", "value", "premium")
        )
        for g in guidelines
    )
    has_visual_rule = any(
        any(
            k in g.excerpt.lower() or k in g.document.lower()
            for k in ("visual", "logo", "color", "palette", "typography", "design", "layout")
        )
        for g in guidelines
    )

    # Helper to pick most relevant guideline by keyword
    def find_guideline(keywords: List[str]) -> GuidelineRef:
        for kw in keywords:
            for g in guidelines:
                if kw in g.excerpt.lower():
                    return g
            for g in guidelines:
                if kw in g.passage_ref.lower():
                    return g
            for g in guidelines:
                if kw in g.document.lower():
                    return g
        return guidelines[0]

    # Pattern 1: Buzzwords (only if guidelines address language/buzzwords)
    if has_buzzword_rule and text:
        buzzwords = re.finditer(r"\b(synergy|disruptive|game-changing)\b", text, re.IGNORECASE)
        for match in buzzwords:
            word = match.group(0)
            start, end = match.span()
            ref = find_guideline(["buzzword", "jargon", "plain english", "language"])
            findings.append(
                BrandFinding(
                    state="potential_issue",
                    passage=word,
                    location=f"characters {start}-{end}",
                    violation_category="buzzword",
                    explanation=f"The buzzword '{word}' contradicts our plain-English brand communication standards.",
                    why_it_matters="Clear terminology builds credibility and avoids sounding like superficial marketing jargon.",
                    guideline_document=ref.document,
                    guideline_section=ref.passage_ref,
                    guideline_excerpt=ref.excerpt,
                    suggested_fix="effective collaboration" if word.lower() == "synergy" else "innovative",
                )
            )

    # Pattern 2: Multiple exclamation marks (only if guidelines address tone/punctuation)
    if has_punctuation_rule and text:
        exclamations = re.finditer(r"!{2,}", text)
        for match in exclamations:
            start, end = match.span()
            ref = find_guideline(["punctuation", "exclamation", "measured", "tone"])
            findings.append(
                BrandFinding(
                    state="potential_issue",
                    passage=text[start:end],
                    location=f"characters {start}-{end}",
                    violation_category="tone",
                    explanation="Repeated exclamation marks violate measured and authoritative brand tone.",
                    why_it_matters="Enterprise brand credibility relies on confident, unexaggerated punctuation.",
                    guideline_document=ref.document,
                    guideline_section=ref.passage_ref,
                    guideline_excerpt=ref.excerpt,
                    suggested_fix=".",
                )
            )

    # Pattern 3: Cheap positioning (only if guidelines address positioning/cost)
    if has_positioning_rule and text:
        cheap_matches = re.finditer(r"\bcheap\b", text, re.IGNORECASE)
        for match in cheap_matches:
            start, end = match.span()
            ref = find_guideline(["positioning", "cheap", "cost", "pricing", "value"])
            findings.append(
                BrandFinding(
                    state="potential_issue",
                    passage=text[start:end],
                    location=f"characters {start}-{end}",
                    violation_category="positioning",
                    explanation="The term 'cheap' undermines our premium, value-driven brand positioning.",
                    why_it_matters="Positioning must focus on cost-effectiveness and high ROI rather than low price.",
                    guideline_document=ref.document,
                    guideline_section=ref.passage_ref,
                    guideline_excerpt=ref.excerpt,
                    suggested_fix="cost-effective",
                )
            )

    # Multimodal Visual Check (only if guidelines address visuals)
    visual_assessment = None
    if content.content_type in ("image", "pdf"):
        if has_visual_rule:
            ref_visual = find_guideline(["visual", "logo", "color", "design", "layout"])
            visual_assessment = "Visual assets demonstrate compliant primary color balance and clear brand mark visibility."
            findings.append(
                BrandFinding(
                    state="aligned",
                    passage=f"Visual asset: {content.file_name or content.content_type}",
                    location="layout",
                    violation_category="visual",
                    explanation="Asset typography and color harmony align with visual brand identity guidelines.",
                    why_it_matters="Visual consistency across collateral builds immediate brand recognition.",
                    guideline_document=ref_visual.document,
                    guideline_section=ref_visual.passage_ref,
                    guideline_excerpt=ref_visual.excerpt,
                    suggested_fix=None,
                )
            )
        else:
            visual_assessment = "Visual verification reported unclear: no visual brand guidelines retrieved."
            findings.append(
                BrandFinding(
                    state="unclear",
                    passage=f"Visual asset: {content.file_name or content.content_type}",
                    location="layout",
                    violation_category="visual",
                    explanation="Retrieved guidelines do not include visual identity standards.",
                    why_it_matters="Visual checks require explicit brand design specifications.",
                    guideline_document=guidelines[0].document,
                    guideline_section=guidelines[0].passage_ref,
                    guideline_excerpt=guidelines[0].excerpt,
                    suggested_fix=None,
                    uncertainty_note="Retrieved guidelines cover text/claims only; visual identity review requires design playbook.",
                )
            )

    # If no violations found in text, add aligned finding
    if not [f for f in findings if f.state == "potential_issue"] and text:
        ref_tone = guidelines[0]
        sample_passage = text[:60].strip()
        findings.append(
            BrandFinding(
                state="aligned",
                passage=sample_passage,
                location="opening",
                violation_category="tone",
                explanation="Brand tone adheres to established clarity and professionalism standards.",
                why_it_matters="Consistent tone reinforces brand authority across all channels.",
                guideline_document=ref_tone.document,
                guideline_section=ref_tone.passage_ref,
                guideline_excerpt=ref_tone.excerpt,
                suggested_fix=None,
            )
        )

    overall = _compute_overall_alignment(findings)

    return BrandVerificationOutput(
        overall_alignment=overall,
        voice_and_tone_assessment="Content demonstrates clear communication with highlighted areas for voice alignment.",
        terminology_assessment="Vocabulary checked against prohibited buzzword and brand positioning registries.",
        visual_brand_assessment=visual_assessment,
        findings=findings,
    )
