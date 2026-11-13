"""Structured Pydantic schemas for Inkloom AI Intelligence outputs.

These schemas power all seven AI verification areas:
1. Content Understanding
2. Brand Verification
3. External Claim Verification
4. AI Flagging
5. Suggestions and Corrections
6. Visual and Accessibility Intelligence
7. Governance Intelligence

Used directly with Gemini structured JSON output (response_schema)
and for type-safe validation across the application.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from app.models import (
    BRAND_STATES,
    CLAIM_STATES,
    ExternalSource,
    FlagDraft,
    GuidelineRef,
)


# ============================================================================
# 1. CONTENT UNDERSTANDING SCHEMAS
# ============================================================================

ClaimType = Literal["fact", "opinion", "mixed"]
EntityType = Literal[
    "proper_name",
    "date",
    "number",
    "metric",
    "condition",
    "legal_term",
    "url",
]


class ExtractedClaim(BaseModel):
    """An individual atomic claim extracted from the draft content."""

    claim_id: str = Field(description="Unique identifier for the claim (e.g. claim-1)")
    text: str = Field(description="The normalized text statement of the claim")
    claim_type: ClaimType = Field(description="Whether the statement is fact, opinion, or mixed")
    passage: str = Field(description="Exact substring as it appears in the original text")
    location: str = Field(description="Readable location in the document (e.g. 'paragraph 1')")


class PreservedEntity(BaseModel):
    """Critical factual token (name, date, number, condition) that must be preserved."""

    entity_type: EntityType = Field(description="Category of the entity")
    text: str = Field(description="Exact text of the entity")
    context: str = Field(description="Brief surrounding phrase or context")


class ContentUnderstandingOutput(BaseModel):
    """Structured understanding of draft content context, claims, and intent."""

    summary: str = Field(description="Concise 1-2 sentence synopsis of the content")
    target_audience: str = Field(description="Identified target audience for the submission")
    purpose: str = Field(description="Intended communication purpose or distribution channel")
    tone: str = Field(description="Observed tone (e.g. formal, technical, sensational, conversational)")
    intended_message: str = Field(description="Core thesis or takeaway intended by the creator")
    claims: List[ExtractedClaim] = Field(
        default_factory=list,
        description="List of individual factual, opinion, or mixed claims extracted from text",
    )
    preserved_entities: List[PreservedEntity] = Field(
        default_factory=list,
        description="Critical dates, numbers, names, and conditions to protect from modification",
    )


# ============================================================================
# 2. BRAND VERIFICATION SCHEMAS
# ============================================================================

BrandState = Literal["aligned", "potential_issue", "unclear"]
ViolationCategory = Literal[
    "tone",
    "buzzword",
    "superlative",
    "terminology",
    "visual",
    "positioning",
    "other",
]


class BrandFinding(BaseModel):
    """A specific brand compliance evaluation for a passage or visual asset."""

    state: BrandState = Field(description="Compliance status ('aligned', 'potential_issue', 'unclear')")
    passage: str = Field(description="Verbatim excerpt or visual description evaluated")
    location: str = Field(description="Location in the asset (e.g. 'characters 12-45' or 'header')")
    violation_category: ViolationCategory = Field(
        default="other", description="Category of brand guideline evaluated"
    )
    explanation: str = Field(description="Clear explanation of why the passage violates or adheres to the rule")
    why_it_matters: str = Field(description="Business or brand governance rationale for this rule")
    guideline_document: Optional[str] = Field(default=None, description="Source guideline document name")
    guideline_section: Optional[str] = Field(default=None, description="Section or rule identifier")
    guideline_excerpt: Optional[str] = Field(default=None, description="Relevant excerpt from the guideline")
    suggested_fix: Optional[str] = Field(default=None, description="Initial suggested replacement text")
    uncertainty_note: Optional[str] = Field(
        default=None, description="Explanation if evaluation is borderline or ambiguous"
    )


class BrandVerificationOutput(BaseModel):
    """Aggregate brand compliance evaluation report."""

    overall_alignment: BrandState = Field(description="Overall brand check status")
    voice_and_tone_assessment: str = Field(description="Narrative assessment of voice, tone, and pacing")
    terminology_assessment: str = Field(description="Check of preferred vs prohibited brand vocabulary")
    visual_brand_assessment: Optional[str] = Field(
        default=None, description="Visual identity, logo, and palette notes if applicable"
    )
    findings: List[BrandFinding] = Field(default_factory=list, description="List of granular brand findings")


# ============================================================================
# 3. EXTERNAL CLAIM VERIFICATION SCHEMAS
# ============================================================================

ClaimState = Literal["supported", "contradicted", "insufficient_evidence"]
EvidenceQuality = Literal["reliable", "outdated", "conflicting", "insufficient", "none"]


class ClaimFinding(BaseModel):
    """Verification of a factual claim against external evidence."""

    claim_text: str = Field(description="The factual statement being verified")
    passage: str = Field(description="The excerpt in the submitted draft containing the claim")
    location: str = Field(description="Document location of the claim")
    state: ClaimState = Field(description="Verdict: 'supported', 'contradicted', or 'insufficient_evidence'")
    explanation: str = Field(description="Clear rationale comparing the claim against retrieved evidence")
    why_it_matters: str = Field(description="Legal, regulatory, or reputation risk of unverified claim")
    evidence_source_url: Optional[str] = Field(default=None, description="Source URL or document reference")
    evidence_excerpt: Optional[str] = Field(default=None, description="Verbatim citation supporting the verdict")
    evidence_quality: EvidenceQuality = Field(
        default="none", description="Assessment of evidence freshness and reliability"
    )
    uncertainty_note: Optional[str] = Field(
        default=None, description="Explicit note if evidence is contradictory or incomplete"
    )
    suggested_fix: Optional[str] = Field(
        default=None, description="Correction aligning claim with verified evidence"
    )
    external_sources: List[ExternalSource] = Field(
        default_factory=list, description="Structured external evidence sources supporting the finding"
    )

    def model_post_init(self, __context):
        # Auto-sync external_sources list and single url/excerpt fields
        if not self.external_sources and self.evidence_source_url and self.evidence_excerpt:
            self.external_sources = [
                ExternalSource(url=self.evidence_source_url, excerpt=self.evidence_excerpt)
            ]
        elif self.external_sources and not self.evidence_source_url:
            self.evidence_source_url = self.external_sources[0].url
            self.evidence_excerpt = self.external_sources[0].excerpt


class ClaimVerificationOutput(BaseModel):
    """Aggregate claim verification report."""

    findings: List[ClaimFinding] = Field(default_factory=list, description="Claim-by-claim verification findings")


# ============================================================================
# 4. AI FLAGGING SYNTHESIS SCHEMAS
# ============================================================================


class SynthesizedFlag(BaseModel):
    """Direct bridge to Gaurav's FlagDraft model."""

    finding_type: Literal["brand", "claim"]
    state: str
    passage: str
    location: str
    explanation: str
    why_it_matters: str
    guideline_ref: Optional[GuidelineRef] = None
    guideline_refs: List[GuidelineRef] = Field(default_factory=list)
    external_sources: List[ExternalSource] = Field(default_factory=list)
    uncertainty_note: Optional[str] = None
    suggested_correction: Optional[str] = None
    origin: Literal["module", "fixture", "error"] = "module"
    status: str = "open"
    comments: List[str] = Field(default_factory=list)
    needs_human: bool = False

    def model_post_init(self, __context):
        from app.uncertainty import needs_human
        self.needs_human = needs_human(self.state)

    def to_flag_draft(self) -> FlagDraft:
        """Convert synthesized flag directly into Gaurav's domain FlagDraft."""
        return FlagDraft(
            finding_type=self.finding_type,
            state=self.state,
            passage=self.passage,
            location=self.location,
            explanation=self.explanation,
            why_it_matters=self.why_it_matters,
            guideline_ref=self.guideline_ref,
            guideline_refs=self.guideline_refs,
            external_sources=self.external_sources,
            uncertainty_note=self.uncertainty_note,
            suggested_correction=self.suggested_correction,
            origin=self.origin,
            status=self.status,
            comments=self.comments,
        )


class FlaggingOutput(BaseModel):
    """Synthesized collection of flags ready for the review pipeline."""

    flags: List[SynthesizedFlag] = Field(default_factory=list)


# ============================================================================
# 5. SUGGESTIONS & CORRECTIONS SCHEMAS
# ============================================================================


class CorrectionOutput(BaseModel):
    """A minimal, source-backed suggestion that protects critical entities."""

    flag_id: Optional[str] = Field(default=None, description="ID of the flag being corrected")
    original_passage: str = Field(description="The problematic text being replaced")
    suggested_replacement: str = Field(description="The recommended replacement text")
    change_rationale: str = Field(description="Explanation of why this replacement resolves the violation")
    entities_preserved: List[str] = Field(
        default_factory=list,
        description="List of entities (numbers, names, specs) confirmed preserved in replacement",
    )
    recheck_passed: bool = Field(
        default=True,
        description="Whether a simulated re-check confirmed no new violations are introduced",
    )
    recheck_notes: Optional[str] = Field(
        default=None, description="Notes on compliance of candidate correction"
    )


# ============================================================================
# 6. VISUAL & ACCESSIBILITY SCHEMAS
# ============================================================================

AccessibilityIssueType = Literal[
    "contrast",
    "readability",
    "hierarchy",
    "text_density",
    "color_blindness",
    "missing_alt",
]


class AccessibilityIssue(BaseModel):
    """An identified visual accessibility or usability issue."""

    issue_type: AccessibilityIssueType = Field(description="Type of accessibility barrier")
    description: str = Field(description="Detailed description of the issue")
    severity: Literal["low", "medium", "high"] = Field(description="Urgency/severity")
    element_location: str = Field(description="Visual coordinate or area in the asset")
    recommendation: str = Field(description="Actionable fix to achieve compliance (e.g. WCAG AA)")


class VisualAccessibilityOutput(BaseModel):
    """Multimodal evaluation of brand aesthetics and accessibility."""

    has_visual_content: bool = Field(description="Whether visual media was present and analyzed")
    detected_logos: List[str] = Field(default_factory=list, description="Identified brand logos or marks")
    color_palette: List[str] = Field(
        default_factory=list, description="Primary hex codes or color descriptions observed"
    )
    visual_consistency_score: str = Field(
        default="moderate", description="Cohesion assessment (e.g. 'high', 'moderate', 'low')"
    )
    visual_brand_alignment: BrandState = Field(
        default="aligned", description="Brand visual identity status"
    )
    visual_brand_notes: str = Field(default="", description="Visual style summary")
    accessibility_issues: List[AccessibilityIssue] = Field(
        default_factory=list, description="Detected accessibility hurdles"
    )


# ============================================================================
# 7. GOVERNANCE INTELLIGENCE SCHEMAS
# ============================================================================


class RecurringViolation(BaseModel):
    """A pattern of repeated non-compliance identified across review history."""

    rule_or_topic: str = Field(description="The guideline or topic repeatedly violated")
    frequency: int = Field(description="Number of times this violation appeared across submissions")
    severity: str = Field(description="Impact level on brand reputation")
    guideline_reference: Optional[str] = Field(default=None, description="Document or section citation")
    recommendation: str = Field(description="Policy or author training guidance to mitigate repeat issues")


class AmbiguousGuideline(BaseModel):
    """A guideline that generates confusion or high escalation rates."""

    guideline_title: str = Field(description="The guideline document or rule name")
    human_escalation_count: int = Field(description="Number of times reviews required human escalation")
    reason_for_ambiguity: str = Field(description="Why reviewers or creators struggle with this rule")
    suggested_clarification: str = Field(description="Proposed wording rewrite to eliminate ambiguity")


class GovernanceInsightsOutput(BaseModel):
    """Strategic governance report generated from review history."""

    total_reviews_analyzed: int = Field(description="Count of historical submissions analyzed")
    top_recurring_violations: List[RecurringViolation] = Field(
        default_factory=list, description="Ranked recurring violations"
    )
    ambiguous_guidelines: List[AmbiguousGuideline] = Field(
        default_factory=list, description="Identified policies needing clarification"
    )
    summary_narrative: str = Field(
        description="Executive summary of governance health and compliance recommendations"
    )

