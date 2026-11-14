"""Live external claim search, page retrieval, freshness, and error handling.

Uses:
- TinyFish (`TinySearch` + `TinyFetch`) and Exa Search for live web discovery and page extraction.
- Gemini (`gemini-3.5-flash-lite`) to extract verifiable factual claims from a draft and evaluate
  whether retrieved external evidence supports, contradicts, or provides insufficient evidence.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse
import httpx
from google.genai import types

from retrieval.config import (
    EXA_API_KEY,
    EXA_SEARCH_URL,
    GEMINI_MODEL,
    TINYFETCH_URL,
    TINYFISH_API_KEY,
    TINYSEARCH_URL,
    get_genai_client,
)
from retrieval.extractor import extract_from_payload
from retrieval.schemas import (
    ContentPayload,
    ExternalEvidenceItem,
    ExternalSource,
    FlagDraft,
)

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 12.0


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _search_tinysearch(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Query TinySearch (`GET https://api.search.tinyfish.ai?query=...`)."""
    if not TINYFISH_API_KEY:
        return []
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get(
                TINYSEARCH_URL,
                params={"query": query},
                headers={"X-API-Key": TINYFISH_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("results") or [])[:max_results]
    except Exception as exc:
        logger.warning("TinySearch failed for query '%s': %s", query, exc)
        return []


def _search_exa(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Query Exa Search (`POST https://api.exa.ai/search`) with inline text excerpts."""
    if not EXA_API_KEY:
        return []
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(
                EXA_SEARCH_URL,
                headers={
                    "x-api-key": EXA_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "numResults": max_results,
                    "contents": {"text": {"maxCharacters": 900}},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("results") or [])[:max_results]
    except Exception as exc:
        logger.warning("Exa search failed for query '%s': %s", query, exc)
        return []


def _fetch_tinyfetch(urls: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch clean markdown excerpts and metadata via TinyFetch (`POST https://api.fetch.tinyfish.ai`)."""
    if not TINYFISH_API_KEY or not urls:
        return {}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(
                TINYFETCH_URL,
                headers={
                    "X-API-Key": TINYFISH_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": urls},
            )
            resp.raise_for_status()
            data = resp.json()

            by_url: Dict[str, Dict[str, Any]] = {}
            for item in data.get("results") or []:
                u = item.get("url") or item.get("final_url")
                if u:
                    by_url[u] = {"status": "ok", "data": item}
            for err in data.get("errors") or []:
                u = err.get("url")
                if u and u not in by_url:
                    by_url[u] = {
                        "status": "unavailable",
                        "error": err.get("message") or err.get("code") or "fetch_failed",
                    }
            return by_url
    except Exception as exc:
        logger.warning("TinyFetch batch error: %s", exc)
        return {}


def verify_claim_externally(
    query: str,
    max_sources: int = 3,
) -> List[ExternalEvidenceItem]:
    """Discover and fetch live external web evidence for a factual or promotional claim.

    - Discovers candidate URLs via Exa Search and TinySearch.
    - Fetches full page excerpts & publication dates via TinyFetch.
    - Degrades unavailable/blocked/timed-out sources gracefully to `status="unavailable"`.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if not query or not query.strip():
        return []

    candidates: Dict[str, Dict[str, Any]] = {}

    # 1. Discover via Exa Search
    for item in _search_exa(query, max_results=max_sources):
        url = (item.get("url") or "").strip()
        if url and url not in candidates:
            candidates[url] = {
                "url": url,
                "title": item.get("title"),
                "published_date": item.get("publishedDate"),
                "snippet": (item.get("text") or "").strip(),
            }

    # 2. Discover via TinySearch (fills up to max_sources or supplements Exa)
    if len(candidates) < max_sources:
        for item in _search_tinysearch(query, max_results=max_sources):
            url = (item.get("url") or "").strip()
            if url and url not in candidates:
                candidates[url] = {
                    "url": url,
                    "title": item.get("title"),
                    "published_date": None,
                    "snippet": (item.get("snippet") or "").strip(),
                }
            if len(candidates) >= max_sources:
                break

    if not candidates:
        return [
            ExternalEvidenceItem(
                query=query,
                url="https://search.unavailable.local",
                title="No external sources found",
                domain="",
                published_date=None,
                retrieved_at=now_iso,
                excerpt="",
                status="unavailable",
                error_reason="no_search_results_or_service_unreachable",
            )
        ]

    # 3. Fetch full clean page text & metadata via TinyFetch
    target_urls = list(candidates.keys())[:max_sources]
    fetched_map = _fetch_tinyfetch(target_urls)

    evidence_list: List[ExternalEvidenceItem] = []
    for url in target_urls:
        base = candidates[url]
        fetched = fetched_map.get(url)
        domain = _extract_domain(url)

        if fetched and fetched.get("status") == "ok":
            f_data = fetched["data"]
            raw_text = (f_data.get("text") or base.get("snippet") or "").strip()
            excerpt = raw_text[:800].strip()
            pub_date = f_data.get("published_date") or base.get("published_date")
            title = f_data.get("title") or base.get("title")
            status = "ok" if excerpt else "unavailable"
            err_reason = None if status == "ok" else "empty_page_content"
        elif fetched and fetched.get("status") == "unavailable":
            snippet = (base.get("snippet") or "")[:600].strip()
            excerpt = snippet
            pub_date = base.get("published_date")
            title = base.get("title")
            # If Exa already gave us a substantial excerpt, keep 'ok'; otherwise mark 'unavailable'
            status = "ok" if len(snippet) >= 120 else "unavailable"
            err_reason = None if status == "ok" else fetched.get("error", "page_unavailable")
        else:
            snippet = (base.get("snippet") or "")[:600].strip()
            excerpt = snippet
            pub_date = base.get("published_date")
            title = base.get("title")
            status = "ok" if snippet else "unavailable"
            err_reason = None if status == "ok" else "fetch_unavailable"

        evidence_list.append(
            ExternalEvidenceItem(
                query=query,
                url=url,
                title=title,
                domain=domain,
                published_date=pub_date,
                retrieved_at=now_iso,
                excerpt=excerpt,
                status=status,
                error_reason=err_reason,
            )
        )

    return evidence_list


def verify_claims(content: ContentPayload) -> List[FlagDraft]:
    """Gaurav's plugin hook (`backend/app/plugins/verification.py`):
    Extract factual/promotional claims from `ContentPayload`, verify them against live external
    web sources (Exa + TinyFish), and return `List[FlagDraft]`.
    """
    text = extract_from_payload(content)
    if not text:
        return [
            FlagDraft(
                finding_type="claim",
                state="insufficient_evidence",
                passage="(empty or unreadable document)",
                location="document",
                explanation="No readable text could be extracted from the submission for claim verification.",
                why_it_matters="All promotional and factual claims must be verifiable before publication.",
                uncertainty_note="Document text extraction returned empty content; human review required.",
                origin="module",
            )
        ]

    client = get_genai_client()

    # Step 1: Extract up to 3 verifiable factual or promotional claims from the text
    extract_prompt = (
        "You are a brand compliance claim extractor.\n"
        "Identify up to 3 factual, statistical, comparative, or guarantee claims in the draft below "
        "that require external verification or substantiation.\n"
        "Return ONLY valid JSON matching this schema:\n"
        '{"claims": [{"passage": "exact quote from text", "location": "where in text (e.g. paragraph 1)", '
        '"search_query": "focused web search query to verify this claim"}]}\n\n'
        f"DRAFT TEXT:\n{text[:6000]}"
    )

    extracted_claims: List[Dict[str, str]] = []
    try:
        res = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=extract_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                http_options={"api_version": "v1beta"},
            ),
        )
        parsed = json.loads(res.text or "{}")
        extracted_claims = (parsed.get("claims") or [])[:3]
    except Exception as exc:
        logger.warning("Gemini claim extraction failed: %s", exc)

    if not extracted_claims:
        sample = text[:80].strip()
        return [
            FlagDraft(
                finding_type="claim",
                state="supported",
                passage=sample,
                location="content",
                explanation="No unsubstantiated factual or statistical claims requiring external verification were detected.",
                why_it_matters="Ensures published statements do not make unsupported external assertions.",
                origin="module",
            )
        ]

    # Step 2: For each claim, fetch live external evidence and ask Gemini to assess it
    flags: List[FlagDraft] = []
    for item in extracted_claims:
        passage = (item.get("passage") or "").strip() or text[:80].strip()
        location = (item.get("location") or "content").strip()
        search_query = (item.get("search_query") or passage).strip()

        evidence_items = verify_claim_externally(search_query, max_sources=2)
        ok_sources = [e for e in evidence_items if e.status == "ok" and e.excerpt]

        if not ok_sources:
            flags.append(
                FlagDraft(
                    finding_type="claim",
                    state="insufficient_evidence",
                    passage=passage,
                    location=location,
                    explanation="External sources were unavailable or returned insufficient evidence to verify this claim.",
                    why_it_matters="Publishing unverified claims exposes the organisation to compliance and credibility risks.",
                    external_sources=[
                        ExternalSource(
                            url=e.url,
                            excerpt=e.excerpt or f"Source unavailable ({e.error_reason or 'unreachable'})",
                            title=e.title,
                            domain=e.domain,
                            published_date=e.published_date,
                            retrieved_at=e.retrieved_at,
                            status=e.status,
                            error_reason=e.error_reason,
                        )
                        for e in evidence_items
                    ],
                    uncertainty_note="External sources could not be retrieved or lacked relevant evidence. Human review required.",
                    suggested_correction=None,
                    origin="module",
                )
            )
            continue

        evidence_context = "\n\n".join(
            f"Source URL: {e.url}\nPublished: {e.published_date or 'Unknown'}\nExcerpt: {e.excerpt}"
            for e in ok_sources
        )
        eval_prompt = (
            "You are an objective claim verification assistant for a brand governance platform.\n"
            "Evaluate the DRAFT CLAIM against the RETRIEVED EXTERNAL EVIDENCE.\n"
            "Choose `state` as one of:\n"
            "- 'supported': external evidence directly backs the claim.\n"
            "- 'contradicted': external evidence refutes or conflicts with the claim.\n"
            "- 'insufficient_evidence': evidence is partial, outdated, ambiguous, or does not prove an absolute/superlative claim.\n"
            "Provide a clear plain-language `explanation`, `why_it_matters`, an `uncertainty_note` (if state != 'supported'), "
            "and a minimal intent-preserving `suggested_correction` (if state != 'supported').\n"
            "Return ONLY valid JSON:\n"
            '{"state": "supported|contradicted|insufficient_evidence", "explanation": "...", '
            '"why_it_matters": "...", "uncertainty_note": "..." or null, "suggested_correction": "..." or null}\n\n'
            f"DRAFT CLAIM: {passage}\n\nRETRIEVED EXTERNAL EVIDENCE:\n{evidence_context}"
        )

        try:
            eval_res = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=eval_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    http_options={"api_version": "v1beta"},
                ),
            )
            verdict = json.loads(eval_res.text or "{}")
            state = verdict.get("state", "insufficient_evidence")
            if state not in ("supported", "contradicted", "insufficient_evidence"):
                state = "insufficient_evidence"

            flags.append(
                FlagDraft(
                    finding_type="claim",
                    state=state,
                    passage=passage,
                    location=location,
                    explanation=verdict.get("explanation")
                    or "Claim assessed against retrieved external web sources.",
                    why_it_matters=verdict.get("why_it_matters")
                    or "Factual accuracy protects brand credibility and regulatory compliance.",
                    external_sources=[
                        ExternalSource(
                            url=e.url,
                            excerpt=e.excerpt[:400],
                            title=e.title,
                            domain=e.domain,
                            published_date=e.published_date,
                            retrieved_at=e.retrieved_at,
                            status=e.status,
                        )
                        for e in ok_sources
                    ],
                    uncertainty_note=verdict.get("uncertainty_note"),
                    suggested_correction=verdict.get("suggested_correction"),
                    origin="module",
                )
            )
        except Exception as exc:
            logger.warning("Gemini claim evaluation failed: %s", exc)
            flags.append(
                FlagDraft(
                    finding_type="claim",
                    state="insufficient_evidence",
                    passage=passage,
                    location=location,
                    explanation="Automated assessment of external evidence encountered an error; human verification required.",
                    why_it_matters="Uncertain claim verifications must be escalated to a human reviewer.",
                    external_sources=[
                        ExternalSource(
                            url=e.url,
                            excerpt=e.excerpt[:400],
                            title=e.title,
                            domain=e.domain,
                            published_date=e.published_date,
                            retrieved_at=e.retrieved_at,
                            status=e.status,
                        )
                        for e in ok_sources
                    ],
                    uncertainty_note=f"Evaluation error: {type(exc).__name__}",
                    origin="module",
                )
            )

    return flags
