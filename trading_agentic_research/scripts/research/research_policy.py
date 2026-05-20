"""Central research policy for autonomous trading research.

This module keeps high-level governance in one place. It is intentionally simple:
- load a JSON policy with sane defaults;
- block risky autonomous launch settings;
- validate that a completed batch actually delivered work.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "objective": "Improve robust SPY-relative performance without sacrificing drawdown for marginal CAGR.",
    "autonomous_controls": {
        "max_runs_without_manual_review": 120,
        "allow_parent_update_by_default": False,
        "require_completed_iterations_gt_zero": True,
        "block_zero_iteration_success": True,
    },
    "promotion_policy": {
        "baseline_promotion_requires_manual_review": True,
        "parent_update_requires_explicit_flag": True,
        "prefer_best_champion_as_parent": True,
    },
    "evaluation_priorities": {
        "robustness_52w_over_short_term": True,
        "compare_against_spy_monthly_and_yearly": True,
        "avoid_large_drawdown_regression_for_small_cagr_gain": True,
    },
}


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def load_research_policy(path: str | Path = "governance/research_policy.json", *, repo_root: str | Path = ".") -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo_root) / p
    policy = read_json(p, None)
    if not isinstance(policy, dict):
        return DEFAULT_POLICY
    merged = json.loads(json.dumps(DEFAULT_POLICY))
    for section, value in policy.items():
        if isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section].update(value)
        else:
            merged[section] = value
    return merged


def validate_autonomous_launch(*, policy: dict[str, Any], allow_parent_update: bool, max_runs: int) -> dict[str, Any]:
    controls = policy.get("autonomous_controls", {}) or {}
    promotion = policy.get("promotion_policy", {}) or {}
    errors: list[str] = []
    warnings: list[str] = []

    max_without_review = int(controls.get("max_runs_without_manual_review", 20) or 20)
    if max_runs > max_without_review:
        errors.append(
            f"Requested max_runs={max_runs}, above policy max_runs_without_manual_review={max_without_review}. Run smaller batches or update policy after review."
        )

    if allow_parent_update and promotion.get("parent_update_requires_explicit_flag", True):
        warnings.append("allow_parent_update was explicitly requested; verify this is intentional and audited.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "next_action": "Reduce --max-runs or update governance/research_policy.json after manual review.",
    }


def validate_post_batch(
    *,
    policy: dict[str, Any],
    batch_state: dict[str, Any],
    allow_zero_iterations: bool = False,
    requested_max_runs: int | None = None,
) -> dict[str, Any]:
    controls = policy.get("autonomous_controls", {}) or {}
    require_gt_zero = bool(controls.get("require_completed_iterations_gt_zero", True))
    completed = int(batch_state.get("completed", 0) or 0)
    status = str(batch_state.get("status", ""))
    stop_reason = batch_state.get("stop_reason")

    if require_gt_zero and completed <= 0 and not allow_zero_iterations:
        return {
            "ok": False,
            "reason": "batch_completed_zero_iterations",
            "errors": [
                "run_research_batch.py returned success but completed zero iterations.",
                f"batch_status={status}; stop_reason={stop_reason}",
            ],
            "warnings": [],
            "next_action": "Inspect state/batch_state.json, hypothesis eligibility, cooldowns, missing_feature_tasks.jsonl and generation fallbacks.",
        }

    warnings: list[str] = []
    if requested_max_runs and completed < requested_max_runs:
        warnings.append(f"Batch completed {completed}/{requested_max_runs} iterations; stop_reason={stop_reason}")

    return {
        "ok": True,
        "reason": "post_batch_validation_passed",
        "errors": [],
        "warnings": warnings,
        "completed": completed,
        "status": status,
        "stop_reason": stop_reason,
    }
