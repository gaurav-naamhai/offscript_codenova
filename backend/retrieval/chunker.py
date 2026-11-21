"""Rule-aware semantic text chunking, metadata tagging, and Brand Constitution compiler."""

import re
from typing import Dict, List, Optional, Set
from retrieval.schemas import DocumentChunk, PageText

# Matches markdown headings (# Heading) or numbered section headers (e.g. "1.2 Tone of Voice" or "SECTION 3:")
HEADING_PATTERN = re.compile(
    r"^(?:#{1,4}\s+(.+)|(?:section\s+\d+[\.\d]*[:\s-]*|^\d+(?:\.\d+)*\s+[A-Z])(.+)?)$",
    re.IGNORECASE,
)

# Rule boundary markers inside paragraphs (numbered rules, bulleted rules, Do/Don't clauses)
RULE_START_PATTERN = re.compile(
    r"^(?:[-*•]\s+|\d+[\.)]\s+|(?:rule|policy|guideline|do|don't|do not|never|always|avoid|approved fact|prohibited|forbidden)\b[:\s-])",
    re.IGNORECASE,
)

STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "will",
    "must", "should", "can", "not", "all", "any", "but", "our", "your", "their", "they",
    "have", "has", "had", "been", "being", "into", "about", "than", "then", "when", "where",
    "which", "while", "such", "only", "also", "more", "most", "very", "use", "using", "used",
}


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
    if first_line.isupper() and 2 <= len(first_line.split()) <= 10:
        return first_line.title()
    return current_section


def classify_rule_category(text: str, section: Optional[str] = None) -> str:
    """Classify a chunk into a semantic governance rule category."""
    combined = f"{section or ''} {text}".lower()
    if any(k in combined for k in ("approved fact", "verified fact", "product spec", "founded", "certified", "ingredient", "nutrition", "metric", "sla", "official stat", "fact sheet")):
        return "approved_fact"
    if any(k in combined for k in ("terminology", "vocabulary", "lexicon", "prohibited term", "forbidden word", "never say", "do not use", "banned", "preferred term", "jargon", "buzzword")):
        return "terminology"
    if any(k in combined for k in ("color", "colour", "palette", "hex", "logo", "clearspace", "typography", "font", "visual", "contrast", "wcag", "accessibility")):
        return "visual"
    if any(k in combined for k in ("claim", "superlative", "guarantee", "benchmark", "substantiat", "proof", "citation", "ranking")):
        return "claim_policy"
    if any(k in combined for k in ("legal", "compliance", "disclaimer", "disclosure", "regulatory", "privacy", "confidential")):
        return "legal"
    if any(k in combined for k in ("tone", "voice", "style", "punctuation", "exclamation", "formal", "conversational", "measured")):
        return "tone"
    return "guideline"


def extract_keywords(text: str, section: Optional[str] = None, max_keywords: int = 24) -> List[str]:
    """Extract normalized searchable keywords, hex codes, numbers, and quoted terms."""
    combined = f"{section or ''} {text}"
    seen: Set[str] = set()
    keywords: List[str] = []

    def _add(tok: str) -> None:
        clean = tok.strip().lower()
        if len(clean) >= 3 and clean not in STOPWORDS and clean not in seen:
            seen.add(clean)
            keywords.append(clean)

    # Preserve hex codes, percentages, and quoted phrases first
    for m in re.findall(r"#[0-9a-fA-F]{3,6}|\b\d+(?:\.\d+)?%|\$?\d+(?:,\d+)*(?:\.\d+)?", combined):
        _add(m)
    for quoted in re.findall(r"[\"'“”]([^\"'“”]{2,40})[\"'“”]", combined):
        _add(quoted)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", combined):
        _add(word)
        if len(keywords) >= max_keywords:
            break
    return keywords[:max_keywords]


def detect_expiry_hint(text: str) -> tuple[bool, Optional[str]]:
    """Detect whether a guideline chunk references an expired or time-bounded rule."""
    patterns = [
        (r"(?:valid\s+(?:until|through)|expires?\s+(?:on|after)?|effective\s+(?:until|through)|ends\s+(?:on)?)\s+([A-Za-z0-9,\s/-]{4,30})", "Time-bounded validity phrase"),
        (r"\b(Q[1-4]\s*20(?:1\d|2[0-5]))\b", "Past quarter reference"),
        (r"\b(20(?:1\d|2[0-5]))\b(?=.{0,40}\b(?:campaign|promo|promotion|offer|pricing|edition|deadline|valid|only|temporary|deprecated|sunset)\b)", "Past campaign or policy year"),
        (r"\b(?:campaign|promo|promotion|offer|pricing|edition|deadline|deprecated|sunset)\b.{0,40}\b(20(?:1\d|2[0-5]))\b", "Past campaign or policy year"),
    ]
    for pat, label in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            snippet = m.group(0).strip()
            return True, f"{label}: '{snippet}'"
    return False, None


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """Split a single oversized paragraph by rule/sentence boundaries with overlap."""
    lines = text.strip().splitlines()
    # Prefer grouping by rule bullets if lines look like rules
    if sum(1 for ln in lines if RULE_START_PATTERN.match(ln.strip())) >= 2:
        units = [ln.strip() for ln in lines if ln.strip()]
    else:
        units = re.split(r"(?<=[.!?])\s+|\n+", text.strip())

    chunks: List[str] = []
    current = ""

    for unit in units:
        if not unit:
            continue
        sep = "\n" if RULE_START_PATTERN.match(unit) else " "
        if len(current) + len(unit) + 1 <= max_chars:
            current = f"{current}{sep}{unit}".strip() if current else unit
        else:
            if current:
                chunks.append(current)
                tail = current[-overlap_chars:] if overlap_chars > 0 else ""
                # Do not start an overlap tail mid-word
                if tail and " " in tail:
                    tail = tail.split(" ", 1)[1]
                current = f"{tail}{sep}{unit}".strip() if tail else unit
            else:
                step = max(100, max_chars - overlap_chars)
                for i in range(0, len(unit), step):
                    chunks.append(unit[i : i + max_chars])
                current = ""

    if current:
        chunks.append(current)
    return chunks


def _build_chunk(
    chunk_idx: int,
    page_number: int,
    section: Optional[str],
    content: str,
) -> DocumentChunk:
    has_expiry, expiry_hint = detect_expiry_hint(content)
    return DocumentChunk(
        chunk_index=chunk_idx,
        page_number=page_number,
        section=section,
        content=content,
        rule_category=classify_rule_category(content, section),
        keywords=extract_keywords(content, section),
        contains_expiry=has_expiry,
        expiry_hint=expiry_hint,
    )


def chunk_pages(
    pages: List[PageText],
    chunk_size: int = 1200,
    chunk_overlap: int = 180,
) -> List[DocumentChunk]:
    """Split extracted pages into rule-aware overlapping chunks preserving page, section, category, and keywords."""
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
            detected_sec = _detect_section(para, current_section)
            # If a clear new section heading begins and buffer already has substantive content, flush buffer cleanly
            if detected_sec != current_section and buffer and len(buffer) >= 180:
                all_chunks.append(_build_chunk(chunk_idx, page.page_number, buffer_section, buffer))
                chunk_idx += 1
                buffer = ""

            current_section = detected_sec
            if not buffer:
                buffer_section = current_section

            if len(para) > chunk_size:
                if buffer:
                    all_chunks.append(_build_chunk(chunk_idx, page.page_number, buffer_section, buffer))
                    chunk_idx += 1
                    buffer = ""
                for sub in _split_long_text(para, chunk_size, chunk_overlap):
                    all_chunks.append(_build_chunk(chunk_idx, page.page_number, current_section, sub))
                    chunk_idx += 1
                buffer_section = current_section
                continue

            if len(buffer) + len(para) + 2 <= chunk_size:
                buffer = f"{buffer}\n\n{para}".strip() if buffer else para
            else:
                if buffer:
                    all_chunks.append(_build_chunk(chunk_idx, page.page_number, buffer_section, buffer))
                    chunk_idx += 1
                    overlap_tail = buffer[-chunk_overlap:].strip() if chunk_overlap > 0 else ""
                    if overlap_tail and " " in overlap_tail:
                        overlap_tail = overlap_tail.split(" ", 1)[1]
                    buffer = f"{overlap_tail}\n\n{para}".strip() if overlap_tail else para
                    buffer_section = current_section
                else:
                    buffer = para
                    buffer_section = current_section

        if buffer:
            all_chunks.append(_build_chunk(chunk_idx, page.page_number, buffer_section, buffer))
            chunk_idx += 1

    return all_chunks


def compile_brand_constitution(
    pages: List[PageText],
    title: str = "",
) -> Dict[str, object]:
    """Compile a machine-readable Brand Constitution from extracted brand document pages.

    Captures approved facts, forbidden terms, preferred terms, tone pillars, official hex colors,
    and time-bounded expiry notices deterministically on ingestion.
    """
    full_text = "\n\n".join(p.text for p in pages if p.text and p.text.strip())
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

    approved_facts: List[str] = []
    forbidden_terms: List[str] = []
    preferred_terms: List[str] = []
    tone_pillars: List[str] = []
    expiry_notices: List[str] = []

    brand_colors = list(dict.fromkeys(m.upper() for m in re.findall(r"#[0-9a-fA-F]{6}\b", full_text)))[:12]

    in_forbidden_block = False
    in_preferred_block = False
    in_fact_block = False

    for line in lines:
        low = line.lower()

        # Section toggles
        if any(k in low for k in ("prohibited", "forbidden", "avoid", "never use", "do not use", "banned terms", "don't:")):
            in_forbidden_block = True
            in_preferred_block = False
            in_fact_block = False
        elif any(k in low for k in ("preferred", "approved terms", "always say", "use instead", "do:")):
            in_preferred_block = True
            in_forbidden_block = False
            in_fact_block = False
        elif any(k in low for k in ("approved fact", "verified fact", "product fact", "key specs", "official facts")):
            in_fact_block = True
            in_forbidden_block = False
            in_preferred_block = False
        elif line.startswith("#") or len(line) < 60 and line.isupper():
            in_forbidden_block = False
            in_preferred_block = False
            in_fact_block = False

        # Extract quoted terms from forbidden / preferred lines
        quoted = re.findall(r"[\"'“”]([^\"'“”]{2,40})[\"'“”]", line)
        if in_forbidden_block or any(k in low for k in ("avoid ", "never say", "do not use", "forbidden:", "prohibited:")):
            for q in quoted:
                if q not in forbidden_terms:
                    forbidden_terms.append(q)
            # Also extract comma-separated short terms after a colon
            if ":" in line and not quoted:
                tail = line.split(":", 1)[1]
                for item in tail.split(","):
                    cleaned = item.strip(" .;-•*")
                    if 2 <= len(cleaned) <= 32 and cleaned not in forbidden_terms:
                        forbidden_terms.append(cleaned)

        if in_preferred_block or any(k in low for k in ("preferred:", "use instead:", "approved term:")):
            for q in quoted:
                if q not in preferred_terms:
                    preferred_terms.append(q)

        prohibition = bool(re.search(r"\b(?:do not|don't|must not|never|prohibit(?:ed)?|forbidden)\b", low))
        if prohibition:
            # Keep the whole negative rule; extracting its number as a fact reverses its meaning.
            if line not in forbidden_terms:
                forbidden_terms.append(line)
        if not prohibition and (in_fact_block or re.match(r"^(?:[-*•]\s*)?(?:approved fact|fact|verified)\s*:", low)):
            cleaned_fact = re.sub(r"^[-*•]\s*", "", line).strip()
            if len(cleaned_fact) >= 12 and cleaned_fact not in approved_facts:
                approved_facts.append(cleaned_fact)
        elif not prohibition and re.search(r"\b\d+(?:\.\d+)?%|\bfounded\b|\bcertified\b|\bsla\b|\borg\b|\b100%\b", low) and len(line) <= 220:
            cleaned_fact = re.sub(r"^[-*•]\s*", "", line).strip()
            if len(cleaned_fact) >= 16 and cleaned_fact not in approved_facts and not in_forbidden_block:
                approved_facts.append(cleaned_fact)

        if any(k in low for k in ("tone:", "voice:", "brand voice", "voice must", "tone should", "tone is")):
            cleaned_tone = re.sub(r"^[-*•]\s*", "", line).strip()
            if 10 <= len(cleaned_tone) <= 200 and cleaned_tone not in tone_pillars:
                tone_pillars.append(cleaned_tone)

        has_exp, exp_hint = detect_expiry_hint(line)
        if has_exp and exp_hint and exp_hint not in expiry_notices:
            expiry_notices.append(exp_hint)

    return {
        "title": title,
        "approved_facts": approved_facts[:20],
        "forbidden_terms": forbidden_terms[:25],
        "preferred_terms": preferred_terms[:25],
        "tone_pillars": tone_pillars[:10],
        "brand_colors": brand_colors,
        "expiry_notices": expiry_notices[:10],
    }
