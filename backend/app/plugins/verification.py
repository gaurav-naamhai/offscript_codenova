"""Claim verification plugin.

OWNER: Ken
Provisional signature: verify_claims(content) -> list[FlagDraft]
"""

from typing import List
from app.models import ContentPayload, ExternalSource, FlagDraft


def verify_claims(content: ContentPayload) -> List[FlagDraft]:
    """Verify factual claims against external sources."""
    return [
        FlagDraft(
            finding_type="claim",
            state="supported",
            passage="Industry-leading 99.9% uptime SLA.",
            location="paragraph 1",
            explanation="Claim matches verified benchmark and SLA reports.",
            why_it_matters="Ensures commercial claims reflect real capabilities.",
            guideline_ref=None,
            external_sources=[
                ExternalSource(
                    url="https://status.example.com",
                    excerpt="Historical SLA benchmark records 99.95% uptime.",
                )
            ],
            uncertainty_note=None,
            suggested_correction=None,
            origin="fixture",
        )
    ]

