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


class ExternalSource(BaseModel):
    url: str
    excerpt: str


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

    @model_validator(mode="after")
    def validate_and_sync(self):
        if self.finding_type == "brand" and self.state not in BRAND_STATES:
            raise ValueError(f"State '{self.state}' is invalid for finding_type 'brand'. Must be one of {BRAND_STATES}")
        if self.finding_type == "claim" and self.state not in CLAIM_STATES:
            raise ValueError(f"State '{self.state}' is invalid for finding_type 'claim'. Must be one of {CLAIM_STATES}")
        if self.guideline_refs and not self.guideline_ref:
            self.guideline_ref = self.guideline_refs[0]
        elif self.guideline_ref and not self.guideline_refs:
            self.guideline_refs = [self.guideline_ref]
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
