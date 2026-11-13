"""Guideline retrieval plugin.

# PLACEHOLDER: replace body, keep signature
OWNER: Ken
"""

from typing import List
from app.models import ContentPayload, GuidelineRef

RULES = [
    {"id": "claim-speed", "guideline": GuidelineRef(document="Brand Tone and Claim Guidelines v2.1", passage_ref="Section 3.2", excerpt="All factual and statistical performance claims must be substantiated with verifiable sources.")},
    {"id": "claim-supremacy", "guideline": GuidelineRef(document="Brand Tone and Claim Guidelines v2.1", passage_ref="Section 3.4", excerpt="Avoid unverified superlatives and unsubstantiated market ranking declarations.")},
    {"id": "claim-guarantee", "guideline": GuidelineRef(document="Commercial Compliance Standard", passage_ref="Section 2.1", excerpt="Guarantees and SLA promises require explicit limitations and benchmark disclosures.")},
    {"id": "brand-tone", "guideline": GuidelineRef(document="Visual and Brand Identity Playbook", passage_ref="Section 1.1", excerpt="Brand voice must remain measured, authoritative, and free of hyperbolic punctuation.")},
    {"id": "brand-language", "guideline": GuidelineRef(document="Visual and Brand Identity Playbook", passage_ref="Section 1.3", excerpt="Use clear, plain English and avoid buzzwords that obscure genuine product capabilities.")},
]


def retrieve_guidelines(content: ContentPayload) -> List[GuidelineRef]:
    """Retrieve relevant brand and claim guidelines for the submitted content."""
    return [r["guideline"] for r in RULES]
