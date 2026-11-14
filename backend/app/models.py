"""Data models and schemas for the compliance review backend."""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

RoleType = Literal["creator", "manager", "authorised_reviewer"]
SubmissionStateType = Literal["draft", "ai_review", "manager_review", "final_approval", "approved"]
DecisionAction = Literal["approve", "request_changes"]
FindingType = Literal["brand", "claim"]

BRAND_STATES = {"aligned", "potential_issue", "unclear"}
CLAIM_STATES = {"supported", "contradicted", "insufficient_evidence"}


EvidenceMode = Literal["internal_only", "external_only", "combined", "insufficient_evidence"]


@dataclass
class ContentPayload:
    content_type: str
    text: Optional[str] = None
    file_name: Optional[str] = None
    file_mime: Optional[str] = None
    file_bytes: Optional[bytes] = None


class GuidelineRef(BaseModel):
    document: str
    passage_ref: str
    excerpt: str
    source_reference: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    section: Optional[str] = None
    page_number: Optional[int] = None
    similarity: Optional[float] = None
    exact_violated_passage: Optional[str] = None


class ExternalSource(BaseModel):
    url: str
    excerpt: str
    title: Optional[str] = None
    domain: Optional[str] = None
    published_date: Optional[str] = None
    retrieved_at: Optional[str] = None
    evidence_quality: Optional[str] = "reliable"
    status: Optional[str] = "ok"
    error_reason: Optional[str] = None


class FlaggedSpan(BaseModel):
    exact_text: str
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    surrounding_passage: Optional[str] = None
    location_label: Optional[str] = None


class InternalEvidence(BaseModel):
    document: str
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    section: Optional[str] = None
    passage_ref: Optional[str] = None
    page_number: Optional[int] = None
    similarity: Optional[float] = None
    retrieved_chunk_text: Optional[str] = None
    excerpt: Optional[str] = None
    exact_violated_passage: Optional[str] = None

    @model_validator(mode="after")
    def _sync_text(self) -> "InternalEvidence":
        if not self.retrieved_chunk_text and self.excerpt:
            self.retrieved_chunk_text = self.excerpt
        elif not self.excerpt and self.retrieved_chunk_text:
            self.excerpt = self.retrieved_chunk_text
        if not self.retrieved_chunk_text and not self.excerpt:
            self.retrieved_chunk_text = ""
            self.excerpt = ""
        return self


class ExternalEvidence(BaseModel):
    title: Optional[str] = None
    url: str
    domain: Optional[str] = None
    published_date: Optional[str] = None
    retrieved_at: Optional[str] = None
    excerpt: str
    evidence_quality: Optional[str] = "reliable"
    status: Optional[str] = "ok"
    error_reason: Optional[str] = None


class SuggestionDetails(BaseModel):
    suggested_replacement: Optional[str] = None
    change_rationale: Optional[str] = None
    entities_preserved: List[str] = Field(default_factory=list)
    preserved_entities: List[str] = Field(default_factory=list)
    recheck_passed: bool = True

    @model_validator(mode="after")
    def _sync_entities(self) -> "SuggestionDetails":
        if not self.preserved_entities and self.entities_preserved:
            self.preserved_entities = list(self.entities_preserved)
        elif not self.entities_preserved and self.preserved_entities:
            self.entities_preserved = list(self.preserved_entities)
        return self


class FlagDraft(BaseModel):
    finding_type: FindingType
    state: str
    passage: str
    location: str
    explanation: str
    why_it_matters: str
    guideline_ref: Optional[GuidelineRef] = None
    guideline_refs: Optional[List[GuidelineRef]] = Field(default_factory=list)
    external_sources: List[ExternalSource] = Field(default_factory=list)
    uncertainty_note: Optional[str] = None
    suggested_correction: Optional[str] = None
    origin: Literal["module", "fixture", "error"] = "module"
    status: str = "open"
    comments: List[str] = Field(default_factory=list)

    # Evidence-first structured additions
    evidence_mode: Optional[EvidenceMode] = None
    internal_evidence: List[InternalEvidence] = Field(default_factory=list)
    external_evidence: List[ExternalEvidence] = Field(default_factory=list)
    exact_violated_passage: Optional[str] = None
    flagged_span: Optional[FlaggedSpan] = None
    suggestion: Optional[SuggestionDetails] = None

    @model_validator(mode="after")
    def validate_and_sync(self):
        if self.finding_type == "brand" and self.state not in BRAND_STATES:
            raise ValueError(f"State '{self.state}' is invalid for finding_type 'brand'. Must be one of {BRAND_STATES}")
        if self.finding_type == "claim" and self.state not in CLAIM_STATES:
            raise ValueError(f"State '{self.state}' is invalid for finding_type 'claim'. Must be one of {CLAIM_STATES}")

        # Sync guideline_ref and guideline_refs
        if self.guideline_refs and not self.guideline_ref:
            self.guideline_ref = self.guideline_refs[0]
        elif self.guideline_ref and not self.guideline_refs:
            self.guideline_refs = [self.guideline_ref]

        # Sync internal evidence
        if not self.internal_evidence and self.guideline_refs:
            self.internal_evidence = [
                InternalEvidence(
                    document=g.document,
                    document_id=g.document_id,
                    chunk_id=g.chunk_id,
                    section=g.section,
                    page_number=g.page_number,
                    similarity=g.similarity,
                    retrieved_chunk_text=g.excerpt,
                    exact_violated_passage=g.exact_violated_passage or self.exact_violated_passage,
                )
                for g in self.guideline_refs
            ]
        elif self.internal_evidence and not self.guideline_refs:
            self.guideline_refs = [
                GuidelineRef(
                    document=ie.document,
                    passage_ref=" — ".join(p for p in [ie.section, f"Page {ie.page_number}" if ie.page_number is not None else None] if p) or ie.passage_ref or "General",
                    excerpt=ie.excerpt or ie.retrieved_chunk_text or "",
                    document_id=ie.document_id,
                    chunk_id=ie.chunk_id,
                    section=ie.section,
                    page_number=ie.page_number,
                    similarity=ie.similarity,
                    exact_violated_passage=ie.exact_violated_passage,
                )
                for ie in self.internal_evidence
            ]
            self.guideline_ref = self.guideline_refs[0]

        # Sync external evidence
        if not self.external_evidence and self.external_sources:
            self.external_evidence = [
                ExternalEvidence(
                    title=s.title,
                    url=s.url,
                    domain=s.domain,
                    published_date=s.published_date,
                    retrieved_at=s.retrieved_at,
                    excerpt=s.excerpt,
                    evidence_quality=s.evidence_quality or "reliable",
                    status=s.status or "ok",
                    error_reason=s.error_reason,
                )
                for s in self.external_sources
            ]
        elif self.external_evidence and not self.external_sources:
            self.external_sources = [
                ExternalSource(
                    url=ee.url,
                    excerpt=ee.excerpt,
                    title=ee.title,
                    domain=ee.domain,
                    published_date=ee.published_date,
                    retrieved_at=ee.retrieved_at,
                    evidence_quality=ee.evidence_quality,
                    status=ee.status,
                    error_reason=ee.error_reason,
                )
                for ee in self.external_evidence
            ]

        # Sync exact_violated_passage
        if not self.exact_violated_passage and self.internal_evidence:
            first_ev = self.internal_evidence[0]
            if first_ev.exact_violated_passage:
                self.exact_violated_passage = first_ev.exact_violated_passage
        elif self.exact_violated_passage and self.internal_evidence:
            for ie in self.internal_evidence:
                if not ie.exact_violated_passage:
                    ie.exact_violated_passage = self.exact_violated_passage

        # Sync flagged_span
        if not self.flagged_span and self.passage:
            self.flagged_span = FlaggedSpan(
                exact_text=self.passage,
                surrounding_passage=self.passage,
                location_label=self.location,
            )

        # Sync suggestions
        if not self.suggestion and self.suggested_correction:
            self.suggestion = SuggestionDetails(
                suggested_replacement=self.suggested_correction
            )
        elif self.suggestion and not self.suggested_correction:
            self.suggested_correction = self.suggestion.suggested_replacement

        # Determine evidence_mode
        if not self.evidence_mode:
            has_int = bool(self.internal_evidence)
            has_ext = bool(self.external_evidence)
            if self.state in ("insufficient_evidence", "unclear") and not has_int and not has_ext:
                self.evidence_mode = "insufficient_evidence"
            elif has_int and has_ext:
                self.evidence_mode = "combined"
            elif has_int:
                self.evidence_mode = "internal_only"
            elif has_ext:
                self.evidence_mode = "external_only"
            else:
                self.evidence_mode = "insufficient_evidence"

        return self


class Flag(FlagDraft):
    id: str
    submission_id: str
    version: int = 1
    needs_human: bool = False
    created_at: str


class DegradedModule(BaseModel):
    module: str
    error: str


class Submission(BaseModel):
    id: str
    content_type: str
    role: str
    status: SubmissionStateType = "draft"
    version: int = 1
    title: Optional[str] = None
    audience: Optional[str] = None
    channel: Optional[str] = None
    context: Optional[str] = None
    text: Optional[str] = None
    file_name: Optional[str] = None
    file_mime: Optional[str] = None
    file_size: Optional[int] = None
    file_bytes: Optional[bytes] = Field(default=None, exclude=True)
    created_at: str
    updated_at: str


class SubmissionListItem(BaseModel):
    id: str
    content_type: str
    status: str
    version: int
    title: Optional[str] = None
    audience: Optional[str] = None
    channel: Optional[str] = None
    context: Optional[str] = None
    created_at: str
    flag_count: int
    needs_human_count: int


class VersionInfo(BaseModel):
    version: int
    flag_count: int
    needs_human_count: int


class Decision(BaseModel):
    id: str
    submission_id: str
    role: str
    decision: DecisionAction
    comment: Optional[str] = None
    version: int
    created_at: str


class Comment(BaseModel):
    id: str
    submission_id: str
    role: str
    text: str
    version: int
    created_at: str


class AuditEvent(BaseModel):
    actor_role: str
    action: str
    detail: str
    timestamp: str
    actor: Optional[str] = None

    @model_validator(mode="after")
    def set_default_actor(self):
        if not self.actor:
            self.actor = self.actor_role
        return self


class CheckRequest(BaseModel):
    role: str


class DecisionRequest(BaseModel):
    role: str
    decision: str
    comment: Optional[str] = None


class CommentRequest(BaseModel):
    role: str
    text: str


class ResolutionRequest(BaseModel):
    action: Literal["accept", "dismiss"]
    comment: Optional[str] = None
    role: Optional[str] = "creator"


class RecheckRequest(BaseModel):
    role: Optional[str] = "creator"


class RecheckResponse(BaseModel):
    new_flags: List[Flag]
    original_flag_gone: bool
    has_needs_human: bool


class CheckResponse(BaseModel):
    submission: Submission
    flags: List[Flag]
    degraded_modules: List[DegradedModule] = Field(default_factory=list)


class SubmissionDetailResponse(BaseModel):
    submission: Submission
    flags: List[Flag]
    comments: List[Comment]
    decisions: List[Decision]


class RecurringInsightsResponse(BaseModel):
    top_guidelines: List[Dict[str, object]]
    state_counts: Dict[str, int]
    total_flags: int
    governance_insights: Optional[Dict[str, Any]] = None


class DisclosureItem(BaseModel):
    name: str
    service_id: str
    description: str
    enabled: bool


class DisclosuresResponse(BaseModel):
    external_services: List[DisclosureItem]
    services_enabled: List[str]
    human_in_the_loop_notice: str


class ContrastResponse(BaseModel):
    fg: str
    bg: str
    contrast_ratio: float
    aa_normal: bool
    aa_large: bool
    aaa_normal: bool
