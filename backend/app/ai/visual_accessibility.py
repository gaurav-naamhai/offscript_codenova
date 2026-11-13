"""Visual and Accessibility Intelligence module for Inkloom AI.

Owner: Sera
Analyzes images, visual layouts, and graphics using Gemini multimodal capabilities.
Identifies logos and visual brand consistency against supplied guidelines, extracts
palette colors, and evaluates accessibility heuristics (measurable text/background contrast,
typography readability, visual hierarchy, alt-text requirements).
Distinguishes measurable observations from visual estimates, avoids inventing brand rules,
and escalates uncertain findings for human review.
"""

from datetime import datetime, timezone
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from google.genai import types

from app.ai.brand_verification import resolve_media_mime
from app.ai.client import GeminiClient
from app.ai.schemas import (
    AccessibilityIssue,
    BrandState,
    VisualAccessibilityOutput,
)
from app.config import Settings
from app.models import ContentPayload, GuidelineRef

logger = logging.getLogger(__name__)

VISUAL_SYSTEM_INSTRUCTION = """You are the Senior Visual Identity, Brand Design, and Accessibility Specialist for Inkloom AI.
Your responsibility is to analyze visual assets (marketing graphics, UI screenshots, promotional banners, and document layouts) for brand consistency and digital accessibility.

CRITICAL OPERATIONAL RULES:
1. LOGO & BRAND IDENTITY:
   - Identify visible brand logos, wordmarks, and iconography.
   - Check against supplied brand guidelines for logo misuse (distortion, incorrect aspect ratio, lack of clearspace/padding, or unapproved color modifications).
   - If guidelines DO NOT specify logo rules, DO NOT invent brand rules. State that guidelines do not specify logo restrictions.
2. COLOR PALETTE & VISUAL HARMONY:
   - Extract the dominant primary and secondary colors observed (provide estimated hex codes e.g. #0F172A, #3B82F6, #FFFFFF).
   - Compare observed palette against supplied brand guidelines. If no palette guidelines exist, assign visual_brand_alignment='aligned' or 'unclear' with an uncertainty note.
3. ACCESSIBILITY HEURISTICS & WCAG DISTINCTIONS:
   - CONTRAST RATIO & WCAG 2.1 AA THRESHOLDS:
     * Normal body text requires at least 4.5:1 contrast.
     * Large text (headings >= 18pt/24px regular or >= 14pt/18.5px bold) and UI components require at least 3.0:1 contrast.
     * Do NOT fail large text if its contrast ratio is >= 3.0:1.
   - STRICT DISTINCTION: MEASURED vs. VISUAL ESTIMATES:
     * Never label visually estimated colors or eyeball estimates as '[Measured]'.
     * When contrast is calculated from visual color estimates of an image screenshot, label the finding prefix as '[Visual Estimate: Calculated Contrast]' and state the estimated foreground and background colors.
     * Only when exact pixel hex codes or design tokens are verified from sampled asset data can a finding be prefixed with '[Measured Contrast]'.
     * For typography sizes, spacing, and visual hierarchy lacking DOM metrics, prefix with '[Visual Estimate]'.
   - NEVER CLAIM FULL WCAG COMPLIANCE. Clearly state that automated checks identify potential hurdles and formal compliance requires complete human assistive-technology verification.
4. ACTIONABLE RECOMMENDATIONS:
   - For every detected issue, provide a practical, non-destructive recommendation (e.g. 'Darken text color to #475569 to achieve at least 4.5:1 contrast against white background').
5. UNCERTAINTY & HUMAN REVIEW:
   - If the image is blurry, low-resolution, ambiguous, or lacks guideline context, provide an uncertainty_note and recommend human review.

Always return strictly valid JSON matching the VisualAccessibilityOutput schema."""


# ============================================================================
# EMPIRICAL CONTRAST MEASUREMENT HELPERS (WCAG 2.1 FORMULA)
# ============================================================================


def _hex_to_rgb(hex_code: str) -> Optional[Tuple[int, int, int]]:
    """Parse hex code (e.g. '#FFFFFF' or 'FFF') into RGB integers."""
    clean = hex_code.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        return None
    try:
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
        return r, g, b
    except ValueError:
        return None


def _calculate_srgb_luminance(color_value: int) -> float:
    """Calculate relative sRGB channel luminance component."""
    c = color_value / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def calculate_relative_luminance(hex_code: str) -> Optional[float]:
    """Calculate relative luminance (0.0 to 1.0) according to WCAG 2.1 definition."""
    rgb = _hex_to_rgb(hex_code)
    if not rgb:
        return None
    r, g, b = rgb
    rl = _calculate_srgb_luminance(r)
    gl = _calculate_srgb_luminance(g)
    bl = _calculate_srgb_luminance(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def calculate_contrast_ratio(hex_fg: str, hex_bg: str) -> Optional[float]:
    """Calculate the WCAG contrast ratio between foreground and background colors.

    Returns a float between 1.0 (no contrast) and 21.0 (black on white), or None if invalid hex.
    """
    lum1 = calculate_relative_luminance(hex_fg)
    lum2 = calculate_relative_luminance(hex_bg)
    if lum1 is None or lum2 is None:
        return None

    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def evaluate_wcag_contrast(
    hex_fg: str,
    hex_bg: str,
    is_large_text: bool = False,
    is_ui_component: bool = False,
    is_measured: bool = False,
) -> Dict[str, Any]:
    """Evaluate contrast against WCAG 2.1 AA thresholds, distinguishing measured vs estimated colors.

    Thresholds:
    - Normal body text: >= 4.5:1
    - Large text (>= 18pt regular or >= 14pt bold, approx >= 24px regular or >= 18.5px bold): >= 3.0:1
    - UI components and essential graphics: >= 3.0:1

    Distinction:
    - is_measured=True: Labeled as '[Measured Contrast]' when colors are extracted from exact pixels/tokens.
    - is_measured=False: Labeled as '[Visual Estimate: Calculated Contrast]' when colors are visually estimated by AI.
    """
    ratio = calculate_contrast_ratio(hex_fg, hex_bg)
    if ratio is None:
        return {
            "valid": False,
            "ratio": None,
            "passes_aa": False,
            "threshold": None,
            "text_type": "unknown",
            "is_measured": is_measured,
            "prefix": "[Visual Estimate: Unverifiable Hex]",
        }

    threshold = 3.0 if (is_large_text or is_ui_component) else 4.5
    passes_aa = (ratio >= threshold)
    text_type = "large text" if is_large_text else ("ui component" if is_ui_component else "normal text")
    prefix = "[Measured Contrast]" if is_measured else "[Visual Estimate: Calculated Contrast]"

    return {
        "valid": True,
        "ratio": ratio,
        "passes_aa": passes_aa,
        "threshold": threshold,
        "text_type": text_type,
        "is_measured": is_measured,
        "prefix": prefix,
    }


# ============================================================================
# MAIN VISUAL & ACCESSIBILITY ANALYSIS
# ============================================================================


def analyze_visual_accessibility(
    content: ContentPayload,
    guidelines: Optional[List[GuidelineRef]] = None,
    client: Optional[GeminiClient] = None,
) -> VisualAccessibilityOutput:
    """Analyze visual assets for logo consistency, brand colors, and accessibility barriers.

    Args:
        content: ContentPayload containing image bytes, file name, or text.
        guidelines: Optional retrieved brand guidelines.
        client: Optional GeminiClient instance.

    Returns:
        Structured VisualAccessibilityOutput report.
    """
    ai_client = client or GeminiClient(settings=Settings())

    # 1. Gracefully handle non-visual or text-only submissions
    has_bytes = bool(content.file_bytes and len(content.file_bytes) > 0)
    is_image_type = (content.content_type == "image") or (
        content.file_mime and content.file_mime.startswith("image/")
    )

    if not has_bytes or not is_image_type:
        logger.info("Submission contains no visual image payload; skipping visual/accessibility analysis.")
        return VisualAccessibilityOutput(
            has_visual_content=False,
            detected_logos=[],
            color_palette=[],
            visual_consistency_score="not_applicable",
            visual_brand_alignment="aligned",
            visual_brand_notes="No visual assets were supplied in this submission. Visual and accessibility analysis was skipped.",
            accessibility_issues=[],
            needs_human=False,
            uncertainty_note=None,
        )

    # Validate image MIME
    mime_type = resolve_media_mime(content)
    if not mime_type.startswith("image/"):
        logger.warning("Invalid or non-image MIME type encountered for visual analysis: %s", mime_type)
        return VisualAccessibilityOutput(
            has_visual_content=False,
            detected_logos=[],
            color_palette=[],
            visual_consistency_score="not_applicable",
            visual_brand_alignment="unclear",
            visual_brand_notes=f"Unsupported visual MIME type '{mime_type}'. Cannot perform visual analysis.",
            accessibility_issues=[],
            needs_human=True,
            uncertainty_note=f"Unsupported visual file format '{mime_type}'. Human visual verification required.",
        )

    # 2. Deterministic Mock Mode Execution
    if ai_client.mock_mode:
        if VisualAccessibilityOutput in ai_client._mock_handlers:
            return ai_client.generate_structured(prompt="", response_schema=VisualAccessibilityOutput)

        return _generate_mock_visual_accessibility(
            content=content,
            guidelines=guidelines,
        )

    # 3. Live Gemini Multimodal Execution
    guideline_text = "No specific brand visual guidelines provided."
    if guidelines:
        guideline_text = "\n".join(
            [
                f"  - Document: {g.document} (Section: {g.passage_ref})\n"
                f"    Rule Excerpt: \"{g.excerpt}\""
                for g in guidelines
            ]
        )

    prompt = (
        "Perform a thorough visual brand compliance and digital accessibility audit of this submitted asset.\n\n"
        f"SUPPLIED BRAND GUIDELINES:\n{guideline_text}\n\n"
        "Tasks to perform:\n"
        "1. Identify visible brand logos and verify clearspace, alignment, and aspect ratio.\n"
        "2. Extract primary color palette hex codes.\n"
        "3. Evaluate visual accessibility (contrast, typography readability, visual hierarchy, alt text).\n"
        "4. Prefix findings with [Measurable] or [Visual Estimate]. Do NOT claim full WCAG compliance.\n"
        "5. If guidelines do not specify rules, report uncertainty rather than inventing rules."
    )

    image_part = types.Part.from_bytes(data=content.file_bytes, mime_type=mime_type)

    output = ai_client.generate_structured(
        prompt=[prompt, image_part],
        response_schema=VisualAccessibilityOutput,
        system_instruction=VISUAL_SYSTEM_INSTRUCTION,
    )

    # Post-process: ensure uncertainty notes escalate needs_human
    if output.visual_brand_alignment == "unclear" or output.uncertainty_note:
        output.needs_human = True

    return output


# ============================================================================
# DETERMINISTIC MOCK VISUAL ACCESSIBILITY GENERATOR
# ============================================================================


def _generate_mock_visual_accessibility(
    content: ContentPayload,
    guidelines: Optional[List[GuidelineRef]],
) -> VisualAccessibilityOutput:
    """Generate realistic, deterministic visual & accessibility findings for offline testing."""
    file_name = (content.file_name or "").lower()

    # Standard detected palette
    palette = ["#0F172A", "#3B82F6", "#FFFFFF", "#94A3B8"]

    # Calculate empirical contrast between light gray and white to demonstrate measurable finding
    ratio = calculate_contrast_ratio("#94A3B8", "#FFFFFF") or 2.61

    # Heuristic issues based on filename or standard demo asset
    issues: List[AccessibilityIssue] = []

    # 1. Calculated Contrast from Visually Estimated Colors (Normal Text)
    eval_normal = evaluate_wcag_contrast("#94A3B8", "#FFFFFF", is_large_text=False, is_measured=False)
    issues.append(
        AccessibilityIssue(
            issue_type="contrast",
            description=(
                f"{eval_normal['prefix']} Secondary label text with estimated colors #94A3B8 on #FFFFFF "
                f"yields a calculated contrast ratio of {eval_normal['ratio']}:1, falling below the "
                f"WCAG 2.1 AA requirement of {eval_normal['threshold']}:1 for normal body text."
            ),
            severity="high",
            element_location="secondary card footer",
            recommendation="Darken text color to #475569 to achieve at least 4.5:1 contrast against white background.",
        )
    )

    # 2. Visual Estimate Readability Issue
    issues.append(
        AccessibilityIssue(
            issue_type="readability",
            description=(
                "[Visual Estimate] Disclaimer typography in footer appears to render below 11px equivalent, "
                "which may cause visual strain on standard mobile screens."
            ),
            severity="medium",
            element_location="bottom footer disclaimer",
            recommendation="Increase minimum footer font size to at least 12px for mobile legibility.",
        )
    )

    # 3. Visual Hierarchy Estimate
    issues.append(
        AccessibilityIssue(
            issue_type="hierarchy",
            description=(
                "[Visual Estimate] Primary call-to-action button has minimal visual distinction "
                "from surrounding secondary card elements."
            ),
            severity="low",
            element_location="hero CTA button",
            recommendation="Increase whitespace padding and elevate primary button styling.",
        )
    )

    # Check guidelines for logo rules
    has_logo_guideline = bool(
        guidelines and any("logo" in (g.excerpt or "").lower() for g in guidelines)
    )

    if "distorted" in file_name or "bad_logo" in file_name:
        brand_alignment = "potential_issue"
        notes = (
            "Detected Inkloom brand logo. Logo appears distorted and stretched horizontally, violating aspect ratio rules."
        )
        logos = ["Inkloom Primary Wordmark (Distorted)"]
        uncertainty = None
        needs_human_eval = True
    elif not guidelines:
        # Zero-guideline rule: when guidelines are absent, report uncertainty rather than inventing rules!
        brand_alignment = "unclear"
        notes = (
            "Visual assets analyzed. Observed standard corporate palette and wordmark. "
            "No brand guideline was supplied to verify official logo clearspace or brand color codes."
        )
        logos = ["Inkloom Primary Wordmark"]
        uncertainty = "Brand visual guidelines were not supplied. Visual identity compliance requires human review."
        needs_human_eval = True
    else:
        brand_alignment = "aligned"
        notes = (
            "Brand logo complies with clearspace and orientation rules. "
            "Color palette (#0F172A, #3B82F6) matches Brand Visual Identity guidelines."
        )
        logos = ["Inkloom Primary Wordmark"]
        uncertainty = None
        needs_human_eval = False

    return VisualAccessibilityOutput(
        has_visual_content=True,
        detected_logos=logos,
        color_palette=palette,
        visual_consistency_score="high" if brand_alignment == "aligned" else "moderate",
        visual_brand_alignment=brand_alignment,
        visual_brand_notes=notes,
        accessibility_issues=issues,
        needs_human=needs_human_eval,
        uncertainty_note=uncertainty,
    )
