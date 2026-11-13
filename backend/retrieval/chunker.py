"""Paragraph-aware text chunking with overlap and page/section metadata."""

import re
from typing import List, Optional
from retrieval.schemas import DocumentChunk, PageText

# Matches markdown headings (# Heading) or numbered section headers (e.g. "1.2 Tone of Voice" or "SECTION 3:")
HEADING_PATTERN = re.compile(
    r"^(?:#{1,4}\s+(.+)|(?:section\s+\d+[\.\d]*[:\s-]*|^\d+(?:\.\d+)*\s+[A-Z])(.+)?)$",
    re.IGNORECASE,
)


def _detect_section(paragraph: str, current_section: Optional[str]) -> Optional[str]:
    """Detect if a paragraph starts with a section heading."""
    first_line = paragraph.strip().splitlines()[0].strip() if paragraph.strip() else ""
    if not first_line or len(first_line) > 90:
        return current_section
    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()
    if HEADING_PATTERN.match(first_line):
        return first_line
    # All-caps short title line
    if first_line.isupper() and 3 <= len(first_line.split()) <= 10:
        return first_line.title()
    return current_section


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """Split a single oversized paragraph by sentence/line boundaries with overlap."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    chunks: List[str] = []
    current = ""

    for sent in sentences:
        if not sent:
            continue
        if len(current) + len(sent) + 1 <= max_chars:
            current = f"{current} {sent}".strip() if current else sent
        else:
            if current:
                chunks.append(current)
                tail = current[-overlap_chars:] if overlap_chars > 0 else ""
                current = f"{tail} {sent}".strip()
            else:
                # Single sentence exceeds max_chars -> hard slice
                for i in range(0, len(sent), max_chars - overlap_chars):
                    chunks.append(sent[i : i + max_chars])
                current = ""

    if current:
        chunks.append(current)
    return chunks


def chunk_pages(
    pages: List[PageText],
    chunk_size: int = 1400,
    chunk_overlap: int = 200,
) -> List[DocumentChunk]:
    """Split extracted pages into ~250-400 word overlapping chunks while preserving `page_number` and `section`."""
    all_chunks: List[DocumentChunk] = []
    chunk_idx = 0
    current_section: Optional[str] = None

    for page in pages:
        raw_page_text = (page.text or "").strip()
        if not raw_page_text:
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_page_text) if p.strip()]
        buffer = ""
        buffer_section = current_section

        for para in paragraphs:
            current_section = _detect_section(para, current_section)
            if not buffer:
                buffer_section = current_section

            if len(para) > chunk_size:
                if buffer:
                    all_chunks.append(
                        DocumentChunk(
                            chunk_index=chunk_idx,
                            page_number=page.page_number,
                            section=buffer_section,
                            content=buffer,
                        )
                    )
                    chunk_idx += 1
                    buffer = ""
                for sub in _split_long_text(para, chunk_size, chunk_overlap):
                    all_chunks.append(
                        DocumentChunk(
                            chunk_index=chunk_idx,
                            page_number=page.page_number,
                            section=current_section,
                            content=sub,
                        )
                    )
                    chunk_idx += 1
                buffer_section = current_section
                continue

            if len(buffer) + len(para) + 2 <= chunk_size:
                buffer = f"{buffer}\n\n{para}".strip() if buffer else para
            else:
                if buffer:
                    all_chunks.append(
                        DocumentChunk(
                            chunk_index=chunk_idx,
                            page_number=page.page_number,
                            section=buffer_section,
                            content=buffer,
                        )
                    )
                    chunk_idx += 1
                    # Keep tail overlap from previous chunk on the same page
                    overlap_tail = buffer[-chunk_overlap:].strip() if chunk_overlap > 0 else ""
                    buffer = f"{overlap_tail}\n\n{para}".strip() if overlap_tail else para
                    buffer_section = current_section
                else:
                    buffer = para
                    buffer_section = current_section

        if buffer:
            all_chunks.append(
                DocumentChunk(
                    chunk_index=chunk_idx,
                    page_number=page.page_number,
                    section=buffer_section,
                    content=buffer,
                )
            )
            chunk_idx += 1

    return all_chunks
