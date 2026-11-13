"""Claim verification plugin.

# PLACEHOLDER: replace body, keep signature
OWNER: Ken
"""

import re
from typing import List
from app.models import ContentPayload, ExternalSource, FlagDraft

RULES = [
    {
        "id": "claim-fastest",
        "pattern": re.compile(r"\bfastest\b", re.IGNORECASE),
        "state": "insufficient_evidence",
        "explanation": "Comparative speed claim lacks benchmark evidence.",
        "why_it_matters": "Unsubstantiated performance claims risk advertising compliance penalties.",
        "replacement": "industry-leading in verified speed",
        "source": ExternalSource(url="https://benchmarks.example.com/speed", excerpt="Standard performance claims require audited benchmark reports."),
    },
    {
        "id": "claim-best-in-world",
        "pattern": re.compile(r"\b(best\s+in\s+the\s+world|#1)\b", re.IGNORECASE),
        "state": "contradicted",
        "explanation": "Absolute market ranking claim contradicts third-party evaluation reports.",
        "why_it_matters": "Global supremacy declarations require exhaustive industry market share citations.",
        "replacement": "a top-tier market provider",
        "source": ExternalSource(url="https://reports.example.com/market-share", excerpt="Comparative market surveys identify multiple enterprise leaders."),
    },
    {
        "id": "claim-guaranteed",
        "pattern": re.compile(r"\b(guaranteed|100%)\b", re.IGNORECASE),
        "state": "insufficient_evidence",
        "explanation": "Absolute guarantee statement lacks SLA and contractual terms references.",
        "why_it_matters": "Unqualified availability or outcome promises create legal breach liability.",
        "replacement": "targeted high reliability",
        "source": ExternalSource(url="https://legal.example.com/sla", excerpt="Commercial terms must define uptime exclusions and scheduled maintenance."),
    },
]


def verify_claims(content: ContentPayload) -> List[FlagDraft]:
    """Verify factual claims against external sources."""
    if content.content_type in ("image", "pdf") or not content.text:
        return [
            FlagDraft(
                finding_type="brand", state="unclear", passage="", location="document",
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
            flags.append(FlagDraft(
                finding_type="claim", state=rule["state"], passage=text[start:end],
                location=f"characters {start}-{end}", explanation=rule["explanation"],
                why_it_matters=rule["why_it_matters"], guideline_ref=None,
                external_sources=[rule["source"]], suggested_correction=rule["replacement"],
                origin="fixture",
            ))

    if not flags:
        metric_match = re.search(r"\b(\d+(\.\d+)?%|uptime|sla|benchmark|verified)\b", text, re.IGNORECASE)
        if metric_match:
            start, end = metric_match.span()
            sentence_start = max(0, text.rfind(".", 0, start) + 1)
            sentence_end = text.find(".", end)
            if sentence_end == -1: sentence_end = len(text)
            passage = text[sentence_start:sentence_end].strip() or text[start:end]
            flags.append(FlagDraft(
                finding_type="claim", state="supported", passage=passage,
                location=f"characters {sentence_start}-{sentence_end}",
                explanation="Factual statement matches verified SLA benchmarks.",
                why_it_matters="Ensures published claims align with historical service records.",
                external_sources=[ExternalSource(url="https://status.example.com", excerpt="Historical status records substantiate published metrics.")],
                origin="fixture",
            ))

    return flags
