"""Uncertainty evaluation for flags."""

UNCERTAIN_STATES = {"unclear", "contradicted", "insufficient_evidence"}


def needs_human(state: str) -> bool:
    """Return True if the flag state requires human review."""
    return state in UNCERTAIN_STATES

