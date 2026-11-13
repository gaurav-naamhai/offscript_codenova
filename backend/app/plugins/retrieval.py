"""Guideline retrieval plugin.

OWNER: Ken
Provisional signature: retrieve_guidelines(content) -> list[GuidelineRef]
"""

from typing import List
from app.models import ContentPayload, GuidelineRef


def retrieve_guidelines(content: ContentPayload) -> List[GuidelineRef]:
    """Retrieve relevant brand and claim guidelines for the submitted content."""
    return [
        GuidelineRef(
            document="Brand Tone and Claim Guidelines v2.1",
            passage_ref="Section 3.2",
            excerpt="All factual and statistical claims must be substantiated with verifiable sources.",
        ),
        GuidelineRef(
            document="Visual and Brand Identity Playbook",
            passage_ref="Section 1.1",
            excerpt="Brand terminology must adhere to our approved naming taxonomy.",
        ),
    ]

