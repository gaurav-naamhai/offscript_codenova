"""Brand check plugin.

# PLACEHOLDER: replace body, keep signature
OWNER: Sera
"""

import re
from typing import List
from app.models import ContentPayload, FlagDraft, GuidelineRef

RULES = [
    {"id": "brand-exclamation", "pattern": re.compile(r"!{2,}"), "state": "potential_issue", "explanation": "Multiple exclamation marks violate professional brand tone guidelines.", "why_it_matters": "Maintains an approachable, clear, and trustworthy voice.", "replacement": "."},
    {"id": "brand-buzzword", "pattern": re.compile(r"\b(synergy|disruptive|game-changing)\b", re.IGNORECASE), "state": "potential_issue", "explanation": "Corporate buzzwords conflict with plain-English communication principles.", "why_it_matters": "Clear terminology preserves credibility across enterprise audiences.", "replacement": "effective collaboration"},
    {"id": "brand-cheap", "pattern": re.compile(r"\bcheap\b", re.IGNORECASE), "state": "potential_issue", "explanation": "Term 'cheap' undermines premium brand positioning standards.", "why_it_matters": "Messaging must highlight cost-efficiency and value over low cost.", "replacement": "cost-effective"},
]


def check_brand(content: ContentPayload, guidelines: List[GuidelineRef]) -> List[FlagDraft]:
    """Check draft content against brand guidelines and voice principles."""
    ref = guidelines[0] if guidelines else None
    if content.content_type in ("image", "pdf") or not content.text:
        return [
            FlagDraft(
                finding_type="brand", state="unclear", passage="", location="document",
                explanation="Visual/document brand review requires multimodal design review module.",
                why_it_matters="Ensures design assets comply with brand typography and visual standards.",
                guideline_ref=ref, origin="fixture",
            )
        ]

    flags: List[FlagDraft] = []
    text = content.text
    for rule in RULES:
        for match in rule["pattern"].finditer(text):
            start, end = match.span()
            flags.append(FlagDraft(
                finding_type="brand", state=rule["state"], passage=text[start:end],
                location=f"characters {start}-{end}", explanation=rule["explanation"],
                why_it_matters=rule["why_it_matters"], guideline_ref=ref,
                suggested_correction=rule["replacement"], origin="fixture",
            ))

    if not flags:
        sample_passage = text[:60].strip() if text else "Draft text"
        flags.append(FlagDraft(
            finding_type="brand", state="aligned", passage=sample_passage, location="content",
            explanation="Content voice aligns with core brand guidelines.",
            why_it_matters="Consistent tone reinforces brand recognition and authority.",
            guideline_ref=ref, origin="fixture",
        ))

    return flags
