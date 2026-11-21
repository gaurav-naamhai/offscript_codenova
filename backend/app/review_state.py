"""Readiness for the current submission version, independent of heuristic scores."""

from typing import Iterable

from app.models import Decision, Flag, Submission


BLOCKING_STATES = {"potential_issue", "contradicted", "insufficient_evidence", "unclear"}


def current_review_state(
    submission: Submission,
    flags: Iterable[Flag],
    decisions: Iterable[Decision] = (),
) -> str:
    current_flags = [flag for flag in flags if flag.version == submission.version]
    if submission.processing_stage in {"failed", "incomplete"} or submission.processing_error:
        return "review_incomplete"
    if submission.status == "ai_review":
        return "review_in_progress"
    if submission.status == "draft" or submission.processing_stage != "completed":
        return "not_checked"
    if any(flag.origin == "error" and flag.status == "open" for flag in current_flags):
        return "review_incomplete"

    blocking = any(
        flag.status == "open" and flag.state in BLOCKING_STATES
        for flag in current_flags
    )
    if submission.status == "approved":
        overridden = any(
            decision.version == submission.version
            and decision.decision == "approve"
            and decision.override_unresolved
            for decision in decisions
        )
        if overridden:
            return "approved_with_override"
        return "changes_required" if blocking else "approved_for_publication"
    return "changes_required" if blocking else "ready_for_human_review"
