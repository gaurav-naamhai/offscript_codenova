"""Claim verification plugin.

OWNER: Ken
Wires Gaurav's FastAPI pipeline to Ken's live external verification (`retrieval/external_search.py`),
with automatic fallback to offline fixture rules when credentials are unavailable (e.g. unit tests).
"""

import re
from typing import Any, List, Optional

from app.models import ContentPayload, ExternalSource, FlagDraft, GuidelineRef

RULES = [
    {
        "id": "claim-fastest",
        "pattern": re.compile(r"\bfastest\b", re.IGNORECASE),
        "state": "insufficient_evidence",
        "explanation": "Comparative speed claim lacks benchmark evidence.",
        "why_it_matters": "Unsubstantiated performance claims risk advertising compliance penalties.",
        "replacement": "industry-leading in verified speed",
        "source": ExternalSource(
            url="https://benchmarks.example.com/speed",
            excerpt="Standard performance claims require audited benchmark reports.",
        ),
    },
    {
        "id": "claim-best-in-world",
        "pattern": re.compile(r"\b(best\s+in\s+the\s+world|#1)\b", re.IGNORECASE),
        "state": "contradicted",
        "explanation": "Absolute market ranking claim contradicts third-party evaluation reports.",
        "why_it_matters": "Global supremacy declarations require exhaustive industry market share citations.",
        "replacement": "a top-tier market provider",
        "source": ExternalSource(
            url="https://reports.example.com/market-share",
            excerpt="Comparative market surveys identify multiple enterprise leaders.",
        ),
    },
    {
        "id": "claim-guaranteed",
        "pattern": re.compile(r"\b(guaranteed|100%)\b", re.IGNORECASE),
        "state": "insufficient_evidence",
        "explanation": "Absolute guarantee statement lacks SLA and contractual terms references.",
        "why_it_matters": "Unqualified availability or outcome promises create legal breach liability.",
        "replacement": "targeted high reliability",
        "source": ExternalSource(
            url="https://legal.example.com/sla",
            excerpt="Commercial terms must define uptime exclusions and scheduled maintenance.",
        ),
    },
]


def _fallback_verify(content: ContentPayload) -> List[FlagDraft]:
    if content.content_type in ("image", "pdf") or not content.text:
        return [
            FlagDraft(
                finding_type="brand",
                state="unclear",
                passage="",
                location="document",
                explanation="Visual/document claim verification requires automated OCR review module.",
                why_it_matters="Ensures non-text assets adhere to verifiable factual standards.",
                origin="fixture",
            )
        ]

    flags: List[FlagDraft] = []
    text = content.text
    for rule in RULES:
        for match in rule["pattern"].finditer(text):
            start, end = match.span()
            flags.append(
                FlagDraft(
                    finding_type="claim",
                    state=rule["state"],
                    passage=text[start:end],
                    location=f"characters {start}-{end}",
                    explanation=rule["explanation"],
                    why_it_matters=rule["why_it_matters"],
                    guideline_ref=None,
                    external_sources=[rule["source"]],
                    suggested_correction=rule["replacement"],
                    origin="fixture",
                )
            )

    if not flags:
        sample_passage = text[:60].strip() if text else "Draft text"
        flags.append(
            FlagDraft(
                finding_type="claim",
                state="supported",
                passage=sample_passage,
                location="content",
                explanation="No unsubstantiated external promotional claims detected.",
                why_it_matters="Factually grounded statements protect brand credibility.",
                origin="fixture",
            )
        )

    return flags


def verify_claims(
    content: ContentPayload,
    client: Optional[object] = None,
    guidelines: Optional[List[GuidelineRef]] = None,
    content_understanding: Optional[Any] = None,
) -> List[FlagDraft]:
    """Verify factual claims against approved brand facts first, then external sources.

    In AI mode (MOCK_AI=true or GEMINI_API_KEY present):
    Executes Sera's Claim Verification (app.ai.claim_verification) with evidence
    retrieved via Ken's external search (retrieval.external_search).

    In offline fixture mode (no credentials and MOCK_AI=false):
    Falls back to deterministic regex RULES with origin='fixture'.
    """
    from app.config import Settings

    settings = Settings()
    use_ai = (client is not None) or settings.mock_ai or bool(settings.gemini_api_key)

    if use_ai:
        from app.ai.claim_verification import (
            _match_claim_to_internal_facts,
            claim_finding_to_flag_draft,
            verify_claims as ai_verify_claims,
        )
        from app.ai.suggestions_corrections import validate_no_invented_facts

        target_input = content_understanding if content_understanding is not None else content
        claim_output = ai_verify_claims(
            target_input,
            client=client,  # type: ignore[arg-type]
            guidelines=guidelines,
            brand_name=getattr(content, "brand_name", None),
        )
        full_txt = content.text or getattr(content, "extracted_text", None)
        flags: List[FlagDraft] = []
        for f in claim_output.findings:
            if f.suggested_fix:
                ok_fix, _ = validate_no_invented_facts(
                    f.passage, f.suggested_fix, guidelines=guidelines
                )
                if not ok_fix:
                    f.suggested_fix = None
            refs = _match_claim_to_internal_facts(f.claim_text, guidelines) if f.state == "supported" else []
            flags.append(claim_finding_to_flag_draft(f, full_text=full_txt,
                                                     internal_guideline=refs[0] if refs else None))
        if flags:
            return flags
        # When AI ran cleanly and found zero factual claims requiring flags, return supported notice
        sample = (full_txt or content.file_name or "Submitted draft")[:80].strip()
        return [
            FlagDraft(
                finding_type="claim",
                state="supported",
                passage=sample,
                location="content",
                explanation="No unsubstantiated factual or statistical claims requiring external verification were detected.",
                why_it_matters="Ensures published statements do not make unsupported external assertions.",
                origin="module",
            )
        ]

    try:
        from retrieval.config import EXA_API_KEY, GEMINI_API_KEY, TINYFISH_API_KEY

        if not (GEMINI_API_KEY and (EXA_API_KEY or TINYFISH_API_KEY)):
            return _fallback_verify(content)

        from retrieval.external_search import verify_claims as live_verify
        from retrieval.schemas import ContentPayload as RetrievalPayload

        payload = RetrievalPayload(
            content_type=content.content_type,
            text=content.text,
            file_name=content.file_name,
            file_mime=content.file_mime,
            file_bytes=content.file_bytes,
            org_id=getattr(content, "org_id", None),
            brand_name=getattr(content, "brand_name", None),
            extracted_text=getattr(content, "extracted_text", None),
        )
        results = live_verify(payload, brand_name=getattr(content, "brand_name", None))
        return [FlagDraft(**f.model_dump()) for f in results]
    except Exception:
        return _fallback_verify(content)
