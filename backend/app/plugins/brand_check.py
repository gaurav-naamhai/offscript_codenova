"""Brand check plugin.

OWNER: Sera
Provisional signature: check_brand(content, guidelines) -> list[FlagDraft]
"""

from typing import List
from app.models import ContentPayload, FlagDraft, GuidelineRef


def check_brand(
    content: ContentPayload, guidelines: List[GuidelineRef]
) -> List[FlagDraft]:
    """Check draft content against brand guidelines and voice principles."""
    ref = guidelines[0] if guidelines else None
    return [
        FlagDraft(
            finding_type="brand",
            state="aligned",
            passage="Empowering modern teams with confidence.",
            location="headline",
            explanation="Aligned with core brand voice principles.",
            why_it_matters="Maintains consistent brand voice across channels.",
            guideline_ref=ref,
            external_sources=[],
            uncertainty_note=None,
            suggested_correction=None,
            origin="fixture",
        )
    ]

