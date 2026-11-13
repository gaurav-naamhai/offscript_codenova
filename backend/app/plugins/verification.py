"""Claim verification plugin.

OWNER: Ken
Wires Gaurav's FastAPI pipeline to Ken's live external verification (`retrieval/external_search.py`),
with automatic fallback to offline fixture rules when credentials are unavailable (e.g. unit tests).
"""

import re
from typing import List, Optional

from app.models import ContentPayload, ExternalSource, FlagDraft

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
) -> List[FlagDraft]:
    """Verify factual claims against external sources.

    In AI mode (MOCK_AI=true or GEMINI_API_KEY present):
    Executes Sera's Claim Verification (app.ai.claim_verification) with evidence
    retrieved via Ken's external search (retrieval.external_search).

    In offline fixture mode:
    Falls back to deterministic regex RULES with origin='fixture'.
    """
    try:
        from app.config import Settings
        settings = Settings()
        use_ai = (client is not None) or settings.mock_ai or bool(settings.gemini_api_key)

        if use_ai:
            from app.ai.claim_verification import (
                claim_finding_to_flag_draft,
                verify_claims as ai_verify_claims,
            )
            # Route through Sera's claim verification using Ken's external search
            claim_output = ai_verify_claims(content, client=client)  # type: ignore[arg-type]
            flags = [claim_finding_to_flag_draft(f) for f in claim_output.findings]
            if flags:
                return flags

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
        )
        results = live_verify(payload)
        return [FlagDraft(**f.model_dump()) for f in results]
    except Exception:
        return _fallback_verify(content)
