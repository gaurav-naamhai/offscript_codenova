"""Content Understanding module for Inkloom AI.

Owner: Sera
Analyzes draft content across text, images, and PDFs using Gemini.
Extracts individual claims (fact vs opinion vs mixed), identifies context
(audience, purpose, tone, message), and preserves vital anchor entities.

Note on Preserved Entities:
In Batch 2 (Content Understanding), preserved entities are extracted, categorized,
and cataloged. Active programmatic enforcement preventing these entities from being
altered or stripped during automatic suggestions is implemented in the upcoming
Corrections Engine (Batch 4).
"""

import logging
import re
from typing import Optional

from app.ai.brand_verification import resolve_media_mime
from app.ai.client import GeminiClient
from app.ai.schemas import (
    ContentUnderstandingOutput,
    ExtractedClaim,
    PreservedEntity,
)
from app.config import Settings
from app.models import ContentPayload

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You are the Senior Content Understanding and Fact Analysis Specialist for Inkloom AI.
Your task is to comprehensively analyze submitted pre-publication material (text, image, or PDF) for compliance and governance.

Your analysis must:
1. Provide a concise executive summary of the content.
2. Accurately identify the target audience (e.g. enterprise CIOs, consumers, healthcare professionals).
3. Determine the publication purpose and channel (e.g. sales pitch, press release, social ad, technical documentation).
4. Profile the dominant tone (e.g. authoritative, conversational, technical, hyperbolic, urgent).
5. State the creator's core intended takeaway or thesis.
6. Extract every atomic claim made in the content and classify its claim_type:
   - 'fact': Objective, testable assertions regarding performance, metrics, benchmarks, certifications, or historical events.
   - 'opinion': Subjective viewpoints, self-assessments, or stylistic value statements.
   - 'mixed': Combined statements containing an objective fact framed with subjective or promotional spin.
7. Identify and protect all preserved_entities (names, dates, metrics, percentages, SLAs, prices, legal conditions) that must NOT be distorted in subsequent edits.

Always output strictly valid JSON adhering to the ContentUnderstandingOutput schema."""


def understand_content(
    content: ContentPayload,
    client: Optional[GeminiClient] = None,
) -> ContentUnderstandingOutput:
    """Analyze text, image, or PDF content payload for claims, context, and entities.

    Args:
        content: Domain ContentPayload containing text or binary file bytes.
        client: Optional GeminiClient instance (uses default if None).

    Returns:
        Structured ContentUnderstandingOutput with claims, audience, tone, and entities.
    """
    ai_client = client or GeminiClient(settings=Settings())

    # Validate that payload has content to analyze
    has_text = bool(content.text and content.text.strip())
    has_bytes = bool(content.file_bytes and len(content.file_bytes) > 0)

    if not has_text and not has_bytes:
        raise ValueError("ContentPayload contains neither text nor file bytes.")

    # 1. Text Submission
    if content.content_type == "text" or (has_text and not has_bytes):
        text_body = content.text or ""
        if ai_client.mock_mode:
            if ContentUnderstandingOutput in ai_client._mock_handlers:
                return ai_client.generate_structured(prompt="", response_schema=ContentUnderstandingOutput)
            return _generate_mock_content_understanding(text_body=text_body, content_type="text")

        prompt = (
            f"Analyze the following draft text submission for publication:\n\n"
            f"--- BEGIN SUBMISSION ---\n"
            f"{text_body}\n"
            f"--- END SUBMISSION ---\n\n"
            f"Deconstruct all claims (fact, opinion, mixed), profile audience/purpose/tone, "
            f"and extract all critical entities to preserve."
        )
        return ai_client.generate_structured(
            prompt=prompt,
            response_schema=ContentUnderstandingOutput,
            system_instruction=SYSTEM_INSTRUCTION,
        )

    # 2. Image Submission (PNG, JPEG, WebP)
    if content.content_type == "image":
        file_label = content.file_name or "uploaded_image"
        mime_type = resolve_media_mime(content)
        if ai_client.mock_mode:
            if ContentUnderstandingOutput in ai_client._mock_handlers:
                return ai_client.generate_structured(prompt="", response_schema=ContentUnderstandingOutput)
            return _generate_mock_content_understanding(
                text_body=content.text or file_label,
                content_type="image",
                file_name=file_label,
            )

        prompt = (
            f"Analyze this visual image asset ({file_label}).\n\n"
            f"1. Read all visible typography, headlines, fine print, and slogans.\n"
            f"2. Inspect graphical elements, logos, icons, and layout hierarchy.\n"
            f"3. Deconstruct all claims conveyed by visual and textual messaging.\n"
            f"4. Identify audience, purpose, tone, and core intended message.\n"
            f"5. Extract all vital names, metrics, dates, and conditions visible in the asset."
        )
        return ai_client.generate_structured(
            prompt=prompt,
            response_schema=ContentUnderstandingOutput,
            system_instruction=SYSTEM_INSTRUCTION,
            media_bytes=content.file_bytes,
            media_mime=mime_type,
        )

    # 3. PDF Document Submission
    if content.content_type == "pdf":
        file_label = content.file_name or "document.pdf"
        if ai_client.mock_mode:
            if ContentUnderstandingOutput in ai_client._mock_handlers:
                return ai_client.generate_structured(prompt="", response_schema=ContentUnderstandingOutput)
            return _generate_mock_content_understanding(
                text_body=content.text or file_label,
                content_type="pdf",
                file_name=file_label,
            )

        prompt = (
            f"Analyze this complete PDF document ({file_label}).\n\n"
            f"1. Read titles, executive summaries, section headings, body paragraphs, and tables.\n"
            f"2. Deconstruct all claims made throughout the document (fact, opinion, mixed).\n"
            f"3. Identify audience, publication purpose, tone, and intended message.\n"
            f"4. Extract all vital names, dates, metrics, percentages, and conditions to preserve."
        )
        return ai_client.generate_structured(
            prompt=prompt,
            response_schema=ContentUnderstandingOutput,
            system_instruction=SYSTEM_INSTRUCTION,
            media_bytes=content.file_bytes,
            media_mime="application/pdf",
        )

    # Fallback for unknown content type with text
    raise ValueError(f"Unsupported content_type: '{content.content_type}'")


def understand_text(text: str, client: Optional[GeminiClient] = None) -> ContentUnderstandingOutput:
    """Convenience helper to analyze a plain text string."""
    payload = ContentPayload(content_type="text", text=text)
    return understand_content(payload, client=client)


# ============================================================================
# DETERMINISTIC MOCK UNDERSTANDING GENERATOR
# ============================================================================


def _generate_mock_content_understanding(
    text_body: str,
    content_type: str,
    file_name: Optional[str] = None,
) -> ContentUnderstandingOutput:
    """Generate realistic, content-aware understanding for offline testing and evaluation."""
    claims = []
    entities = []

    if content_type == "text" and text_body:
        # Extract metrics (percentages, numbers with units)
        metric_matches = re.finditer(r"\b(\d+(\.\d+)?%|\$\d+(\.\d+)?|\d+\s*(?:ms|seconds|x|hrs))\b", text_body)
        for m in metric_matches:
            val = m.group(0)
            start = max(0, m.start() - 20)
            end = min(len(text_body), m.end() + 20)
            entities.append(
                PreservedEntity(
                    entity_type="metric",
                    text=val,
                    context=text_body[start:end].strip(),
                )
            )

        # Extract dates / years
        date_matches = re.finditer(r"\b(20\d\d|Q[1-4]\s*20\d\d|January|February|March|April|May|June|July|August|September|October|November|December)\b", text_body)
        for d in date_matches:
            val = d.group(0)
            entities.append(
                PreservedEntity(
                    entity_type="date",
                    text=val,
                    context=text_body[max(0, d.start() - 15):min(len(text_body), d.end() + 15)].strip(),
                )
            )

        # Extract proper names / brand candidates
        proper_names = re.findall(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b", text_body)
        for p in proper_names[:3]:
            if p.lower() not in ("the", "this", "our", "we", "with", "all"):
                entities.append(
                    PreservedEntity(
                        entity_type="proper_name",
                        text=p,
                        context=f"Mentioned in text: {p}",
                    )
                )

        # Split into sentences for claim identification
        sentences = [s.strip() for s in re.split(r"[.!?]", text_body) if len(s.strip()) > 10]
        for idx, sentence in enumerate(sentences[:4]):
            c_type = "fact" if any(char.isdigit() for char in sentence) else ("opinion" if any(w in sentence.lower() for w in ("best", "love", "feel", "great", "world-class")) else "mixed")
            claims.append(
                ExtractedClaim(
                    claim_id=f"claim-{idx+1}",
                    text=sentence,
                    claim_type=c_type,
                    passage=sentence,
                    location=f"sentence {idx+1}",
                )
            )

    if not claims:
        # Default representative claims
        claims = [
            ExtractedClaim(
                claim_id="claim-1",
                text=f"Submitted asset contains verifiable {content_type} assertions.",
                claim_type="fact",
                passage=text_body[:60].strip() if text_body else f"{content_type.capitalize()} draft",
                location="header",
            ),
            ExtractedClaim(
                claim_id="claim-2",
                text="The solution delivers market-leading ease of adoption.",
                claim_type="opinion",
                passage="market-leading ease of adoption",
                location="body",
            ),
        ]

    if not entities:
        entities = [
            PreservedEntity(
                entity_type="proper_name",
                text="Inkloom AI",
                context="Primary platform brand name",
            ),
            PreservedEntity(
                entity_type="metric",
                text="99.9%",
                context="Target performance metric",
            ),
        ]

    summary_text = (
        f"Draft {content_type} asset ({file_name or 'text draft'}) describing product capabilities and value propositions."
    )

    return ContentUnderstandingOutput(
        summary=summary_text,
        target_audience="Enterprise decision makers, marketing teams, and brand guardians.",
        purpose="Pre-publication compliance verification and marketing review.",
        tone="Professional, informative, and assertive.",
        intended_message="Demonstrate verified capability while maintaining brand integrity.",
        claims=claims,
        preserved_entities=entities,
    )
