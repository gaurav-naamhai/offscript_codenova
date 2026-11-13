"""Guideline retrieval plugin.

OWNER: Ken
Wires Gaurav's FastAPI pipeline to Ken's Supabase pgvector RAG (`retrieval/brand_rag.py`),
with automatic fallback to offline fixture rules when credentials are unavailable (e.g. unit tests).
"""

from typing import List

from app.models import ContentPayload, GuidelineRef

RULES = [
    {
        "id": "claim-speed",
        "guideline": GuidelineRef(
            document="Brand Tone and Claim Guidelines v2.1",
            passage_ref="Section 3.2",
            excerpt="All factual and statistical performance claims must be substantiated with verifiable sources.",
        ),
    },
    {
        "id": "claim-supremacy",
        "guideline": GuidelineRef(
            document="Brand Tone and Claim Guidelines v2.1",
            passage_ref="Section 3.4",
            excerpt="Avoid unverified superlatives and unsubstantiated market ranking declarations.",
        ),
    },
    {
        "id": "claim-guarantee",
        "guideline": GuidelineRef(
            document="Commercial Compliance Standard",
            passage_ref="Section 2.1",
            excerpt="Guarantees and SLA promises require explicit limitations and benchmark disclosures.",
        ),
    },
    {
        "id": "brand-tone",
        "guideline": GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.1",
            excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.",
        ),
    },
    {
        "id": "brand-language",
        "guideline": GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.3",
            excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.",
        ),
    },
]


def retrieve_guidelines(content: ContentPayload) -> List[GuidelineRef]:
    """Retrieve relevant brand and claim guidelines for the submitted content."""
    try:
        from retrieval.config import GEMINI_API_KEY, SUPABASE_KEY, SUPABASE_URL
        if not (GEMINI_API_KEY and SUPABASE_URL and SUPABASE_KEY):
            return [r["guideline"] for r in RULES]

        from retrieval.brand_rag import retrieve_guidelines as rag_retrieve
        from retrieval.schemas import ContentPayload as RetrievalPayload

        payload = RetrievalPayload(
            content_type=content.content_type,
            text=content.text,
            file_name=content.file_name,
            file_mime=content.file_mime,
            file_bytes=content.file_bytes,
        )
        results = rag_retrieve(payload)
        return [GuidelineRef(**g.model_dump()) for g in results]
    except Exception:
        return [r["guideline"] for r in RULES]
