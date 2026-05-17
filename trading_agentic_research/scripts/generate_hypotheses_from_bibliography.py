"""Generate and validate hypotheses from bibliography or empirical evidence."""

from __future__ import annotations


def candidate_has_basis(hypothesis: dict) -> bool:
    """Return True when a hypothesis has bibliography or empirical basis."""
    return bool(hypothesis.get("bibliography_basis") or hypothesis.get("empirical_basis"))


def validate_candidate_basis(hypothesis: dict) -> None:
    """Enforce basis rules for candidate generation."""
    if not candidate_has_basis(hypothesis):
        raise ValueError("Candidate requires bibliography_basis or empirical_basis.")

    for item in hypothesis.get("bibliography_basis", []):
        if not isinstance(item, dict) or not item.get("source_id"):
            raise ValueError("Bibliography-based hypotheses must include source_id.")

    for item in hypothesis.get("empirical_basis", []):
        if not isinstance(item, dict) or not (item.get("run_id") or item.get("learning_id")):
            raise ValueError("Empirical hypotheses must include run_id or learning_id.")


def build_hypothesis_card(
    hypothesis_id: str,
    family: str,
    claim: str,
    bibliography_basis: list[dict] | None = None,
    empirical_basis: list[dict] | None = None,
) -> dict:
    """Build a compact hypothesis card and validate its basis."""
    hypothesis = {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "claim": claim,
        "bibliography_basis": bibliography_basis or [],
        "empirical_basis": empirical_basis or [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
    }
    validate_candidate_basis(hypothesis)
    return hypothesis
