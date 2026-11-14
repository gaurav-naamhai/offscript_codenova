"""Brand Knowledge Base ingestion, versioning, and Supabase pgvector RAG search."""

import logging
import time
from typing import List, Optional
from google.genai import types

from retrieval.chunker import chunk_pages
from retrieval.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    get_genai_client,
    get_supabase_client,
)
from retrieval.extractor import extract_document, extract_from_payload
from retrieval.schemas import (
    BrandChunkMatch,
    BrandDocumentRecord,
    ContentPayload,
    GuidelineRef,
)

logger = logging.getLogger(__name__)

# Fallback rules returned if Supabase `brand_chunks` has no ingested docs yet
DEFAULT_GUIDELINES: List[GuidelineRef] = [
    GuidelineRef(
        document="Brand Tone and Claim Guidelines v2.1",
        passage_ref="Section 3.2 (Page 1)",
        excerpt="All factual and statistical performance claims must be substantiated with verifiable sources.",
        source_reference="Brand Tone and Claim Guidelines v2.1",
    ),
    GuidelineRef(
        document="Brand Tone and Claim Guidelines v2.1",
        passage_ref="Section 3.4 (Page 1)",
        excerpt="Avoid unverified superlatives and unsubstantiated market ranking declarations.",
        source_reference="Brand Tone and Claim Guidelines v2.1",
    ),
    GuidelineRef(
        document="Commercial Compliance Standard",
        passage_ref="Section 2.1 (Page 1)",
        excerpt="Guarantees and SLA promises require explicit limitations and benchmark disclosures.",
        source_reference="Commercial Compliance Standard",
    ),
    GuidelineRef(
        document="Visual and Brand Identity Playbook",
        passage_ref="Section 1.1 (Page 1)",
        excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.",
        source_reference="Visual and Brand Identity Playbook",
    ),
    GuidelineRef(
        document="Visual and Brand Identity Playbook",
        passage_ref="Section 1.3 (Page 1)",
        excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.",
        source_reference="Visual and Brand Identity Playbook",
    ),
]


def embed_texts(texts: List[str], batch_size: int = 20) -> List[List[float]]:
    """Generate 768-dimensional Gemini embeddings in batches with retry on rate limits."""
    if not texts:
        return []

    client = get_genai_client()
    all_embeddings: List[List[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        for attempt in range(3):
            try:
                res = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        output_dimensionality=EMBEDDING_DIM,
                        http_options={"api_version": "v1beta"},
                    ),
                )
                for emb in res.embeddings:
                    all_embeddings.append(list(emb.values))
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                logger.warning("Embedding batch retry %d after error: %s", attempt + 1, exc)
                time.sleep(2.0 * (attempt + 1))

    return all_embeddings


def embed_query(query: str) -> List[float]:
    """Generate a single 768-dimensional embedding vector for a search query."""
    vectors = embed_texts([query.strip()], batch_size=1)
    if not vectors:
        raise RuntimeError("Failed to generate query embedding.")
    return vectors[0]


def list_brand_docs(include_inactive: bool = False) -> List[dict]:
    """List brand documents stored in Supabase `brand_documents`."""
    sb = get_supabase_client()
    query = sb.table("brand_documents").select("*").order("created_at", desc=True)
    if not include_inactive:
        query = query.eq("is_active", True)
    res = query.execute()
    return res.data or []


def deactivate_brand_doc(
    document_id: Optional[str] = None,
    title: Optional[str] = None,
) -> int:
    """Mark outdated brand documents as `is_active = False` in Supabase."""
    sb = get_supabase_client()
    query = sb.table("brand_documents").update({"is_active": False})
    if document_id:
        query = query.eq("id", document_id)
    elif title:
        query = query.eq("title", title).eq("is_active", True)
    else:
        raise ValueError("Provide either document_id or title to deactivate.")

    res = query.execute()
    return len(res.data or [])


def ingest_brand_doc(
    file_bytes: bytes,
    filename: str,
    title: str,
    category: str = "guideline",
    version: str = "1.0",
    storage_path: Optional[str] = None,
    deactivate_previous_versions: bool = True,
) -> BrandDocumentRecord:
    """Extract, chunk, embed, and store a brand document in Supabase (`brand_documents` + `brand_chunks`)."""
    sb = get_supabase_client()

    # 1. Optionally mark earlier active versions of the same document title as inactive
    if deactivate_previous_versions:
        try:
            deactivate_brand_doc(title=title)
        except Exception as exc:
            logger.warning("Could not deactivate previous versions for '%s': %s", title, exc)

    # 2. Extract pages and split into overlapping chunks
    extracted = extract_document(file_bytes=file_bytes, filename=filename)
    chunks = chunk_pages(extracted.pages)
    if not chunks:
        raise ValueError(f"No readable text chunks extracted from '{filename}'.")

    # 3. Insert parent row in `brand_documents`
    doc_insert = (
        sb.table("brand_documents")
        .insert(
            {
                "title": title,
                "category": category,
                "version": version,
                "is_active": True,
                "source_filename": filename,
                "storage_path": storage_path,
            }
        )
        .execute()
    )
    if not doc_insert.data:
        raise RuntimeError("Failed to insert row into brand_documents.")
    doc_row = doc_insert.data[0]
    doc_id: str = doc_row["id"]

    # 4. Generate 768-dim embeddings for all chunks
    vectors = embed_texts([c.content for c in chunks])

    # 5. Insert child rows into `brand_chunks`
    chunk_rows = [
        {
            "document_id": doc_id,
            "content": chunk.content,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
            "embedding": vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]
    sb.table("brand_chunks").insert(chunk_rows).execute()

    return BrandDocumentRecord(
        id=doc_id,
        title=title,
        category=category,
        version=version,
        is_active=True,
        source_filename=filename,
        storage_path=storage_path,
        chunks_count=len(chunk_rows),
    )


def search_brand_rag(
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
) -> List[BrandChunkMatch]:
    """Search active brand chunks in Supabase `pgvector` using `match_brand_chunks` RPC."""
    if not query or not query.strip():
        return []

    sb = get_supabase_client()
    query_vec = embed_query(query)

    rpc_params = {
        "query_embedding": query_vec,
        "match_count": top_k,
        "filter_category": category,
    }
    res = sb.rpc("match_brand_chunks", rpc_params).execute()
    rows = res.data or []
    return [BrandChunkMatch(**row) for row in rows]


def retrieve_guidelines(
    content: ContentPayload,
    top_k: int = 5,
) -> List[GuidelineRef]:
    """Gaurav's plugin hook (`backend/app/plugins/retrieval.py`):
    Retrieve relevant brand and claim guidelines for the submitted `ContentPayload`.
    """
    try:
        query_text = extract_from_payload(content)
        if not query_text:
            query_text = "brand tone terminology claims visual compliance guidelines"
        # Cap query length to stay well inside embedding token limit
        matches = search_brand_rag(query=query_text[:3000], top_k=top_k)
        if not matches:
            return list(DEFAULT_GUIDELINES)

        guidelines: List[GuidelineRef] = []
        for m in matches:
            loc_parts = []
            if m.section:
                loc_parts.append(m.section)
            if m.page_number is not None:
                loc_parts.append(f"Page {m.page_number}")
            passage_ref = " — ".join(loc_parts) if loc_parts else "General"
            doc_label = f"{m.doc_title} (v{m.version})" if m.version else m.doc_title

            guidelines.append(
                GuidelineRef(
                    document=doc_label,
                    passage_ref=passage_ref,
                    excerpt=m.content,
                    source_reference=f"{doc_label} [{m.category}]",
                    document_id=m.document_id,
                    chunk_id=m.chunk_id,
                    section=m.section,
                    page_number=m.page_number,
                    similarity=round(m.similarity, 4) if m.similarity is not None else None,
                )
            )
        return guidelines
    except Exception as exc:
        logger.warning("RAG retrieval fell back to default guidelines due to: %s", exc)
        return list(DEFAULT_GUIDELINES)
