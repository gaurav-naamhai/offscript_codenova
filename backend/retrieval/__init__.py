"""Public exports for the retrieval package (imported by FastAPI & Sera's layer)."""

from retrieval.brand_rag import (
    deactivate_brand_doc,
    embed_query,
    embed_texts,
    ingest_brand_doc,
    retrieve_guidelines,
    search_brand_rag,
)
from retrieval.chunker import chunk_pages
from retrieval.extractor import extract_document, extract_from_payload
from retrieval.external_search import verify_claim_externally, verify_claims
from retrieval.schemas import (
    BrandChunkMatch,
    BrandDocumentRecord,
    ContentPayload,
    DocumentChunk,
    ExternalEvidenceItem,
    ExternalSource,
    ExtractedDocument,
    FlagDraft,
    GuidelineRef,
    PageText,
)

__all__ = [
    "extract_document",
    "extract_from_payload",
    "chunk_pages",
    "embed_texts",
    "embed_query",
    "ingest_brand_doc",
    "deactivate_brand_doc",
    "search_brand_rag",
    "retrieve_guidelines",
    "verify_claim_externally",
    "verify_claims",
    "PageText",
    "ExtractedDocument",
    "DocumentChunk",
    "BrandDocumentRecord",
    "BrandChunkMatch",
    "ExternalEvidenceItem",
    "ContentPayload",
    "GuidelineRef",
    "ExternalSource",
    "FlagDraft",
]
