"""Pydantic models defining the input/output contract for Gaurav & Sera.

Includes both:
1. Detailed Retrieval & Evidence schemas (extraction, chunking, RAG, external evidence).
2. Exact plugin schemas matching `backend/app/models.py` in `offscript_codenova`
   (`ContentPayload`, `GuidelineRef`, `ExternalSource`, `FlagDraft`).
"""

from dataclasses import dataclass
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# 1. Core Retrieval & Evidence Models (Ken's module)
# ---------------------------------------------------------------------------


class PageText(BaseModel):
    """Extracted text from a single page or image."""

    page_number: int = Field(..., description="1-based page number")
    text: str = Field(..., description="Cleaned text extracted from this page")
    extraction_method: Literal["digital_pdf", "ocr_gemini", "plain_text"] = "digital_pdf"


class ExtractedDocument(BaseModel):
    """Structured result returned by `extract_document()`."""

    filename: str
    content_type: Literal["pdf", "image", "text"]
    page_count: int
    pages: List[PageText] = Field(default_factory=list)
    full_text: str = ""


class DocumentChunk(BaseModel):
    """A single chunk ready to be embedded and stored in `brand_chunks`."""

    chunk_index: int
    page_number: int
    section: Optional[str] = None
    content: str


class BrandDocumentRecord(BaseModel):
    """Represents a row in the `brand_documents` table."""

    id: str
    title: str
    category: str = "guideline"
    version: str = "1.0"
    is_active: bool = True
    source_filename: Optional[str] = None
    storage_path: Optional[str] = None
    chunks_count: int = 0


class BrandChunkMatch(BaseModel):
    """A matched chunk returned from Supabase `match_brand_chunks` RPC."""

    chunk_id: str
    document_id: str
    doc_title: str
    category: str
    version: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    content: str
    similarity: float


class ExternalEvidenceItem(BaseModel):
    """Structured external evidence returned by `verify_claim_externally()`."""

    query: str
    url: str
    title: Optional[str] = None
    domain: str = ""
    published_date: Optional[str] = None
    retrieved_at: str
    excerpt: str = ""
    status: Literal["ok", "unavailable"] = "ok"
    error_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# 2. Backend Plugin Contract Models (compatible with `backend/app/models.py`)
# ---------------------------------------------------------------------------

FindingType = Literal["brand", "claim"]
BRAND_STATES = {"aligned", "potential_issue", "unclear"}
CLAIM_STATES = {"supported", "contradicted", "insufficient_evidence"}


@dataclass
class ContentPayload:
    content_type: str  # 'text' | 'image' | 'pdf'
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
            raise ValueError(
                f"State '{self.state}' is invalid for finding_type 'brand'. Must be one of {BRAND_STATES}"
            )
        if self.finding_type == "claim" and self.state not in CLAIM_STATES:
            raise ValueError(
                f"State '{self.state}' is invalid for finding_type 'claim'. Must be one of {CLAIM_STATES}"
            )
        if self.guideline_refs and not self.guideline_ref:
            self.guideline_ref = self.guideline_refs[0]
        elif self.guideline_ref and not self.guideline_refs:
            self.guideline_refs = [self.guideline_ref]
        return self
