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
    SynthesizedFlag,
    VisualAccessibilityOutput,
)

__all__ = [
    # Core Functions
    "understand_content",
    "understand_text",
    "verify_brand",
    "validate_and_ground_findings",
    "brand_finding_to_flag_draft",
    "resolve_media_mime",
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
    "VisualAccessibilityOutput",
    "AccessibilityIssue",
    "GovernanceInsightsOutput",
    "RecurringViolation",
    "AmbiguousGuideline",
]
