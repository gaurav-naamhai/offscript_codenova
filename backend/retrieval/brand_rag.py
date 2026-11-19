"""Brand Knowledge Base ingestion, org isolation, versioning, and hybrid Supabase pgvector RAG search."""

from datetime import datetime, timezone
import logging
import math
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from google.genai import types

from retrieval.chunker import (
    classify_rule_category,
    chunk_pages,
    compile_brand_constitution,
    extract_keywords,
)
from retrieval.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    GEMINI_API_KEY,
    SUPABASE_KEY,
    SUPABASE_URL,
    get_genai_client,
    get_supabase_client,
)
from retrieval.extractor import extract_document, extract_from_payload
from retrieval.schemas import (
    BrandChunkMatch,
    BrandDocumentRecord,
    ContentPayload,
    DocumentChunk,
    GuidelineRef,
    PageText,
)

logger = logging.getLogger(__name__)

# Fallback rules returned ONLY when neither org docs nor Supabase credentials exist (offline unit tests)
DEFAULT_GUIDELINES: List[GuidelineRef] = [
    GuidelineRef(
        document="Brand Tone and Claim Guidelines v2.1",
        passage_ref="Section 3.2 (Page 1)",
        excerpt="All factual and statistical performance claims must be substantiated with verifiable sources.",
        source_reference="Brand Tone and Claim Guidelines v2.1",
        category="claim_policy",
    ),
    GuidelineRef(
        document="Brand Tone and Claim Guidelines v2.1",
        passage_ref="Section 3.4 (Page 1)",
        excerpt="Avoid unverified superlatives and unsubstantiated market ranking declarations.",
        source_reference="Brand Tone and Claim Guidelines v2.1",
        category="claim_policy",
    ),
    GuidelineRef(
        document="Commercial Compliance Standard",
        passage_ref="Section 2.1 (Page 1)",
        excerpt="Guarantees and SLA promises require explicit limitations and benchmark disclosures.",
        source_reference="Commercial Compliance Standard",
        category="legal",
    ),
    GuidelineRef(
        document="Visual and Brand Identity Playbook",
        passage_ref="Section 1.1 (Page 1)",
        excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.",
        source_reference="Visual and Brand Identity Playbook",
        category="tone",
    ),
    GuidelineRef(
        document="Visual and Brand Identity Playbook",
        passage_ref="Section 1.3 (Page 1)",
        excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.",
        source_reference="Visual and Brand Identity Playbook",
        category="terminology",
    ),
]

# Thread-safe local store used automatically when Supabase credentials are unavailable (offline/unit tests)
_LOCAL_LOCK = threading.Lock()
_LOCAL_DOCS: Dict[str, Dict[str, Any]] = {}
_LOCAL_CHUNKS: Dict[str, List[Dict[str, Any]]] = {}


def _supabase_configured() -> bool:
    import os

    url = (os.getenv("SUPABASE_URL", "") or SUPABASE_URL).strip()
    key = (
        os.getenv("SUPABASE_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        or SUPABASE_KEY
    )
    return bool(url and key)


def _gemini_configured() -> bool:
    import os

    return bool((os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY).strip())


def clear_local_brand_store() -> None:
    """Reset the local in-memory brand store (used in unit tests)."""
    with _LOCAL_LOCK:
        _LOCAL_DOCS.clear()
        _LOCAL_CHUNKS.clear()


# ---------------------------------------------------------------------------
# Organisation Metadata Encoding & Isolation Helpers
# ---------------------------------------------------------------------------


def _encode_storage_meta(
    org_id: str,
    brand_name: Optional[str] = None,
    previous_version_id: Optional[str] = None,
    raw_path: Optional[str] = None,
) -> str:
    clean_org = (org_id or "inkloom").strip().lower()
    clean_brand = (brand_name or clean_org).strip().replace("|", " ")
    prev = (previous_version_id or "").strip().replace("|", "")
    tail = (raw_path or "").strip()
    return f"org:{clean_org}|brand:{clean_brand}|prev:{prev}|{tail}"


def _infer_org_from_doc_row(row: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """Extract (org_id, brand_name, previous_version_id) from storage_path or infer safely for legacy rows."""
    storage_path = (row.get("storage_path") or "").strip()
    if storage_path.startswith("org:"):
        org_id = "inkloom"
        brand_name = ""
        prev_id: Optional[str] = None
        for part in storage_path.split("|"):
            if part.startswith("org:"):
                org_id = part[4:].strip().lower() or "inkloom"
            elif part.startswith("brand:"):
                brand_name = part[6:].strip()
            elif part.startswith("prev:"):
                val = part[5:].strip()
                prev_id = val or None
        return org_id, brand_name or org_id, prev_id

    if row.get("org_id"):
        return (
            str(row["org_id"]).strip().lower(),
            str(row.get("brand_name") or row["org_id"]).strip(),
            row.get("previous_version_id"),
        )

    # Legacy pre-round-2 rows uploaded before org tagging
    haystack = f"{row.get('title', '')} {row.get('source_filename', '')} {row.get('category', '')}".lower()
    if "brightleaf" in haystack or "bright leaf" in haystack:
        return "brightleaf", "BrightLeaf", None
    if "nike" in haystack or row.get("title", "").strip().lower() in ("identity", "identitty"):
        return "nike", "Nike", None
    return "inkloom", "Inkloom AI", None


def _enrich_doc_row(row: Dict[str, Any]) -> Dict[str, Any]:
    org_id, brand_name, prev_id = _infer_org_from_doc_row(row)
    enriched = dict(row)
    enriched["org_id"] = org_id
    enriched["brand_name"] = brand_name
    enriched["previous_version_id"] = prev_id
    return enriched


def _bump_version_string(version: str) -> str:
    """Increment semantic or decimal version string cleanly (e.g. '1.0' -> '1.1', '2' -> '2.1')."""
    raw = (version or "1.0").strip().lstrip("vV")
    parts = raw.split(".")
    if parts and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{raw}.1"


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


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
                time.sleep(1.5 * (attempt + 1))

    return all_embeddings


def embed_query(query: str) -> List[float]:
    """Generate a single 768-dimensional embedding vector for a search query."""
    vectors = embed_texts([query.strip()], batch_size=1)
    if not vectors:
        raise RuntimeError("Failed to generate query embedding.")
    return vectors[0]


# ---------------------------------------------------------------------------
# Brand Knowledge Base CRUD & Versioning
# ---------------------------------------------------------------------------


def list_brand_docs(
    include_inactive: bool = False,
    org_id: Optional[str] = None,
) -> List[dict]:
    """List brand documents scoped to `org_id` (from Supabase or local store when offline)."""
    target_org = org_id.strip().lower() if org_id else None

    if not _supabase_configured():
        with _LOCAL_LOCK:
            docs = [dict(d) for d in _LOCAL_DOCS.values()]
        if not include_inactive:
            docs = [d for d in docs if d.get("is_active", True)]
        if target_org:
            docs = [d for d in docs if d.get("org_id", "inkloom") == target_org]
        return sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)

    sb = get_supabase_client()
    query = sb.table("brand_documents").select("*").order("created_at", desc=True)
    if not include_inactive:
        query = query.eq("is_active", True)
    res = query.execute()
    rows = [_enrich_doc_row(r) for r in (res.data or [])]
    if target_org:
        rows = [r for r in rows if r["org_id"] == target_org]
    return rows


def get_brand_doc_by_id(document_id: str, org_id: Optional[str] = None) -> Optional[dict]:
    """Fetch a single brand document row by ID, verifying optional org ownership."""
    target_org = org_id.strip().lower() if org_id else None
    if not _supabase_configured():
        with _LOCAL_LOCK:
            row = _LOCAL_DOCS.get(document_id)
            if not row:
                return None
            if target_org and row.get("org_id", "inkloom") != target_org:
                return None
            return dict(row)

    sb = get_supabase_client()
    res = sb.table("brand_documents").select("*").eq("id", document_id).limit(1).execute()
    if not res.data:
        return None
    enriched = _enrich_doc_row(res.data[0])
    if target_org and enriched["org_id"] != target_org:
        return None
    return enriched


def list_brand_doc_versions(
    document_id_or_title: str,
    org_id: Optional[str] = None,
) -> List[dict]:
    """List all versions (active + archived previous versions) for a brand document title/ID."""
    all_docs = list_brand_docs(include_inactive=True, org_id=org_id)
    target_title = document_id_or_title.strip().lower()
    for d in all_docs:
        if d.get("id") == document_id_or_title:
            target_title = (d.get("title") or "").strip().lower()
            break
    matched = [
        d for d in all_docs if (d.get("title") or "").strip().lower() == target_title
    ]
    return sorted(matched, key=lambda d: (d.get("is_active", False), d.get("created_at", "")), reverse=True)


def deactivate_brand_doc(
    document_id: Optional[str] = None,
    title: Optional[str] = None,
    org_id: Optional[str] = None,
) -> int:
    """Mark outdated brand documents as `is_active = False` scoped to org_id."""
    target_org = org_id.strip().lower() if org_id else None

    if not _supabase_configured():
        count = 0
        with _LOCAL_LOCK:
            for doc_id, row in _LOCAL_DOCS.items():
                if target_org and row.get("org_id") != target_org:
                    continue
                if document_id and doc_id == document_id:
                    row["is_active"] = False
                    count += 1
                elif title and (row.get("title") or "").lower() == title.lower() and row.get("is_active", True):
                    row["is_active"] = False
                    count += 1
        return count

    sb = get_supabase_client()
    if document_id:
        existing = get_brand_doc_by_id(document_id, org_id=target_org)
        if not existing:
            return 0
        res = sb.table("brand_documents").update({"is_active": False}).eq("id", document_id).execute()
        return len(res.data or [])

    if title:
        docs = list_brand_docs(include_inactive=False, org_id=target_org)
        targets = [d["id"] for d in docs if (d.get("title") or "").lower() == title.lower()]
        count = 0
        for tid in targets:
            res = sb.table("brand_documents").update({"is_active": False}).eq("id", tid).execute()
            count += len(res.data or [])
        return count

    raise ValueError("Provide either document_id or title to deactivate.")


def get_brand_doc_chunks(document_id: str) -> List[dict]:
    """Fetch ordered chunks belonging to a specific brand document."""
    if not _supabase_configured():
        with _LOCAL_LOCK:
            return [dict(c) for c in _LOCAL_CHUNKS.get(document_id, [])]

    sb = get_supabase_client()
    res = (
        sb.table("brand_chunks")
        .select("id,document_id,content,page_number,section,chunk_index")
        .eq("document_id", document_id)
        .order("chunk_index")
        .execute()
    )
    return res.data or []


def get_org_active_chunks(org_id: str) -> List[dict]:
    """Fetch all active brand chunks for a single organisation with document metadata attached."""
    docs = list_brand_docs(include_inactive=False, org_id=org_id)
    if not docs:
        return []

    doc_map = {d["id"]: d for d in docs}
    all_chunks: List[dict] = []

    if not _supabase_configured():
        with _LOCAL_LOCK:
            for doc_id, d in doc_map.items():
                for c in _LOCAL_CHUNKS.get(doc_id, []):
                    row = dict(c)
                    row["doc_title"] = d.get("title", "Brand Document")
                    row["doc_version"] = d.get("version", "1.0")
                    row["doc_category"] = d.get("category", "guideline")
                    row["org_id"] = d.get("org_id", org_id)
                    all_chunks.append(row)
        return all_chunks

    sb = get_supabase_client()
    doc_ids = list(doc_map.keys())
    res = (
        sb.table("brand_chunks")
        .select("id,document_id,content,page_number,section,chunk_index")
        .in_("document_id", doc_ids)
        .order("chunk_index")
        .execute()
    )
    for row in res.data or []:
        d = doc_map.get(row["document_id"], {})
        enriched = dict(row)
        enriched["doc_title"] = d.get("title", "Brand Document")
        enriched["doc_version"] = d.get("version", "1.0")
        enriched["doc_category"] = d.get("category", "guideline")
        enriched["org_id"] = d.get("org_id", org_id)
        enriched["rule_category"] = classify_rule_category(row.get("content", ""), row.get("section"))
        all_chunks.append(enriched)
    return all_chunks


def ingest_brand_doc(
    file_bytes: bytes,
    filename: str,
    title: str,
    category: str = "guideline",
    version: str = "1.0",
    storage_path: Optional[str] = None,
    deactivate_previous_versions: bool = True,
    org_id: str = "inkloom",
    brand_name: Optional[str] = None,
    previous_version_id: Optional[str] = None,
) -> BrandDocumentRecord:
    """Extract, chunk, compile Brand Constitution, embed, and store a brand document scoped to `org_id`."""
    clean_org = (org_id or "inkloom").strip().lower()
    clean_brand = (brand_name or clean_org).strip()

    # 1. Mark earlier active versions of the same document title within the SAME org as inactive
    if deactivate_previous_versions:
        try:
            existing = list_brand_docs(include_inactive=False, org_id=clean_org)
            for doc in existing:
                if (doc.get("title") or "").strip().lower() == title.strip().lower():
                    if not previous_version_id:
                        previous_version_id = doc.get("id")
                    deactivate_brand_doc(document_id=doc["id"], org_id=clean_org)
        except Exception as exc:
            logger.warning("Could not deactivate previous versions for '%s': %s", title, exc)

    # 2. Extract pages, split into rule-aware chunks, and compile Brand Constitution
    extracted = extract_document(file_bytes=file_bytes, filename=filename)
    chunks = chunk_pages(extracted.pages)
    if not chunks:
        raise ValueError(f"No readable text chunks extracted from '{filename}'.")

    constitution = compile_brand_constitution(extracted.pages, title=title)
    encoded_path = _encode_storage_meta(
        org_id=clean_org,
        brand_name=clean_brand,
        previous_version_id=previous_version_id,
        raw_path=storage_path,
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    # Offline local store fallback (when Supabase credentials are not set)
    if not _supabase_configured():
        doc_id = str(uuid.uuid4())
        doc_row = {
            "id": doc_id,
            "title": title,
            "category": category,
            "version": version,
            "is_active": True,
            "source_filename": filename,
            "storage_path": encoded_path,
            "org_id": clean_org,
            "brand_name": clean_brand,
            "previous_version_id": previous_version_id,
            "constitution": constitution,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        chunk_rows = [
            {
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "content": c.content,
                "page_number": c.page_number,
                "section": c.section,
                "chunk_index": c.chunk_index,
                "rule_category": c.rule_category,
                "keywords": c.keywords,
                "contains_expiry": c.contains_expiry,
                "expiry_hint": c.expiry_hint,
            }
            for c in chunks
        ]
        with _LOCAL_LOCK:
            _LOCAL_DOCS[doc_id] = doc_row
            _LOCAL_CHUNKS[doc_id] = chunk_rows
        return BrandDocumentRecord(
            id=doc_id,
            title=title,
            category=category,
            version=version,
            is_active=True,
            source_filename=filename,
            storage_path=encoded_path,
            chunks_count=len(chunk_rows),
            org_id=clean_org,
            brand_name=clean_brand,
            previous_version_id=previous_version_id,
            constitution=constitution,
            created_at=now_iso,
        )

    # Live Supabase persistence
    sb = get_supabase_client()
    doc_insert = (
        sb.table("brand_documents")
        .insert(
            {
                "title": title,
                "category": category,
                "version": version,
                "is_active": True,
                "source_filename": filename,
                "storage_path": encoded_path,
            }
        )
        .execute()
    )
    if not doc_insert.data:
        raise RuntimeError("Failed to insert row into brand_documents.")
    doc_row = doc_insert.data[0]
    doc_id = doc_row["id"]

    vectors = embed_texts([c.content for c in chunks])
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
        storage_path=encoded_path,
        chunks_count=len(chunk_rows),
        org_id=clean_org,
        brand_name=clean_brand,
        previous_version_id=previous_version_id,
        constitution=constitution,
        created_at=doc_row.get("created_at") or now_iso,
    )


def create_rectified_brand_doc_version(
    source_doc_id: str,
    target_chunk_id: str,
    new_chunk_text: str,
    org_id: str,
    approved_by: str = "manager",
) -> BrandDocumentRecord:
    """Publish a rectified version of a brand guideline document, archiving the previous version."""
    source_doc = get_brand_doc_by_id(source_doc_id, org_id=org_id)
    if not source_doc:
        raise ValueError(f"Brand document '{source_doc_id}' not found for organisation '{org_id}'.")

    existing_chunks = get_brand_doc_chunks(source_doc_id)
    if not existing_chunks:
        raise ValueError("Source brand document has no stored chunks to rectify.")

    new_version = _bump_version_string(str(source_doc.get("version") or "1.0"))
    clean_text = new_chunk_text.strip()
    if not clean_text:
        raise ValueError("Approved guideline wording cannot be empty.")

    updated_chunks: List[DocumentChunk] = []
    pages_for_const: List[PageText] = []
    replaced = False

    for idx, c in enumerate(existing_chunks):
        c_content = c.get("content", "")
        if str(c.get("id")) == str(target_chunk_id):
            c_content = clean_text
            replaced = True
        page_num = int(c.get("page_number") or 1)
        sec = c.get("section")
        updated_chunks.append(
            DocumentChunk(
                chunk_index=idx,
                page_number=page_num,
                section=sec,
                content=c_content,
                rule_category=classify_rule_category(c_content, sec),
                keywords=extract_keywords(c_content, sec),
            )
        )
        pages_for_const.append(PageText(page_number=page_num, text=c_content, extraction_method="plain_text"))

    if not replaced:
        raise ValueError(f"Target guideline chunk '{target_chunk_id}' was not found in document '{source_doc_id}'.")

    # Deactivate old version while keeping all its rows & chunks intact for history!
    deactivate_brand_doc(document_id=source_doc_id, org_id=org_id)

    title = source_doc["title"]
    category = source_doc.get("category") or "guideline"
    brand_name = source_doc.get("brand_name") or org_id
    filename = source_doc.get("source_filename") or f"{title}_v{new_version}.txt"
    constitution = compile_brand_constitution(pages_for_const, title=title)
    encoded_path = _encode_storage_meta(
        org_id=org_id,
        brand_name=brand_name,
        previous_version_id=source_doc_id,
        raw_path=f"rectified_by:{approved_by}",
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    if not _supabase_configured():
        new_doc_id = str(uuid.uuid4())
        new_doc_row = {
            "id": new_doc_id,
            "title": title,
            "category": category,
            "version": new_version,
            "is_active": True,
            "source_filename": filename,
            "storage_path": encoded_path,
            "org_id": org_id,
            "brand_name": brand_name,
            "previous_version_id": source_doc_id,
            "constitution": constitution,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        new_chunk_rows = [
            {
                "id": str(uuid.uuid4()),
                "document_id": new_doc_id,
                "content": ch.content,
                "page_number": ch.page_number,
                "section": ch.section,
                "chunk_index": ch.chunk_index,
                "rule_category": ch.rule_category,
                "keywords": ch.keywords,
            }
            for ch in updated_chunks
        ]
        with _LOCAL_LOCK:
            _LOCAL_DOCS[new_doc_id] = new_doc_row
            _LOCAL_CHUNKS[new_doc_id] = new_chunk_rows
        return BrandDocumentRecord(
            id=new_doc_id,
            title=title,
            category=category,
            version=new_version,
            is_active=True,
            source_filename=filename,
            storage_path=encoded_path,
            chunks_count=len(new_chunk_rows),
            org_id=org_id,
            brand_name=brand_name,
            previous_version_id=source_doc_id,
            constitution=constitution,
            created_at=now_iso,
        )

    sb = get_supabase_client()
    doc_insert = (
        sb.table("brand_documents")
        .insert(
            {
                "title": title,
                "category": category,
                "version": new_version,
                "is_active": True,
                "source_filename": filename,
                "storage_path": encoded_path,
            }
        )
        .execute()
    )
    if not doc_insert.data:
        raise RuntimeError("Failed to insert rectified brand document version.")
    new_doc_id = doc_insert.data[0]["id"]

    vectors = embed_texts([c.content for c in updated_chunks])
    chunk_rows = [
        {
            "document_id": new_doc_id,
            "content": c.content,
            "page_number": c.page_number,
            "section": c.section,
            "chunk_index": c.chunk_index,
            "embedding": vec,
        }
        for c, vec in zip(updated_chunks, vectors)
    ]
    sb.table("brand_chunks").insert(chunk_rows).execute()

    return BrandDocumentRecord(
        id=new_doc_id,
        title=title,
        category=category,
        version=new_version,
        is_active=True,
        source_filename=filename,
        storage_path=encoded_path,
        chunks_count=len(chunk_rows),
        org_id=org_id,
        brand_name=brand_name,
        previous_version_id=source_doc_id,
        constitution=constitution,
        created_at=doc_insert.data[0].get("created_at") or now_iso,
    )


def get_brand_constitution(org_id: str) -> Dict[str, Any]:
    """Aggregate a machine-readable Brand Constitution across all active docs for `org_id`."""
    docs = list_brand_docs(include_inactive=False, org_id=org_id)
    chunks = get_org_active_chunks(org_id=org_id)
    if not docs or not chunks:
        return {
            "org_id": org_id,
            "documents_count": len(docs),
            "approved_facts": [],
            "forbidden_terms": [],
            "preferred_terms": [],
            "tone_pillars": [],
            "brand_colors": [],
            "expiry_notices": [],
        }

    pages = [
        PageText(
            page_number=int(c.get("page_number") or 1),
            text=c.get("content", ""),
            extraction_method="plain_text",
        )
        for c in chunks
    ]
    compiled = compile_brand_constitution(pages, title=f"{org_id} Brand Constitution")
    compiled["org_id"] = org_id
    compiled["documents_count"] = len(docs)
    return compiled


# ---------------------------------------------------------------------------
# Hybrid Multi-Query Brand RAG Search
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9#%+.-]{2,}", (text or "").lower())


def _decompose_rag_queries(query_text: str, content_type: str = "text") -> List[str]:
    """Decompose a draft into focused sub-queries for claims, tone/terms, and visuals."""
    clean = (query_text or "").strip()
    if not clean:
        return ["brand tone terminology claims visual compliance guidelines"]

    queries: List[str] = [clean[:1500]]

    # 1. Factual / numeric / product claim sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", clean) if s.strip()]
    fact_sentences = [
        s for s in sentences
        if re.search(r"\d+|%|founded|certified|ingredient|organic|guarantee|sla|price|\$", s, re.IGNORECASE)
    ]
    if fact_sentences:
        queries.append("Approved facts and claims: " + " ".join(fact_sentences[:5])[:900])

    # 2. Visual / accessibility query for images or PDFs
    if content_type in ("image", "pdf"):
        queries.append("visual identity logo clearspace color palette hex typography contrast guidelines")

    return queries[:3]


def _score_lexical_match(query_tokens: Set[str], chunk_text: str, section: Optional[str]) -> Tuple[float, List[str]]:
    """Compute lexical overlap + exact quoted/forbidden term match bonus."""
    if not query_tokens or not chunk_text:
        return 0.0, []
    chunk_low = chunk_text.lower()
    chunk_tokens = set(_tokenize(f"{section or ''} {chunk_text}"))
    overlap = query_tokens.intersection(chunk_tokens)
    matched_terms = sorted(t for t in overlap if len(t) >= 4)[:8]

    # Exact quoted rules or forbidden phrases appearing directly in the query
    query_str = " ".join(query_tokens)
    exact_hits: List[str] = []
    for q in re.findall(r"[\"'“”]([^\"'“”]{3,40})[\"'“”]", chunk_low):
        if q.lower() in query_str:
            exact_hits.append(q)

    denom = max(4.0, min(len(query_tokens), 20) * 0.5)
    base_score = min(1.0, len(overlap) / denom)
    if exact_hits:
        base_score = min(1.0, base_score + 0.35)
        matched_terms = list(dict.fromkeys(exact_hits + matched_terms))[:8]
    return round(base_score, 4), matched_terms


def search_brand_rag(
    query: str,
    top_k: int = 6,
    category: Optional[str] = None,
    org_id: Optional[str] = None,
    brand_name: Optional[str] = None,
    content_type: str = "text",
) -> List[BrandChunkMatch]:
    """Hybrid multi-query RAG search strictly scoped to `org_id`'s active brand documents.

    Combines pgvector semantic similarity, lexical/exact-term matching, and category priority
    (boosting approved facts & terminology), rejecting low-relevance or cross-org noise.
    """
    if not query or not query.strip():
        return []

    target_org = org_id.strip().lower() if org_id else None
    active_docs = list_brand_docs(include_inactive=False, org_id=target_org)
    if target_org and not active_docs:
        # Strict org isolation: if an org has uploaded no guidelines, NEVER pull another org's rules
        return []

    allowed_doc_map = {d["id"]: d for d in active_docs}
    if category:
        cat_low = category.strip().lower()
        allowed_doc_map = {
            k: v for k, v in allowed_doc_map.items() if (v.get("category") or "").lower() == cat_low
        }
        if not allowed_doc_map:
            return []

    query_tokens = set(_tokenize(query))
    sub_queries = _decompose_rag_queries(query, content_type=content_type)

    # Candidate map keyed by chunk_id
    candidates: Dict[str, Dict[str, Any]] = {}

    # A. Semantic vector search via Supabase pgvector RPC (when configured)
    if _supabase_configured() and _gemini_configured():
        sb = get_supabase_client()
        fetch_count = max(top_k * 5, 24)
        for sub_q in sub_queries:
            try:
                query_vec = embed_query(sub_q)
                rpc_params = {
                    "query_embedding": query_vec,
                    "match_count": fetch_count,
                    "filter_category": category,
                }
                res = sb.rpc("match_brand_chunks", rpc_params).execute()
                for row in res.data or []:
                    doc_id = row.get("document_id")
                    if target_org and doc_id not in allowed_doc_map:
                        # Strictly drop cross-organisation chunks!
                        continue
                    cid = str(row.get("chunk_id") or row.get("id"))
                    sim = float(row.get("similarity") or 0.0)
                    prev = candidates.get(cid)
                    if not prev or sim > prev["vector_sim"]:
                        doc_meta = allowed_doc_map.get(doc_id, {})
                        candidates[cid] = {
                            "chunk_id": cid,
                            "document_id": doc_id,
                            "doc_title": row.get("doc_title") or doc_meta.get("title", "Brand Guideline"),
                            "category": row.get("category") or doc_meta.get("category", "guideline"),
                            "version": row.get("version") or doc_meta.get("version", "1.0"),
                            "page_number": row.get("page_number"),
                            "section": row.get("section"),
                            "content": row.get("content", ""),
                            "vector_sim": sim,
                            "org_id": doc_meta.get("org_id") or target_org,
                        }
            except Exception as exc:
                logger.warning("Vector search sub-query failed (%s): %s", sub_q[:40], exc)

    # B. Lexical / Exact-Term Scan over org's active chunks (guarantees exact rules & facts aren't missed)
    try:
        org_chunks = get_org_active_chunks(target_org) if target_org else []
        if not org_chunks and not _supabase_configured():
            with _LOCAL_LOCK:
                for doc_id, d in allowed_doc_map.items():
                    for c in _LOCAL_CHUNKS.get(doc_id, []):
                        row = dict(c)
                        row["doc_title"] = d.get("title", "Brand Guideline")
                        row["doc_version"] = d.get("version", "1.0")
                        row["doc_category"] = d.get("category", "guideline")
                        row["org_id"] = d.get("org_id")
                        org_chunks.append(row)

        for c in org_chunks:
            doc_id = c.get("document_id")
            if allowed_doc_map and doc_id not in allowed_doc_map:
                continue
            cid = str(c.get("id") or c.get("chunk_id"))
            if cid not in candidates:
                candidates[cid] = {
                    "chunk_id": cid,
                    "document_id": doc_id,
                    "doc_title": c.get("doc_title", "Brand Guideline"),
                    "category": c.get("doc_category", "guideline"),
                    "version": c.get("doc_version", "1.0"),
                    "page_number": c.get("page_number"),
                    "section": c.get("section"),
                    "content": c.get("content", ""),
                    "vector_sim": 0.0,
                    "org_id": c.get("org_id") or target_org,
                }
    except Exception as exc:
        logger.warning("Lexical org chunk scan warning: %s", exc)

    # C. Hybrid Re-Ranking: semantic + lexical + approved-fact/terminology priority
    ranked: List[BrandChunkMatch] = []
    for item in candidates.values():
        text = item["content"]
        sec = item.get("section")
        lex_score, matched_terms = _score_lexical_match(query_tokens, text, sec)
        vec_sim = float(item.get("vector_sim") or 0.0)
        rule_cat = classify_rule_category(text, sec)

        cat_boost = 0.0
        if rule_cat == "approved_fact" and lex_score > 0.1:
            cat_boost = 0.12
        elif rule_cat in ("terminology", "claim_policy") and lex_score > 0.1:
            cat_boost = 0.08
        elif content_type in ("image", "pdf") and rule_cat == "visual":
            cat_boost = 0.10

        # When vector_sim is unavailable (offline local mode), rely directly on lexical + category boost
        if vec_sim > 0:
            hybrid = 0.62 * vec_sim + 0.28 * lex_score + cat_boost
        else:
            hybrid = 0.85 * lex_score + cat_boost

        # Relevance floor: avoid returning completely unrelated chunks
        if hybrid < 0.18 and not matched_terms:
            continue

        match_type = (
            "approved_fact"
            if rule_cat == "approved_fact"
            else ("exact_rule" if len(matched_terms) >= 2 and lex_score >= 0.3 else "semantic")
        )
        display_sim = round(max(vec_sim, min(0.99, hybrid)), 4)

        ranked.append(
            BrandChunkMatch(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                doc_title=item["doc_title"],
                category=item["category"],
                version=str(item.get("version") or "1.0"),
                page_number=item.get("page_number"),
                section=sec,
                content=text,
                similarity=display_sim,
                org_id=item.get("org_id"),
                match_type=match_type,
                matched_terms=matched_terms,
                hybrid_score=round(hybrid, 4),
            )
        )

    ranked.sort(key=lambda m: (m.hybrid_score or m.similarity, m.similarity), reverse=True)
    return ranked[:top_k]


def retrieve_guidelines(
    content: ContentPayload,
    top_k: int = 6,
    org_id: Optional[str] = None,
    brand_name: Optional[str] = None,
) -> List[GuidelineRef]:
    """Retrieve relevant, org-isolated brand and claim guidelines for `ContentPayload`."""
    target_org = (org_id or getattr(content, "org_id", None) or "").strip().lower() or None
    target_brand = (brand_name or getattr(content, "brand_name", None) or "").strip() or None

    try:
        query_text = getattr(content, "extracted_text", None) or extract_from_payload(content)
        if not query_text:
            query_text = "brand tone terminology claims visual compliance guidelines"

        # If target_org has active docs, strictly use ONLY that org's docs
        org_has_docs = bool(target_org and list_brand_docs(include_inactive=False, org_id=target_org))

        matches = search_brand_rag(
            query=query_text[:3500],
            top_k=top_k,
            org_id=target_org,
            brand_name=target_brand,
            content_type=content.content_type,
        )

        if not matches:
            if org_has_docs:
                # Org has docs but none matched strongly -> fall back to top active chunks of THAT SAME org only
                own_chunks = get_org_active_chunks(target_org)[:top_k]  # type: ignore[arg-type]
                return [
                    GuidelineRef(
                        document=f"{c.get('doc_title', 'Brand Guideline')} (v{c.get('doc_version', '1.0')})",
                        passage_ref=" — ".join(
                            p for p in [c.get("section"), f"Page {c['page_number']}" if c.get("page_number") is not None else None] if p
                        ) or "General",
                        excerpt=c.get("content", ""),
                        source_reference=f"{c.get('doc_title')} [{c.get('doc_category', 'guideline')}]",
                        document_id=c.get("document_id"),
                        chunk_id=str(c.get("id")),
                        section=c.get("section"),
                        page_number=c.get("page_number"),
                        org_id=target_org,
                        category=c.get("rule_category"),
                        version=str(c.get("doc_version", "1.0")),
                    )
                    for c in own_chunks
                ]
            if target_org and _supabase_configured():
                # Org has zero uploaded documents on live DB -> return [] so brand check reports missing guidelines cleanly
                return []
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
                    org_id=m.org_id or target_org,
                    category=m.category,
                    match_type=m.match_type,
                    matched_terms=m.matched_terms,
                    version=m.version,
                )
            )
        return guidelines
    except Exception as exc:
        logger.warning("RAG retrieval fell back due to: %s", exc)
        if target_org:
            return []
        return list(DEFAULT_GUIDELINES)
