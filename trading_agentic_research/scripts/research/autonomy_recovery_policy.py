"""Recovery policy matrix for autonomous research blockers.

This module is intentionally declarative.  The orchestrator owns control-flow;
handlers own side effects.  A blocker is terminal only after the ordered safe
handlers in this policy have been exhausted under the loop guards.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

GOVERNANCE_FORBIDDEN_ACTIONS = [
    "move_AUTO_002",
    "change_current_parent_without_manual_review",
    "auto_promote_baseline",
    "delete_runs_or_history",
    "rerun_exhausted_HYP_FSPACE",
    "ignore_duplicate_signatures",
    "mutate_original_csv",
    "invent_external_data",
]

DEFAULT_VALIDATIONS = [
    "hypothesis_eligibility",
    "parent_governance_guard",
    "duplicate_signature_guard",
]

TERMINAL_ONLY_IF = [
    "all_safe_handlers_attempted",
    "same_blocker_and_next_action_repeated_twice_without_material_mutation",
    "continuing_would_violate_governance_or_require_unobtainable_external_data",
]


def _policy(
    handlers_ordered: list[str],
    *,
    max_attempts: int = 2,
    material_mutation_required: bool = True,
    terminal_only_if: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    validations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "handlers_ordered": handlers_ordered,
        "max_attempts": max_attempts,
        "material_mutation_required": material_mutation_required,
        "terminal_only_if": terminal_only_if or TERMINAL_ONLY_IF,
        "forbidden_actions": forbidden_actions or GOVERNANCE_FORBIDDEN_ACTIONS,
        "validations": validations or DEFAULT_VALIDATIONS,
    }


RECOVERY_POLICY: dict[str, dict[str, Any]] = {
    "new_literature_family_required": _policy([
        "paper_searcher",
        "literature_template_expander",
        "feature_gap_analyzer",
        "external_data_acquisition",
        "novelty_checker",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "missing_sector_classification_source": _policy([
        "external_data_acquisition",
        "feature_gap_analyzer",
        "literature_template_expander",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "missing_external_data": _policy([
        "external_data_acquisition",
        "feature_gap_analyzer",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "research_space_exhausted": _policy([
        "research_expansion_planner_executor",
        "paper_searcher",
        "literature_template_expander",
        "feature_gap_analyzer",
        "novelty_checker",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "no_eligible_hypotheses": _policy([
        "research_expansion_planner_executor",
        "paper_searcher",
        "literature_template_expander",
        "feature_gap_analyzer",
        "novelty_checker",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "feature_missing": _policy([
        "feature_gap_analyzer",
        "external_data_acquisition",
        "literature_template_expander",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "template_missing": _policy([
        "literature_template_expander",
        "paper_searcher",
        "feature_gap_analyzer",
        "novelty_checker",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "paper_idea_not_convertible": _policy([
        "paper_searcher",
        "literature_template_expander",
        "feature_gap_analyzer",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "duplicate_loop": _policy([
        "novelty_checker",
        "research_expansion_planner_executor",
        "literature_template_expander",
        "hypothesis_eligibility",
    ], max_attempts=2, material_mutation_required=False),
    "zero_iteration_batch": _policy([
        "hypothesis_eligibility",
        "research_expansion_planner_executor",
        "novelty_checker",
    ], max_attempts=2, material_mutation_required=False),
    "runtime_error": _policy([
        "runtime_error",
        "hypothesis_eligibility",
    ], max_attempts=1, material_mutation_required=False),
    "import_error": _policy([
        "runtime_error",
        "hypothesis_eligibility",
    ], max_attempts=1, material_mutation_required=False),
    "data_path_error": _policy([
        "data_path_error",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "config_error": _policy([
        "data_path_error",
        "hypothesis_eligibility",
    ], max_attempts=2),
    "state_inconsistency": _policy([
        "state_inconsistency",
        "hypothesis_eligibility",
    ], max_attempts=1, material_mutation_required=False),
    "policy_blocked": _policy([
        "policy_blocked",
        "hypothesis_eligibility",
    ], max_attempts=1, material_mutation_required=False),
    "governance_risk": _policy([
        "governance_risk",
    ], max_attempts=1, material_mutation_required=False),
    "candidate_found": _policy([
        "candidate_found",
    ], max_attempts=1, material_mutation_required=False, terminal_only_if=["candidate_requires_manual_review"]),
    "unknown_blocker": _policy([
        "hypothesis_eligibility",
        "research_expansion_planner_executor",
        "novelty_checker",
    ], max_attempts=1, material_mutation_required=False),
}


def get_recovery_policy(blocker_type: str | None) -> dict[str, Any]:
    """Return a defensive copy so callers can annotate without global mutation."""
    key = blocker_type if blocker_type in RECOVERY_POLICY else "unknown_blocker"
    return deepcopy(RECOVERY_POLICY[key])


def handlers_for(blocker_type: str | None) -> list[str]:
    return list(get_recovery_policy(blocker_type).get("handlers_ordered") or [])


def all_blocker_types() -> list[str]:
    return sorted(RECOVERY_POLICY)
