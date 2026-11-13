"""External Claim Verification module for Inkloom AI.

Owner: Sera
Evaluates factual and promotional claims against external evidence retrieved
via Ken's retrieval interface (Exa + TinySearch + TinyFetch).
Enforces zero-hallucination guardrails, checks source freshness, recency,
and conflicting evidence, and escalates to human review when uncertain.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Union

from app.ai.client import GeminiClient
from app.ai.content_understanding import understand_content
from app.ai.schemas import (
    ClaimFinding,
    ClaimVerificationOutput,
    ContentUnderstandingOutput,
    ExtractedClaim,
)
from app.config import Settings
from app.models import ContentPayload, ExternalSource
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)

CLAIM_SYSTEM_INSTRUCTION = """You are the Senior Fact-Checking and Claim Verification Specialist for Inkloom AI.
Your responsibility is to verify factual, statistical, comparative, and guarantee claims against retrieved external evidence.

CRITICAL OPERATIONAL RULES:
1. STRICT EVIDENCE GROUNDING: You must ONLY evaluate claims using the provided retrieved external evidence. NEVER invent sources, URLs, quotes, or statistics.
2. VERDICT CLASSIFICATION:
   - 'supported': Authoritative retrieved evidence directly substantiates and confirms the claim.
   - 'contradicted': Retrieved evidence directly refutes, disproves, or contradicts the statement.
   - 'insufficient_evidence': Evidence is absent, incomplete, outdated, conflicting/disputed, or unable to prove absolute superlatives (e.g. '#1', 'world's best', '100% guarantee').
3. CONFLICTING EVIDENCE RULE: When multiple reliable sources present conflicting or contradictory findings, DO NOT classify the claim as definitively contradicted. Instead, classify as 'insufficient_evidence', set evidence_quality='conflicting', and supply an explicit uncertainty_note noting the disagreement for human review.
4. CONTEXTUAL FRESHNESS EVALUATION:
   - For fast-moving performance, speed, latency, SLA, or current market share claims: evidence must be contemporary. Older reports must be classified as 'outdated' and evaluated as 'insufficient_evidence'.
   - For historical milestones, founding dates, or static patents (e.g. 'Founded in 1972'): historical sources are fully authoritative and NOT outdated.
5. SOURCE RELIABILITY & METADATA:
   - Check source domains, publication dates, and excerpts.
   - If source metadata or excerpts are missing or unavailable, assign evidence_quality='insufficient'. Never invent reliability when metadata is absent.
6. UNCERTAINTY ESCALATION: When evidence is ambiguous, partial, or conflicting, supply an explicit 'uncertainty_note' explaining the gap so human reviewers can intervene.
7. EXPLANATIONS & WHY IT MATTERS:
   - Provide an objective plain-language explanation of how the evidence supports or contradicts the claim.
   - Explain 'why_it_matters' from a legal, advertising standard, or commercial risk perspective.
   - For non-supported claims, provide an intent-preserving 'suggested_fix' (e.g. softening superlatives to verified claims).

Always return strictly valid JSON matching the ClaimVerificationOutput schema."""


def validate_and_ground_claim_findings(
    findings: List[ClaimFinding],
    available_evidence: List[Any],
) -> List[ClaimFinding]:
    """Validate that cited URLs, titles, excerpts and source metadata correspond to retrieved evidence.

    1. Ensures a valid URL alone does not make a finding valid if the source was unavailable or empty.
    2. Synchronizes verbatim excerpts from retrieved evidence to prevent AI paraphrasing drift.
    3. Converts ungrounded, hallucinated, or placeholder URLs to 'insufficient_evidence'.
    """
    evidence_by_url: Dict[str, Any] = {}
    for ev in available_evidence:
        u = getattr(ev, "url", None) or (ev.get("url") if isinstance(ev, dict) else None)
        if u:
            evidence_by_url[u.strip().lower()] = ev

    grounded_findings: List[ClaimFinding] = []

    for f in findings:
        cited_url = (f.evidence_source_url or "").strip().lower()

        # Reject synthetic placeholder URLs
        if cited_url and ("unavailable.local" in cited_url or "search.unavailable" in cited_url):
            logger.warning("Placeholder failure URL detected in finding: '%s'. Converting to 'insufficient_evidence'.", cited_url)
            f.state = "insufficient_evidence"
            f.evidence_quality = "insufficient"
            f.uncertainty_note = "External retrieval was unable to reach or find public sources for this query. Escalated for human verification."
            f.evidence_source_url = None
            f.evidence_excerpt = None
            f.external_sources = []
            grounded_findings.append(f)
            continue

        # Ground against verified retrieved evidence
        if cited_url and cited_url in evidence_by_url:
            matched_ev = evidence_by_url[cited_url]
            status = getattr(matched_ev, "status", "ok")
            excerpt = getattr(matched_ev, "excerpt", "") or ""

            # Rule: A valid URL alone does not make a finding valid if status is unavailable or text is empty
            if status == "unavailable" or not excerpt.strip():
                logger.warning("Cited URL '%s' has status='unavailable' or empty excerpt. Converting to 'insufficient_evidence'.", cited_url)
                f.state = "insufficient_evidence"
                f.evidence_quality = "insufficient"
                f.uncertainty_note = f"Source URL '{cited_url}' was unreachable or returned empty text. Human verification required."
                f.external_sources = [ExternalSource(url=cited_url, excerpt="Source text unavailable.")]
                grounded_findings.append(f)
                continue

            # Synchronize excerpt directly from retrieved evidence to avoid inaccurate AI paraphrasing
            f.evidence_excerpt = excerpt[:500].strip()
            f.external_sources = [ExternalSource(url=cited_url, excerpt=f.evidence_excerpt)]
            grounded_findings.append(f)

        elif not cited_url:
            # Finding has no cited URL (e.g. claim marked insufficient_evidence due to missing evidence)
            grounded_findings.append(f)

        else:
            # Cited URL was hallucinated / not present in retrieved evidence
            logger.warning(
                "Ungrounded external source URL cited: '%s'. Converting finding to 'insufficient_evidence'.",
                f.evidence_source_url,
            )
            f.state = "insufficient_evidence"
            f.evidence_quality = "none"
            f.uncertainty_note = (
                f"Unverified external source: The cited URL '{f.evidence_source_url}' was not present "
                f"in the retrieved evidence. Flagged as insufficient evidence for human review."
            )
            f.evidence_source_url = None
            f.evidence_excerpt = None
            f.external_sources = []
            grounded_findings.append(f)

    return grounded_findings


def verify_claims_against_evidence(
    claims: List[ExtractedClaim],
    evidence_map: Optional[Dict[str, List[Any]]] = None,
    client: Optional[GeminiClient] = None,
    auto_fetch_evidence: bool = True,
) -> ClaimVerificationOutput:
    """Evaluate extracted factual claims against external evidence retrieved via Ken's interface.

    Args:
        claims: List of ExtractedClaim items (from Content Understanding).
        evidence_map: Optional mapping of claim_id/text -> List of ExternalEvidenceItem.
        client: Optional GeminiClient instance.
        auto_fetch_evidence: If True and evidence_map is missing, calls Ken's retrieval interface.

    Returns:
        ClaimVerificationOutput containing claim-by-claim verification findings.
    """
    ai_client = client or GeminiClient(settings=Settings())

    if not claims:
        return ClaimVerificationOutput(findings=[])

    # Filter strictly to factual or mixed claims. Subjective opinions do NOT require external factual evidence!
    target_claims = [c for c in claims if c.claim_type in ("fact", "mixed")]
    if not target_claims:
        logger.info("No factual or mixed claims requiring external verification were identified in submission.")
        return ClaimVerificationOutput(findings=[])

    resolved_evidence: Dict[str, List[Any]] = dict(evidence_map or {})
    all_evidence_items: List[Any] = []

    # If evidence was not pre-supplied, use Ken's retrieval interface to fetch live evidence
    if auto_fetch_evidence and not evidence_map and not ai_client.mock_mode:
        try:
            from retrieval.external_search import verify_claim_externally

            for c in target_claims[:4]:  # Budget to top 4 claims
                query = c.text
                items = verify_claim_externally(query, max_sources=3)
                resolved_evidence[c.claim_id] = items
                all_evidence_items.extend(items)
        except Exception as exc:
            logger.warning("Ken's external search invocation failed: %s", exc)

    # Collect all available evidence for grounding post-validation
    for ev_list in resolved_evidence.values():
        all_evidence_items.extend(ev_list)

    # 1. Handle Mock Mode Deterministically
    if ai_client.mock_mode:
        if ClaimVerificationOutput in ai_client._mock_handlers:
            output = ai_client.generate_structured(prompt="", response_schema=ClaimVerificationOutput)
        else:
            output = _generate_mock_claim_verification(target_claims, resolved_evidence)
        output.findings = validate_and_ground_claim_findings(output.findings, all_evidence_items)
        return output

    # 2. Live Gemini Execution
    # Format claims and evidence into structured verification prompt
    prompt_sections = []
    for idx, c in enumerate(target_claims):
        ev_items = resolved_evidence.get(c.claim_id) or resolved_evidence.get(c.text) or []
        ev_text = "No external evidence retrieved."
        if ev_items:
            ev_text = "\n".join(
                [
                    f"  - Source URL: {getattr(e, 'url', 'N/A')}\n"
                    f"    Title: {getattr(e, 'title', 'N/A')}\n"
                    f"    Domain: {getattr(e, 'domain', 'N/A')}\n"
                    f"    Published: {getattr(e, 'published_date', 'Unknown')}\n"
                    f"    Status: {getattr(e, 'status', 'ok')}\n"
                    f"    Excerpt: \"{getattr(e, 'excerpt', '')[:500]}\""
                    for e in ev_items
                ]
            )

        prompt_sections.append(
            f"CLAIM {idx+1} (ID: {c.claim_id}):\n"
            f"Passage: \"{c.passage}\"\n"
            f"Location: {c.location}\n"
            f"Statement: \"{c.text}\"\n"
            f"Retrieved External Evidence:\n{ev_text}\n"
        )

    full_prompt = (
        "Evaluate the following draft claims against the retrieved external evidence.\n\n"
        + "\n---\n".join(prompt_sections)
        + "\n\nFor each claim, determine state ('supported', 'contradicted', 'insufficient_evidence'), "
        "cite specific evidence URLs, assess evidence quality, explain the verdict, "
        "and provide uncertainty notes where evidence is incomplete, outdated, or conflicting."
    )

    output = ai_client.generate_structured(
        prompt=full_prompt,
        response_schema=ClaimVerificationOutput,
        system_instruction=CLAIM_SYSTEM_INSTRUCTION,
    )

    # Post-validation: ground findings against authoritative evidence
    output.findings = validate_and_ground_claim_findings(output.findings, all_evidence_items)
    return output


def verify_claims(
    content: Union[ContentPayload, str, ContentUnderstandingOutput],
    evidence_map: Optional[Dict[str, List[Any]]] = None,
    client: Optional[GeminiClient] = None,
) -> ClaimVerificationOutput:
    """High-level entry point accepting ContentPayload, text string, or ContentUnderstandingOutput."""
    if isinstance(content, ContentUnderstandingOutput):
        claims = content.claims
    elif isinstance(content, ContentPayload):
        cu = understand_content(content, client=client)
        claims = cu.claims
    elif isinstance(content, str):
        payload = ContentPayload(content_type="text", text=content)
        cu = understand_content(payload, client=client)
        claims = cu.claims
    else:
        raise TypeError(f"Unsupported content type for verify_claims: {type(content)}")

    return verify_claims_against_evidence(
        claims=claims,
        evidence_map=evidence_map,
        client=client,
        auto_fetch_evidence=True,
    )


# ============================================================================
# DETERMINISTIC MOCK CLAIM VERIFICATION GENERATOR
# ============================================================================


def _evaluate_contextual_freshness(claim_text: str, published_date: Optional[str]) -> bool:
    """Contextual freshness assessment: distinguishes contemporary performance claims from historical facts."""
    if not published_date:
        return False  # Missing date alone does not mean outdated without claim context

    # Check if claim is a historical milestone (e.g. founding date, inception, patent, origin)
    # Note: Do not match bare 'history' as phrases like 'in history' appear in contemporary superlatives
    is_historical_claim = bool(
        re.search(
            r"\b(founded|established|patented|origin|originated|created in|first launched in|inception)\b",
            claim_text,
            re.IGNORECASE,
        )
    )
    if is_historical_claim:
        return False  # Historical milestones naturally rely on older sources

    # Extract year from published_date string
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", published_date)
    pub_year = int(year_match.group(1)) if year_match else None

    # Contemporary / performance claims (e.g. fastest, current, latest, uptime, benchmark, 2026 SLA)
    is_contemporary = bool(
        re.search(
            r"\b(fastest|current|latest|uptime|latency|throughput|sla|benchmark|leading|today|now|202[5-9])\b",
            claim_text,
            re.IGNORECASE,
        )
    )

    current_year = 2026
    if is_contemporary and pub_year:
        # If the claim is about contemporary/current performance and the source is >= 2 years old (pre-2025)
        if (current_year - pub_year) >= 2:
            return True

    return False


def _generate_mock_claim_verification(
    claims: List[ExtractedClaim],
    evidence_map: Dict[str, List[Any]],
) -> ClaimVerificationOutput:
    """Generate realistic, evidence-grounded mock claim findings for offline testing."""
    findings: List[ClaimFinding] = []

    for c in claims:
        text = c.text.lower()
        ev_items = evidence_map.get(c.claim_id) or evidence_map.get(c.text) or []

        # Case 1: Pre-supplied evidence check
        if ev_items:
            first_ev = ev_items[0]
            url = getattr(first_ev, "url", "https://status.example.com")
            excerpt = getattr(first_ev, "excerpt", "Historical benchmark records.")
            pub_date = getattr(first_ev, "published_date", None)
            domain = getattr(first_ev, "domain", "")
            status = getattr(first_ev, "status", "ok")

            # Check if source status was unavailable or empty
            if status == "unavailable" or not excerpt.strip():
                findings.append(
                    ClaimFinding(
                        claim_text=c.text,
                        passage=c.passage,
                        location=c.location,
                        state="insufficient_evidence",
                        explanation="External evidence source is unavailable, unreachable, or returned empty content.",
                        why_it_matters="Published claims must be backed by accessible and verifiable public sources.",
                        evidence_source_url=url,
                        evidence_excerpt=excerpt or "Source text unavailable.",
                        evidence_quality="insufficient",
                        uncertainty_note="External retrieval service was unavailable. Human review required.",
                        suggested_fix=None,
                        external_sources=[ExternalSource(url=url, excerpt=excerpt or "Unavailable")],
                    )
                )
                continue

            # Contextual Freshness Check
            is_outdated = _evaluate_contextual_freshness(c.text, pub_date)
            if is_outdated:
                findings.append(
                    ClaimFinding(
                        claim_text=c.text,
                        passage=c.passage,
                        location=c.location,
                        state="insufficient_evidence",
                        explanation=f"Retrieved benchmark evidence is outdated (published {pub_date}) for a current performance claim.",
                        why_it_matters="Outdated performance benchmarks violate advertising truthfulness regulations.",
                        evidence_source_url=url,
                        evidence_excerpt=excerpt,
                        evidence_quality="outdated",
                        uncertainty_note=f"Outdated evidence from {pub_date}; cannot substantiate current-year performance.",
                        suggested_fix="verified in recent benchmarks",
                        external_sources=[ExternalSource(url=url, excerpt=excerpt)],
                    )
                )
                continue

            # Conflicting Evidence Check: Disputed evidence leads to uncertainty, NOT definitive contradiction
            has_conflict = len(ev_items) > 1 and any(
                "conflict" in getattr(e, "excerpt", "").lower() or "disputed" in getattr(e, "excerpt", "").lower()
                for e in ev_items
            )
            if has_conflict:
                findings.append(
                    ClaimFinding(
                        claim_text=c.text,
                        passage=c.passage,
                        location=c.location,
                        state="insufficient_evidence",  # Disputed / uncertain, requiring human review
                        explanation="Multiple retrieved external sources present conflicting or contradictory findings regarding this claim. The facts are disputed.",
                        why_it_matters="Publishing contested claims without qualification risks credibility and regulatory scrutiny.",
                        evidence_source_url=url,
                        evidence_excerpt=excerpt,
                        evidence_quality="conflicting",
                        uncertainty_note="Third-party benchmark evaluations report conflicting metrics. Human reviewer must resolve the discrepancy.",
                        suggested_fix=None,
                        external_sources=[
                            ExternalSource(url=e.url, excerpt=e.excerpt[:200])
                            for e in ev_items
                            if hasattr(e, "url")
                        ],
                    )
                )
                continue

            # Check direct contradiction: evidence explicitly refutes the claim
            is_contradicted = any(
                "contradicts" in getattr(e, "excerpt", "").lower() or "refuted" in getattr(e, "excerpt", "").lower()
                or ("#1" in text and "multiple leaders" in getattr(e, "excerpt", "").lower())
                for e in ev_items
            )
            if is_contradicted:
                findings.append(
                    ClaimFinding(
                        claim_text=c.text,
                        passage=c.passage,
                        location=c.location,
                        state="contradicted",
                        explanation="Retrieved third-party market survey explicitly contradicts the supremacy claim.",
                        why_it_matters="Publishing contradicted supremacy claims exposes the organization to advertising standards penalties.",
                        evidence_source_url=url,
                        evidence_excerpt=excerpt,
                        evidence_quality="reliable",
                        uncertainty_note="Verified third-party evaluations directly refute market supremacy.",
                        suggested_fix="a top-tier market provider",
                        external_sources=[ExternalSource(url=url, excerpt=excerpt)],
                    )
                )
                continue

            # Reliability determination based on available metadata:
            # Requires valid domain, substantive excerpt, and operational source status.
            # Missing or incomplete metadata must NOT produce invented reliability.
            has_domain = bool(domain and domain.strip() and "." in domain)
            has_substantive_excerpt = bool(excerpt and len(excerpt.strip()) >= 20)
            is_ok = (status == "ok")
            quality = "reliable" if (has_domain and has_substantive_excerpt and is_ok) else "insufficient"

            # Supported claim with reliable evidence
            findings.append(
                ClaimFinding(
                    claim_text=c.text,
                    passage=c.passage,
                    location=c.location,
                    state="supported",
                    explanation="Factual statement matches verified SLA benchmarks and third-party audit reports.",
                    why_it_matters="Verifiable factual claims build credibility and protect against compliance penalties.",
                    evidence_source_url=url,
                    evidence_excerpt=excerpt,
                    evidence_quality=quality,
                    uncertainty_note=None,
                    suggested_fix=None,
                    external_sources=[ExternalSource(url=url, excerpt=excerpt)],
                )
            )
            continue

        # Case 2: Pattern-based evaluation when evidence is absent
        if any(w in text for w in ("fastest", "speed", "latency", "40%", "99.9%")):
            findings.append(
                ClaimFinding(
                    claim_text=c.text,
                    passage=c.passage,
                    location=c.location,
                    state="insufficient_evidence",
                    explanation="Comparative performance and speed claim lacks verified third-party benchmark evidence.",
                    why_it_matters="Unsubstantiated performance figures create legal advertising compliance risks.",
                    evidence_source_url=None,
                    evidence_excerpt=None,
                    evidence_quality="none",
                    uncertainty_note="No external benchmark was supplied to substantiate this metric. Human review required.",
                    suggested_fix="industry-leading verified performance",
                    external_sources=[],
                )
            )
        elif any(w in text for w in ("best in the world", "#1", "world's leading")):
            findings.append(
                ClaimFinding(
                    claim_text=c.text,
                    passage=c.passage,
                    location=c.location,
                    state="contradicted",
                    explanation="Absolute supremacy ranking claim contradicts third-party market share evaluations.",
                    why_it_matters="Unqualified supremacy declarations require audited independent industry market reports.",
                    evidence_source_url=None,
                    evidence_excerpt=None,
                    evidence_quality="none",
                    uncertainty_note="Global supremacy declaration lacks mandatory audited market share evidence.",
                    suggested_fix="a top-tier market provider",
                    external_sources=[],
                )
            )
        elif any(w in text for w in ("guaranteed", "100% uptime", "zero failure")):
            findings.append(
                ClaimFinding(
                    claim_text=c.text,
                    passage=c.passage,
                    location=c.location,
                    state="insufficient_evidence",
                    explanation="Absolute guarantee statement lacks SLA contract and exclusions disclosures.",
                    why_it_matters="Absolute outcome promises without SLA qualification create legal breach liability.",
                    evidence_source_url=None,
                    evidence_excerpt=None,
                    evidence_quality="none",
                    uncertainty_note="Guarantees require explicit limitation disclosures.",
                    suggested_fix="targeted high availability",
                    external_sources=[],
                )
            )
        else:
            findings.append(
                ClaimFinding(
                    claim_text=c.text,
                    passage=c.passage,
                    location=c.location,
                    state="supported",
                    explanation="Factual statement conforms to standard descriptive business communications.",
                    why_it_matters="Clear and truthful communication reinforces audience trust.",
                    evidence_source_url=None,
                    evidence_excerpt=None,
                    evidence_quality="none",
                    uncertainty_note=None,
                    suggested_fix=None,
                    external_sources=[],
                )
            )

    return ClaimVerificationOutput(findings=findings)
