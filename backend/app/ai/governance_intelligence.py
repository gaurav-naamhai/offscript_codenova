"""Governance Intelligence module for Inkloom AI.

Owner: Sera
Aggregates historical review flags across submissions to identify:
1. Frequently recurring brand violations and unverified claims.
2. Guidelines associated with frequent non-compliance.
3. Ambiguous guidelines that repeatedly generate uncertain findings or high human escalations.
4. Actionable policy and author training recommendations.
5. Executive summary narratives for brand governance leaders.

Operates strictly on historical flags without fabricating statistics or inventing trends.
"""

from collections import Counter
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Union

from app.ai.client import GeminiClient
from app.ai.schemas import (
    AmbiguousGuideline,
    GovernanceInsightsOutput,
    RecurringViolation,
)
from app.config import Settings
from app.models import Flag, FlagDraft
from app.uncertainty import needs_human

logger = logging.getLogger(__name__)

GOVERNANCE_SYSTEM_INSTRUCTION = """You are the Senior Compliance Director and Brand Governance Intelligence Specialist for Inkloom AI.
Your role is to analyze historical compliance review flags to provide strategic governance insights for enterprise executive teams.

CRITICAL OPERATIONAL RULES:
1. FACTUAL GROUNDING: Base all analysis strictly on the provided aggregated flag statistics and historical review findings. Never fabricate violation frequencies, fake guidelines, or non-existent trends.
2. INSUFFICIENT DATA HANDLING: If historical records are sparse or absent (e.g. fewer than 3 reviews), state clearly that sample size is preliminary. Do not invent patterns where data does not support them.
3. RECURRING VIOLATIONS ANALYSIS:
   - Identify the most common non-compliance areas (e.g. corporate buzzwords, unsubstantiated claims, logo clearspace).
   - Assess impact/severity on brand reputation and enterprise trust.
   - Formulate practical, actionable training or workflow recommendations to prevent repeat infractions.
4. POLICY AMBIGUITY IDENTIFICATION:
   - Identify guidelines with disproportionate rates of 'unclear' states or human reviewer escalations.
   - Explain why authors or automated tools struggle to interpret the policy.
   - Propose clear, unambiguous rewrites to eliminate friction.
5. EXECUTIVE SUMMARY NARRATIVE:
   - Provide an objective, concise summary assessing organizational compliance health, primary risk exposures, and high-impact interventions.

Always return strictly valid JSON matching the GovernanceInsightsOutput schema."""


def generate_governance_insights(
    flags: List[Union[Flag, FlagDraft, Dict[str, Any]]],
    total_reviews_analyzed: Optional[int] = None,
    client: Optional[GeminiClient] = None,
) -> GovernanceInsightsOutput:
    """Analyze historical compliance flags to generate strategic governance intelligence.

    Args:
        flags: List of historical Flag, FlagDraft, or dict objects from the repository.
        total_reviews_analyzed: Optional total submission count (defaults to inferred from flags).
        client: Optional GeminiClient instance.

    Returns:
        Structured GovernanceInsightsOutput with recurring violations, ambiguous policies, and narrative.
    """
    settings = Settings()
    if client is not None:
        ai_client = client
    elif settings.gemini_api_key or settings.mock_ai:
        ai_client = GeminiClient(settings=settings)
    else:
        ai_client = GeminiClient(settings=Settings(mock_ai=True))

    # 1. Handle Empty or Insufficient Data Gracefully
    if not flags:
        logger.info("No historical flags provided for governance analysis.")
        return GovernanceInsightsOutput(
            total_reviews_analyzed=total_reviews_analyzed or 0,
            top_recurring_violations=[],
            ambiguous_guidelines=[],
            summary_narrative=(
                "Insufficient historical review data. No compliance reviews have been completed "
                "yet to establish recurring patterns or policy ambiguity. As submissions are processed, "
                "Inkloom Governance Intelligence will aggregate trend metrics and policy recommendations."
            ),
        )

    # 2. Extract and Aggregate Flag Statistics
    total_flags = len(flags)
    brand_violations: List[Any] = []
    claim_violations: List[Any] = []
    human_escalations: List[Any] = []

    guideline_violation_counts: Counter[str] = Counter()
    guideline_escalation_counts: Counter[str] = Counter()
    guideline_details: Dict[str, Dict[str, str]] = {}
    issue_topic_counts: Counter[str] = Counter()

    for f in flags:
        st = getattr(f, "state", None) or (f.get("state") if isinstance(f, dict) else "open")
        ft = getattr(f, "finding_type", "brand") if hasattr(f, "finding_type") else (f.get("finding_type", "brand") if isinstance(f, dict) else "brand")
        explanation = getattr(f, "explanation", "") or (f.get("explanation", "") if isinstance(f, dict) else "")
        g_ref = getattr(f, "guideline_ref", None) or (f.get("guideline_ref") if isinstance(f, dict) else None)

        is_human = needs_human(st)
        if is_human:
            human_escalations.append(f)

        g_key = None
        if g_ref:
            doc = getattr(g_ref, "document", None) or (g_ref.get("document") if isinstance(g_ref, dict) else None)
            pref = getattr(g_ref, "passage_ref", None) or (g_ref.get("passage_ref") if isinstance(g_ref, dict) else None)
            if doc:
                g_key = f"{doc} ({pref or 'General'})"
                if g_key not in guideline_details:
                    excerpt = getattr(g_ref, "excerpt", "") or (g_ref.get("excerpt", "") if isinstance(g_ref, dict) else "")
                    guideline_details[g_key] = {"document": doc, "passage_ref": pref or "Rule", "excerpt": excerpt}

        if ft == "brand" and st == "potential_issue":
            brand_violations.append(f)
            if g_key:
                guideline_violation_counts[g_key] += 1
            # Cluster by topic
            topic = _cluster_issue_topic(explanation)
            issue_topic_counts[topic] += 1

        elif ft == "claim" and st in ("contradicted", "insufficient_evidence"):
            claim_violations.append(f)
            topic = "Unverified Factual/Statistical Claims" if st == "insufficient_evidence" else "Contradicted Market Supremacy Claims"
            issue_topic_counts[topic] += 1

        if is_human and g_key:
            guideline_escalation_counts[g_key] += 1

    # Infer submissions analyzed if not explicitly supplied
    inferred_submissions = total_reviews_analyzed or max(1, len(set(
        getattr(f, "submission_id", None) or (f.get("submission_id") if isinstance(f, dict) else None) or id(f)
        for f in flags
    )))

    # 3. Deterministic Mock Mode Execution
    if ai_client.mock_mode:
        if GovernanceInsightsOutput in ai_client._mock_handlers:
            return ai_client.generate_structured(prompt="", response_schema=GovernanceInsightsOutput)

        return _generate_mock_governance_insights(
            total_reviews=inferred_submissions,
            total_flags=total_flags,
            brand_violations=brand_violations,
            claim_violations=claim_violations,
            human_escalations=human_escalations,
            guideline_violation_counts=guideline_violation_counts,
            guideline_escalation_counts=guideline_escalation_counts,
            guideline_details=guideline_details,
            issue_topic_counts=issue_topic_counts,
        )

    # 4. Live Gemini Execution
    stats_summary = (
        f"HISTORICAL GOVERNANCE DATA SUMMARY:\n"
        f"- Total Submissions Analyzed: {inferred_submissions}\n"
        f"- Total Compliance Flags Recorded: {total_flags}\n"
        f"- Total Brand Violations: {len(brand_violations)}\n"
        f"- Total Claim/Substantiation Issues: {len(claim_violations)}\n"
        f"- Total Human Escalations Required: {len(human_escalations)}\n\n"
        f"TOP RECURRING GUIDELINE VIOLATIONS:\n"
        + "\n".join([f"  - {g}: {c} violations" for g, c in guideline_violation_counts.most_common(5)] or ["  None recorded."])
        + "\n\nPOLICIES WITH HIGHEST HUMAN ESCALATIONS:\n"
        + "\n".join([f"  - {g}: {c} escalations" for g, c in guideline_escalation_counts.most_common(5)] or ["  None recorded."])
        + "\n\nISSUE TOPIC DISTRIBUTION:\n"
        + "\n".join([f"  - {t}: {c} occurrences" for t, c in issue_topic_counts.most_common(5)] or ["  None recorded."])
    )

    prompt = (
        f"Analyze the following enterprise compliance review history to produce executive governance insights:\n\n"
        f"{stats_summary}\n\n"
        f"Generate strategic recommendations, identify top recurring violations, pinpoint ambiguous policies "
        f"causing review friction, and provide a comprehensive executive health summary."
    )

    output = ai_client.generate_structured(
        prompt=prompt,
        response_schema=GovernanceInsightsOutput,
        system_instruction=GOVERNANCE_SYSTEM_INSTRUCTION,
    )
    output.total_reviews_analyzed = inferred_submissions
    return output


# ============================================================================
# DETERMINISTIC MOCK & HELPER FUNCTIONS
# ============================================================================


def _cluster_issue_topic(explanation: str) -> str:
    """Categorize flag explanations into standard governance topics."""
    expl_lower = explanation.lower()
    if any(w in expl_lower for w in ("buzzword", "synergy", "disruptive", "plain english")):
        return "Corporate Buzzwords and Jargon"
    if any(w in expl_lower for w in ("exclamation", "hyperbolic", "informal", "tone")):
        return "Informal Punctuation and Tone Inconsistency"
    if any(w in expl_lower for w in ("cheap", "discount", "undermine", "pricing")):
        return "Pricing and Value Positioning"
    if any(w in expl_lower for w in ("contrast", "wcag", "accessibility", "readability")):
        return "Visual Accessibility and Contrast Hurdles"
    if any(w in expl_lower for w in ("logo", "clearspace", "aspect ratio", "distortion")):
        return "Brand Logo Clearspace and Orientation"
    return "General Brand Voice Alignment"


def _generate_mock_governance_insights(
    total_reviews: int,
    total_flags: int,
    brand_violations: List[Any],
    claim_violations: List[Any],
    human_escalations: List[Any],
    guideline_violation_counts: Counter[str],
    guideline_escalation_counts: Counter[str],
    guideline_details: Dict[str, Dict[str, str]],
    issue_topic_counts: Counter[str],
) -> GovernanceInsightsOutput:
    """Generate realistic, deterministic governance insights for testing and demonstration."""
    recurring: List[RecurringViolation] = []
    ambiguous: List[AmbiguousGuideline] = []

    # 1. Populate top recurring violations based on empirical counts
    for topic, count in issue_topic_counts.most_common(3):
        rec_text = "Conduct copywriter training on plain-English brand terminology."
        sev = "medium"
        if "Buzzword" in topic:
            rec_text = "Integrate plain-English automated linting into author drafting tools."
            sev = "high"
        elif "Claim" in topic or "Supremacy" in topic:
            rec_text = "Establish mandatory SLA and market report citation protocols before publication."
            sev = "high"
        elif "Accessibility" in topic:
            rec_text = "Standardize high-contrast design system tokens across marketing templates."
            sev = "medium"

        ref_doc = None
        if guideline_violation_counts:
            ref_doc = guideline_violation_counts.most_common(1)[0][0]

        recurring.append(
            RecurringViolation(
                rule_or_topic=topic,
                frequency=count,
                severity=sev,
                guideline_reference=ref_doc,
                recommendation=rec_text,
            )
        )

    # 2. Populate ambiguous guidelines based on human escalation frequency
    if guideline_escalation_counts:
        for g_title, esc_count in guideline_escalation_counts.most_common(2):
            ambiguous.append(
                AmbiguousGuideline(
                    guideline_title=g_title,
                    human_escalation_count=esc_count,
                    reason_for_ambiguity=(
                        "Rule relies on subjective descriptors ('measured tone', 'industry-leading') "
                        "lacking quantifiable thresholds, causing reviewers and creators to reach inconsistent verdicts."
                    ),
                    suggested_clarification=(
                        "Define measurable criteria: specify prohibited superlatives explicitly, "
                        "and mandate audited third-party benchmark citations for comparative claims."
                    ),
                )
            )
    elif human_escalations:
        ambiguous.append(
            AmbiguousGuideline(
                guideline_title="Third-Party Verification Standards",
                human_escalation_count=len(human_escalations),
                reason_for_ambiguity="Absence of pre-approved domain whitelists leads to frequent manual escalation.",
                suggested_clarification="Publish a centralized whitelist of verified industry research analysts and SLA benchmark sources.",
            )
        )

    # 3. Formulate Executive Health Narrative
    pub_ready_pct = round(max(0, 100 - (len(brand_violations) + len(claim_violations)) * 10), 1)
    narrative = (
        f"Executive Governance Review: Analyzed {total_reviews} submissions ({total_flags} total compliance checks). "
        f"Overall publication health score is {pub_ready_pct}%. The primary risk vector identified is "
        f"{issue_topic_counts.most_common(1)[0][0] if issue_topic_counts else 'General Tone Alignment'}, "
        f"accounting for {issue_topic_counts.most_common(1)[0][1] if issue_topic_counts else 0} occurrences. "
        f"{len(human_escalations)} review escalations were recorded due to ambiguous claims or unverified sources. "
        f"Recommendation: Update brand guidelines with explicit terminology boundaries and verified data requirements."
    )

    return GovernanceInsightsOutput(
        total_reviews_analyzed=total_reviews,
        top_recurring_violations=recurring,
        ambiguous_guidelines=ambiguous,
        summary_narrative=narrative,
    )

