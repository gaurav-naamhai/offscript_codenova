"""Guideline Rectification Engine for Inkloom AI.

Detects unclear, conflicting, duplicate, and expired rules across an organisation's
active brand guidelines, explains the issue, and proposes clearer replacement wording
for Manager review and versioned publication.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
import uuid

from pydantic import BaseModel, Field

from app.ai.client import GeminiClient
from app.models import Flag
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)

RectificationIssueType = Literal["unclear", "conflicting", "duplicate", "expired"]


class GuidelineRectification(BaseModel):
    """A proposed guideline rectification waiting for Manager review or already resolved."""

    id: str
    org_id: str
    issue_type: RectificationIssueType
    severity: Literal["low", "medium", "high"] = "medium"
    document_id: str
    document_title: str
    document_version: str = "1.0"
    chunk_id: str
    section: Optional[str] = None
    original_text: str
    target_rule_text: Optional[str] = None
    conflicting_document: Optional[str] = None
    conflicting_text: Optional[str] = None
    problem_explanation: str
    suggested_wording: str
    evidence_count: int = 0
    status: Literal["pending", "approved", "dismissed", "stale"] = "pending"
    invalidation_reason: Optional[str] = None
    approved_wording: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    new_document_id: Optional[str] = None
    new_version: Optional[str] = None
    created_at: str


_VAGUE_TERMS = (
    "appropriate",
    "reasonable",
    "good judgment",
    "good judgement",
    "as needed",
    "where possible",
    "generally",
    "etc.",
    "balanced tone",
    "engaging yet professional",
    "proper",
    "suitable",
)


def _norm_tokens(text: str) -> Set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9%]{3,}", (text or "").lower())
        if t not in {"the", "and", "for", "with", "that", "this", "from", "must", "should", "brand", "guideline"}
    }


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _count_chunk_escalations(historical_flags: List[Flag]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for f in historical_flags:
        if f.status != "open" or f.origin == "error":
            continue
        if not (needs_human(f.state) or f.state == "unclear"):
            continue
        if f.guideline_ref:
            if f.guideline_ref.chunk_id:
                counts[str(f.guideline_ref.chunk_id)] += 1
            if f.guideline_ref.document:
                counts[f.guideline_ref.document.lower()] += 1
    return dict(counts)


def _suggest_clearer_wording(original: str, issue_type: RectificationIssueType, extra: str = "") -> str:
    clean = (original or "").strip()
    # Keep the complete chunk intact. A Manager must provide the policy decision;
    # automatic date or vague-word substitutions can change unrelated rules.
    return clean


def _expired_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """Return a past explicit end date; unknown or future dates are not expired."""
    today = today or datetime.now(timezone.utc).date()
    marker = re.search(r"\b(?:expires?|expired|valid\s+(?:until|through)|ends?|ended|effective\s+(?:until|through))\b", text, re.I)
    if not marker:
        return None
    tail = text[marker.end():marker.end() + 65]
    candidates = re.findall(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b|\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b|\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b|\b20\d{2}\b", tail)
    for candidate in candidates:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                parsed = datetime.strptime(candidate, fmt).date()
                return parsed if parsed < today else None
            except ValueError:
                continue
        if re.fullmatch(r"20\d{2}", candidate):
            # A year-only expiry is not definite until that entire year has passed.
            parsed = date(int(candidate), 12, 31)
            return parsed if parsed < today else None
    return None


def _atomic_rules(text: str) -> List[str]:
    """Split rule lines and sentence boundaries without treating headings as rules."""
    units: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not line or (len(line) < 45 and not re.search(r"[.!?]$|^(?:use|must|never|avoid|do not|always|expires|offer)\b", line, re.I)):
            continue
        units.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if len(part.strip()) >= 12)
    return units


def _detect_conflict_pair(text_a: str, text_b: str) -> Optional[str]:
    """Detect direct polarity or numeric conflicts between two rules covering the same topic."""
    la, lb = text_a.lower(), text_b.lower()
    tok_a, tok_b = _norm_tokens(text_a), _norm_tokens(text_b)
    if _jaccard(tok_a, tok_b) < 0.22:
        return None

    # 1. Opposite modal polarity on same topic (always/must vs never/avoid/prohibited)
    pos_markers = ("always ", "must use", "encourage ", "allowed", "casual", "playful")
    neg_markers = ("never ", "do not ", "don't ", "prohibited", "forbidden", "avoid ", "strictly formal", "no exclamation")
    a_pos = any(m in la for m in pos_markers)
    a_neg = any(m in la for m in neg_markers)
    b_pos = any(m in lb for m in pos_markers)
    b_neg = any(m in lb for m in neg_markers)

    if (a_pos and not a_neg and b_neg and not b_pos) or (b_pos and not b_neg and a_neg and not a_pos):
        shared = sorted(tok_a & tok_b)[:4]
        return f"opposing directives regarding {', '.join(shared) or 'shared terminology/tone'}"

    # 2. Conflicting numeric thresholds (e.g. 99.9% vs 99.99%, 20px vs 40px, #hex codes)
    nums_a = set(re.findall(r"\b\d+(?:\.\d+)?%|\b\d+px\b|\$\d+(?:\.\d+)?", la))
    nums_b = set(re.findall(r"\b\d+(?:\.\d+)?%|\b\d+px\b|\$\d+(?:\.\d+)?", lb))
    if nums_a and nums_b and nums_a != nums_b and _jaccard(tok_a, tok_b) >= 0.30:
        # A ceiling and a prohibited out-of-range example are compatible.
        if ("maximum" in la or "up to" in la or "at most" in la) and ("never" in lb or "do not" in lb or "prohibited" in lb):
            return None
        if ("maximum" in lb or "up to" in lb or "at most" in lb) and ("never" in la or "do not" in la or "prohibited" in la):
            return None
        return f"conflicting numeric thresholds ({', '.join(sorted(nums_a))} vs {', '.join(sorted(nums_b))})"

    return None


def scan_guidelines_for_rectification(
    chunks: List[dict],
    historical_flags: Optional[List[Flag]] = None,
    org_id: str = "inkloom",
    client: Optional[GeminiClient] = None,
) -> List[GuidelineRectification]:
    """Scan active brand chunks + historical flags for unclear, conflicting, duplicate, and expired rules."""
    if not chunks:
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    esc_counts = _count_chunk_escalations(historical_flags or [])
    proposals: List[GuidelineRectification] = []
    seen_keys: Set[Tuple[str, str]] = set()

    def _add(prop: GuidelineRectification) -> None:
        key = (prop.issue_type, prop.chunk_id)
        if key not in seen_keys:
            seen_keys.add(key)
            proposals.append(prop)

    # 1. Expired rules check
    for c in chunks:
        content = (c.get("content") or "").strip()
        if not content:
            continue
        expired = next((d for unit in (_atomic_rules(content) or [content]) if (d := _expired_date(unit))), None)
        if expired:
            hint = expired.isoformat()
            cid = str(c.get("id") or c.get("chunk_id"))
            _add(
                GuidelineRectification(
                    id=f"rect-{uuid.uuid4().hex[:10]}",
                    org_id=org_id,
                    issue_type="expired",
                    severity="high",
                    document_id=str(c.get("document_id")),
                    document_title=str(c.get("doc_title") or "Brand Guideline"),
                    document_version=str(c.get("doc_version") or "1.0"),
                    chunk_id=cid,
                    section=c.get("section"),
                    original_text=content,
                    target_rule_text=next((unit for unit in (_atomic_rules(content) or [content]) if _expired_date(unit)), content),
                    problem_explanation=(
                        f"Rule has an explicit past end date ({hint}). "
                        "Expired campaign rules cause false warnings or outdated claims in current reviews."
                    ),
                    suggested_wording=_suggest_clearer_wording(content, "expired"),
                    evidence_count=1,
                    created_at=now_iso,
                )
            )

    # 2. Pairwise Duplicate & Conflicting rule checks (across chunks AND across paragraphs within chunks)
    def _strip_heading_prefix(unit: str) -> str:
        lines = [ln.strip() for ln in unit.splitlines() if ln.strip()]
        if len(lines) >= 2 and len(lines[0]) <= 50:
            return "\n".join(lines[1:])
        return unit

    rule_units: List[Dict[str, Any]] = []
    for c in chunks:
        raw_txt = (c.get("content") or "").strip()
        if not raw_txt:
            continue
        for p_idx, rule in enumerate(_atomic_rules(raw_txt)):
            rule_units.append({**c, "_unit_text": rule, "_body_text": rule,
                               "_full_text": raw_txt, "_unit_key": f"{c.get('id') or c.get('chunk_id')}#{p_idx}"})

    n = len(rule_units)
    for i in range(n):
        ci = rule_units[i]
        txt_i = ci["_unit_text"]
        body_i = ci["_body_text"]
        key_i = ci["_unit_key"]
        tok_i = _norm_tokens(body_i)
        if not txt_i or len(tok_i) < 2:
            continue

        for j in range(i + 1, n):
            cj = rule_units[j]
            txt_j = cj["_unit_text"]
            body_j = cj["_body_text"]
            key_j = cj["_unit_key"]
            cid_j = str(cj.get("id") or cj.get("chunk_id"))
            if key_i == key_j:
                continue
            tok_j = _norm_tokens(body_j)
            sim = _jaccard(tok_i, tok_j)

            # Duplicate check across chunks/docs/paragraphs
            if sim >= 0.72:
                _add(
                    GuidelineRectification(
                        id=f"rect-{uuid.uuid4().hex[:10]}",
                        org_id=org_id,
                        issue_type="duplicate",
                        severity="low",
                        document_id=str(cj.get("document_id")),
                        document_title=str(cj.get("doc_title") or "Brand Guideline"),
                        document_version=str(cj.get("doc_version") or "1.0"),
                        chunk_id=cid_j,
                        section=cj.get("section"),
                        original_text=txt_j,
                        target_rule_text=txt_j,
                        conflicting_document=f"{ci.get('doc_title', 'Guideline')} ({ci.get('section') or 'General'})",
                        conflicting_text=txt_i[:300],
                        problem_explanation=(
                            f"Near-duplicate rule ({int(sim * 100)}% lexical overlap) with "
                            f"'{ci.get('doc_title', 'Guideline')}'. Duplicate clauses inflate RAG hits and drift over updates."
                        ),
                        suggested_wording=_suggest_clearer_wording(txt_j, "duplicate"),
                        evidence_count=2,
                        created_at=now_iso,
                    )
                )
                continue

            # Conflict check
            conflict_desc = _detect_conflict_pair(txt_i, txt_j)
            if conflict_desc:
                _add(
                    GuidelineRectification(
                        id=f"rect-{uuid.uuid4().hex[:10]}",
                        org_id=org_id,
                        issue_type="conflicting",
                        severity="high",
                        document_id=str(cj.get("document_id")),
                        document_title=str(cj.get("doc_title") or "Brand Guideline"),
                        document_version=str(cj.get("doc_version") or "1.0"),
                        chunk_id=cid_j,
                        section=cj.get("section"),
                        original_text=txt_j,
                        target_rule_text=txt_j,
                        conflicting_document=f"{ci.get('doc_title', 'Guideline')} ({ci.get('section') or 'General'})",
                        conflicting_text=txt_i[:300],
                        problem_explanation=(
                            f"Potential rule conflict ({conflict_desc}) between "
                            f"'{ci.get('doc_title', 'Doc A')}' and '{cj.get('doc_title', 'Doc B')}'. "
                            "Conflicting guidance leads to inconsistent review outcomes."
                        ),
                        suggested_wording=_suggest_clearer_wording(txt_j, "conflicting", conflict_desc),
                        evidence_count=2,
                        created_at=now_iso,
                    )
                )

    # 3. Unclear / Ambiguous rules (vague phrasing OR frequent human escalations in history)
    for c in chunks:
        content = (c.get("content") or "").strip()
        if not content:
            continue
        cid = str(c.get("id") or c.get("chunk_id"))
        low = content.lower()
        vague_hits = [term for term in _VAGUE_TERMS if term in low]
        doc_title = str(c.get("doc_title") or "Brand Guideline")
        esc_hit_count = esc_counts.get(cid, 0) + esc_counts.get(doc_title.lower(), 0)

        if vague_hits or esc_hit_count >= 2:
            reasons = []
            if vague_hits:
                reasons.append(f"subjective phrasing ({', '.join(vague_hits[:3])}) without measurable criteria")
            if esc_hit_count >= 2:
                reasons.append(f"{esc_hit_count} historical reviews resulted in 'unclear' / human escalation")
            _add(
                GuidelineRectification(
                    id=f"rect-{uuid.uuid4().hex[:10]}",
                    org_id=org_id,
                    issue_type="unclear",
                    severity="high" if esc_hit_count >= 2 else "medium",
                    document_id=str(c.get("document_id")),
                    document_title=doc_title,
                    document_version=str(c.get("doc_version") or "1.0"),
                    chunk_id=cid,
                    section=c.get("section"),
                    original_text=content,
                    target_rule_text=next((unit for unit in (_atomic_rules(content) or [content]) if any(term in unit.lower() for term in vague_hits)), content),
                    problem_explanation=f"Ambiguous rule: {' and '.join(reasons)}.",
                    suggested_wording=_suggest_clearer_wording(content, "unclear"),
                    evidence_count=max(1, esc_hit_count),
                    created_at=now_iso,
                )
            )

    # Order high severity first
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    proposals.sort(key=lambda p: (sev_rank.get(p.severity, 1), -p.evidence_count))
    return proposals
