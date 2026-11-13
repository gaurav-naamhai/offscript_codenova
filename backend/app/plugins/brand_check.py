"""Brand check plugin.

OWNER: Sera
Wires Gaurav's FastAPI pipeline to Sera's AI modules:
- Content Understanding (app.ai.content_understanding)
- Brand Verification (app.ai.brand_verification)
- Suggestions & Corrections (app.ai.suggestions_corrections)
- Visual & Accessibility Intelligence (app.ai.visual_accessibility)

Maintains exact signature check_brand(content, guidelines) -> List[FlagDraft].
Gracefully falls back to offline fixture rules when credentials / mock mode are unavailable.
"""

import logging
import re
from typing import List, Optional

from app.ai.brand_verification import (
    brand_finding_to_flag_draft,
    verify_brand,
)
from app.ai.client import GeminiClient
from app.ai.content_understanding import understand_content
from app.ai.suggestions_corrections import generate_correction
from app.ai.visual_accessibility import analyze_visual_accessibility
from app.config import Settings
from app.models import ContentPayload, FlagDraft, GuidelineRef

logger = logging.getLogger(__name__)

# Deterministic fixture rules for offline fallback
RULES = [
    {
        "id": "brand-exclamation",
        "pattern": re.compile(r"!{2,}"),
        "state": "potential_issue",
        "explanation": "Multiple exclamation marks violate professional brand tone guidelines.",
        "why_it_matters": "Maintains an approachable, clear, and trustworthy voice.",
        "replacement": ".",
    },
    {
        "id": "brand-buzzword",
        "pattern": re.compile(r"\b(synergy|disruptive|game-changing)\b", re.IGNORECASE),
        "state": "potential_issue",
        "explanation": "Corporate buzzwords conflict with plain-English communication principles.",
        "why_it_matters": "Clear terminology preserves credibility across enterprise audiences.",
        "replacement": "effective collaboration",
    },
    {
        "id": "brand-cheap",
        "pattern": re.compile(r"\bcheap\b", re.IGNORECASE),
        "state": "potential_issue",
        "explanation": "Term 'cheap' undermines premium brand positioning standards.",
        "why_it_matters": "Messaging must highlight cost-efficiency and value over low cost.",
        "replacement": "cost-effective",
    },
]


def check_brand(
    content: ContentPayload,
    guidelines: List[GuidelineRef],
    client: Optional[GeminiClient] = None,
) -> List[FlagDraft]:
    """Check draft content against brand guidelines and voice principles.

    In AI mode (MOCK_AI=true or GEMINI_API_KEY present): executes Sera's
    multimodal Content Understanding, Brand Verification, Visual & Accessibility
    Intelligence, and entity-preserving Suggestions/Corrections.

    In offline/fixture mode: falls back to deterministic regex RULES with
    origin='fixture' for testing resilience without live credentials.
    """
    settings = Settings()
    use_ai = (client is not None) or settings.mock_ai or bool(settings.gemini_api_key)
    ref = guidelines[0] if guidelines else None

    # -------------------------------------------------------------------------
    # OFFLINE FIXTURE FALLBACK (No AI credentials or explicit mock active)
    # -------------------------------------------------------------------------
    if not use_ai:
        if content.content_type in ("image", "pdf") or not content.text:
            return [
                FlagDraft(
                    finding_type="brand",
                    state="unclear",
                    passage="",
                    location="document",
                    explanation="Visual/document brand review requires multimodal design review module.",
                    why_it_matters="Ensures design assets comply with brand typography and visual standards.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    origin="fixture",
                )
            ]

        fixture_flags: List[FlagDraft] = []
        text = content.text
        for rule in RULES:
            for match in rule["pattern"].finditer(text):
                start, end = match.span()
                fixture_flags.append(
                    FlagDraft(
                        finding_type="brand",
                        state=rule["state"],
                        passage=text[start:end],
                        location=f"characters {start}-{end}",
                        explanation=rule["explanation"],
                        why_it_matters=rule["why_it_matters"],
                        guideline_ref=ref,
                        guideline_refs=[ref] if ref else [],
                        suggested_correction=rule["replacement"],
                        origin="fixture",
                    )
                )

        if not fixture_flags:
            sample_passage = text[:60].strip() if text else "Draft text"
            fixture_flags.append(
                FlagDraft(
                    finding_type="brand",
                    state="aligned",
                    passage=sample_passage,
                    location="content",
                    explanation="Content voice aligns with core brand guidelines.",
                    why_it_matters="Consistent tone reinforces brand recognition and authority.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    origin="fixture",
                )
            )

        return fixture_flags

    # -------------------------------------------------------------------------
    # AI INTELLIGENCE PIPELINE (Sera's modules)
    # -------------------------------------------------------------------------
    ai_client = client or GeminiClient(settings=settings)
    flags: List[FlagDraft] = []

    # Case 1: Image Multimodal Asset
    if content.content_type == "image":
        # 1. Run Visual & Accessibility Intelligence (WCAG contrast, logos, palette)
        visual_output = analyze_visual_accessibility(content, guidelines=guidelines, client=ai_client)

        for issue in visual_output.accessibility_issues:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state="potential_issue",
                    passage=f"Accessibility: {issue.issue_type.title()} in {issue.element_location}",
                    location=issue.element_location,
                    explanation=issue.description,
                    why_it_matters="Ensures digital assets comply with digital accessibility and readability standards.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    suggested_correction=issue.recommendation,
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        if visual_output.visual_brand_alignment != "aligned" or visual_output.uncertainty_note:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state=visual_output.visual_brand_alignment,
                    passage=f"Visual asset: {content.file_name or 'Uploaded image'}",
                    location="Visual layout",
                    explanation=visual_output.visual_brand_notes or "Visual brand consistency evaluation.",
                    why_it_matters="Consistent visual presentation protects brand recognition and design standards.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    uncertainty_note=visual_output.uncertainty_note,
                    suggested_correction="Align visual elements and logo presentation with brand guidelines.",
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        # 2. Also run Brand Verification if file bytes are present
        if content.file_bytes:
            brand_output = verify_brand(content, guidelines=guidelines, client=ai_client)
            for f in brand_output.findings:
                draft = brand_finding_to_flag_draft(f)
                if not draft.guideline_ref and ref:
                    draft.guideline_ref = ref
                    draft.guideline_refs = [ref]
                flags.append(draft)

        if not flags:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state="aligned",
                    passage=f"Visual asset: {content.file_name or 'Uploaded image'}",
                    location="Visual layout",
                    explanation=visual_output.visual_brand_notes or "Visual design and logo presentation align with brand guidelines.",
                    why_it_matters="Consistent visual styling reinforces brand recognition.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        return flags

    # Case 2: PDF Document Asset
    if content.content_type == "pdf":
        # 1. Run visual accessibility analysis on rendered PDF page
        visual_output = analyze_visual_accessibility(content, guidelines=guidelines, client=ai_client)
        for issue in visual_output.accessibility_issues:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state="potential_issue",
                    passage=f"Accessibility: {issue.issue_type.title()} in {issue.element_location}",
                    location=issue.element_location,
                    explanation=issue.description,
                    why_it_matters="Ensures digital assets comply with digital accessibility and readability standards.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    suggested_correction=issue.recommendation,
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        if visual_output.visual_brand_alignment != "aligned" or visual_output.uncertainty_note:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state=visual_output.visual_brand_alignment,
                    passage=f"PDF Document: {content.file_name or 'Uploaded document'}",
                    location="Document visual layout",
                    explanation=visual_output.visual_brand_notes or "PDF document visual layout and contrast evaluation.",
                    why_it_matters="Consistent visual presentation and readable contrast protect enterprise credibility.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    uncertainty_note=visual_output.uncertainty_note,
                    suggested_correction="Adjust typography size and color contrast to meet WCAG 2.1 AA standards.",
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        # 2. Run multimodal brand verification across document
        brand_output = verify_brand(content, guidelines=guidelines, client=ai_client)
        for f in brand_output.findings:
            draft = brand_finding_to_flag_draft(f)
            if not draft.guideline_ref and ref:
                draft.guideline_ref = ref
                draft.guideline_refs = [ref]
            flags.append(draft)

        if not flags:
            flags.append(
                FlagDraft(
                    finding_type="brand",
                    state="aligned",
                    passage=f"PDF Document: {content.file_name or 'Uploaded document'}",
                    location="Document",
                    explanation=visual_output.visual_brand_notes or "Document voice and layout align with brand guidelines.",
                    why_it_matters="Consistent presentation reinforces brand authority.",
                    guideline_ref=ref,
                    guideline_refs=[ref] if ref else [],
                    origin="module",
                    status="open",
                    comments=[],
                )
            )

        return flags

    # Case 3: Text Asset (default)
    if not (content.text and content.text.strip()):
        return [
            FlagDraft(
                finding_type="brand",
                state="unclear",
                passage="",
                location="content",
                explanation="Draft content is empty. Cannot evaluate brand voice without text.",
                why_it_matters="Brand compliance requires substantive draft content.",
                guideline_ref=ref,
                guideline_refs=[ref] if ref else [],
                origin="module",
                status="open",
                comments=[],
            )
        ]

    # 1. Content Understanding (extract claims and preserved entities)
    cu = understand_content(content, client=ai_client)

    # 2. Brand Verification against retrieved guidelines
    brand_output = verify_brand(
        content,
        guidelines=guidelines,
        content_understanding=cu,
        client=ai_client,
    )

    # 3. Generate entity-preserving corrections for actionable issues
    for finding in brand_output.findings:
        if finding.state == "potential_issue" and not finding.suggested_fix:
            corr = generate_correction(
                flag=finding,
                content_understanding=cu,
                guidelines=guidelines,
                client=ai_client,
            )
            if corr and corr.suggested_replacement and corr.suggested_replacement != finding.passage:
                finding.suggested_fix = corr.suggested_replacement

        draft = brand_finding_to_flag_draft(finding)
        if not draft.guideline_ref and ref:
            draft.guideline_ref = ref
            draft.guideline_refs = [ref]
        flags.append(draft)

    if not flags:
        sample_passage = content.text[:60].strip() if content.text else "Draft text"
        flags.append(
            FlagDraft(
                finding_type="brand",
                state="aligned",
                passage=sample_passage,
                location="content",
                explanation="Content voice aligns with core brand guidelines.",
                why_it_matters="Consistent tone reinforces brand recognition and authority.",
                guideline_ref=ref,
                guideline_refs=[ref] if ref else [],
                origin="module",
                status="open",
                comments=[],
            )
        )

    return flags
