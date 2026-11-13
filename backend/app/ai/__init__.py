"""Inkloom AI Intelligence and Verification Module.

Owner: Sera
Provides Gemini-powered content understanding, brand verification,
claim verification, AI flagging, suggestions, visual intelligence,
and governance insights.
"""

from app.ai.brand_verification import (
    brand_finding_to_flag_draft,
    resolve_media_mime,
    validate_and_ground_findings,
    verify_brand,
)
from app.ai.claim_verification import (
    claim_finding_to_flag_draft,
    validate_and_ground_claim_findings,
    verify_claims,
    verify_claims_against_evidence,
)
from app.ai.client import (
    GeminiAPIError,
    GeminiClient,
    GeminiConfigurationError,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiQuotaError,
    GeminiTimeoutError,
)
from app.ai.content_understanding import understand_content, understand_text
from app.ai.flagging import (
    consolidate_flags,
    deduplicate_and_synthesize_flag_drafts,
    summarize_flag_metrics,
    synthesize_flag_drafts,
)
from app.ai.governance_intelligence import generate_governance_insights
from app.ai.schemas import (
    AccessibilityIssue,
    AmbiguousGuideline,
    BrandFinding,
    BrandVerificationOutput,
    ClaimFinding,
    ClaimVerificationOutput,
    ContentUnderstandingOutput,
    CorrectionOutput,
    ExtractedClaim,
    FlaggingOutput,
    GovernanceInsightsOutput,
    PreservedEntity,
    RecurringViolation,
    SuggestionsOutput,
    SynthesizedFlag,
    VisualAccessibilityOutput,
)
from app.ai.suggestions_corrections import (
    check_entity_preservation,
    generate_correction,
    generate_corrections,
    recheck_correction,
)
from app.ai.visual_accessibility import (
    analyze_visual_accessibility,
    calculate_contrast_ratio,
    calculate_relative_luminance,
    evaluate_wcag_contrast,
)

__all__ = [
    # Core Functions
    "understand_content",
    "understand_text",
    "verify_brand",
    "validate_and_ground_findings",
    "brand_finding_to_flag_draft",
    "resolve_media_mime",
    "claim_finding_to_flag_draft",
    "verify_claims",
    "verify_claims_against_evidence",
    "validate_and_ground_claim_findings",
    "synthesize_flag_drafts",
    "deduplicate_and_synthesize_flag_drafts",
    "consolidate_flags",
    "summarize_flag_metrics",
    "generate_correction",
    "generate_corrections",
    "recheck_correction",
    "check_entity_preservation",
    "analyze_visual_accessibility",
    "calculate_contrast_ratio",
    "calculate_relative_luminance",
    "evaluate_wcag_contrast",
    "generate_governance_insights",
    # Client & Exceptions
    "GeminiClient",
    "GeminiError",
    "GeminiConfigurationError",
    "GeminiAPIError",
    "GeminiTimeoutError",
    "GeminiModelNotFoundError",
    "GeminiQuotaError",
    # Schemas
    "ContentUnderstandingOutput",
    "ExtractedClaim",
    "PreservedEntity",
    "BrandVerificationOutput",
    "BrandFinding",
    "ClaimVerificationOutput",
    "ClaimFinding",
    "FlaggingOutput",
    "SynthesizedFlag",
    "CorrectionOutput",
    "SuggestionsOutput",
    "VisualAccessibilityOutput",
    "AccessibilityIssue",
    "GovernanceInsightsOutput",
    "RecurringViolation",
    "AmbiguousGuideline",
]
