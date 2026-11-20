"""Guideline retrieval plugin with explicit fixture mode and organisation scope."""

from typing import List

from app.config import Settings

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
        from retrieval.brand_rag import list_brand_docs, retrieve_guidelines as rag_retrieve
        org_id = getattr(content, "org_id", None)
        has_active_docs = bool(org_id and list_brand_docs(org_id=org_id))
        if not has_active_docs:
            if getattr(content, "mock_mode", False) or Settings().mock_ai:
                return [r["guideline"] for r in RULES]
            if not (GEMINI_API_KEY and SUPABASE_URL and SUPABASE_KEY):
                raise RuntimeError("Active organisation guideline retrieval is not configured.")
        from retrieval.schemas import ContentPayload as RetrievalPayload

        payload = RetrievalPayload(
            content_type=content.content_type,
            text=content.text,
            file_name=content.file_name,
            file_mime=content.file_mime,
            file_bytes=content.file_bytes,
            org_id=org_id,
            brand_name=getattr(content, "brand_name", None),
            extracted_text=getattr(content, "extracted_text", None),
        )
        results = rag_retrieve(
            payload,
            org_id=org_id,
            brand_name=getattr(content, "brand_name", None),
        )
        expected_org = (getattr(content, "org_id", None) or "").strip().lower()
        if not expected_org:
            raise RuntimeError("Organisation is required for active guideline retrieval.")
        if any((g.org_id or "").strip().lower() != expected_org for g in results):
            raise RuntimeError("Guideline retrieval returned a different organisation's document.")
        return [GuidelineRef(**g.model_dump()) for g in results]
    except Exception:
        raise
