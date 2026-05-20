"""Autonomy readiness checks for the trading research loop.

This preserves the original score-style readiness function and adds stricter
continuation checks used by autonomy_orchestrator.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.research_policy import load_research_policy


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def _resolve_repo_path(path: str | Path | None, repo_root: str | Path) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo_root) / p
    return p


def compute_readiness(
    *,
    state_dir: str | Path = "state",
    registry_path: str | Path = "configs/strategy_registry.json",
    repo_root: str | Path = ROOT,
) -> dict[str, Any]:
    repo = Path(repo_root)
    state = _resolve_repo_path(state_dir, repo) or (repo / "state")
    registry_file = _resolve_repo_path(registry_path, repo) or (repo / "configs/strategy_registry.json")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, weight: int, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "weight": weight, "detail": detail})

    parent = read_json(state / "current_parent.json", {}) or {}
    parent_config = parent.get("current_parent_config_path")
    parent_config_path = _resolve_repo_path(parent_config, repo)
    add("current_parent_set", bool(parent.get("current_parent_run_id")), 10, str(parent.get("current_parent_run_id")))
    add("parent_config_exists", bool(parent_config_path and parent_config_path.exists()), 12, str(parent_config))

    registry = read_json(registry_file, {}) or {}
    strategies = registry.get("strategies", []) if isinstance(registry, dict) else []
    parent_id = parent.get("current_parent_strategy_id")
    registered = any(str(row.get("strategy_id")) == str(parent_id) for row in strategies)
    add("parent_registered_in_strategy_registry", registered, 8, str(parent_id))

    data = read_json(state / "data_paths_resolved.json", {}) or {}
    add("data_paths_resolved", bool(data.get("can_run")), 10, str(data.get("source")))

    blocker = read_json(state / "autonomy_blocker.json", {}) or {}
    add("no_active_blocker", blocker.get("status") in {None, "clear", ""} or not blocker, 12, str(blocker.get("reason")))

    ledger = read_jsonl(state / "research_ledger.jsonl")
    artifact_index = read_json(state / "artifact_hash_index.json", {}) or {}
    add("research_ledger_populated", len(ledger) > 0, 8, f"events={len(ledger)}")
    add("artifact_index_populated", bool(artifact_index), 8, "artifact index exists" if artifact_index else "missing/empty")

    hyp_bank = repo / "bibliography/hypothesis_bank.jsonl"
    paper_ideas = repo / "bibliography/paper_ideas.jsonl"
    add("hypothesis_bank_exists", hyp_bank.exists() and hyp_bank.stat().st_size > 0, 8, str(hyp_bank))
    add("paper_ideas_available", paper_ideas.exists() and paper_ideas.stat().st_size > 0, 5, str(paper_ideas))

    missing_tasks = read_jsonl(state / "missing_feature_tasks.jsonl")
    feature_plan = repo / "reports/feature_engineering_plan.md"
    add("missing_features_have_plan_or_none", (not missing_tasks) or feature_plan.exists(), 7, f"tasks={len(missing_tasks)}")

    batch_state = read_json(state / "batch_state.json", {}) or {}
    if batch_state:
        add(
            "last_batch_not_zero_iteration_success",
            int(batch_state.get("completed", 0) or 0) > 0 or batch_state.get("status") not in {"completed"},
            10,
            f"completed={batch_state.get('completed')}; status={batch_state.get('status')}",
        )

    max_score = sum(c["weight"] for c in checks)
    score = sum(c["weight"] for c in checks if c["ok"])
    pct = round((score / max_score * 100) if max_score else 0, 2)
    return {
        "score": score,
        "max_score": max_score,
        "readiness_pct": pct,
        "status": "ready" if pct >= 85 else "needs_attention",
        "failed_checks": [c for c in checks if not c["ok"]],
        "checks": checks,
    }


def validate_autonomy_readiness(
    *,
    state_dir: str | Path,
    runs_dir: str | Path,
    reports_dir: str | Path,
    hypothesis_bank: str | Path,
    final_eligibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    parent = read_json(state / "current_parent.json", {}) or {}
    candidate = read_json(state / "candidate_under_review.json", {}) or {}
    blocker = read_json(state / "autonomy_blocker.json", {}) or {}
    plan = read_json(state / "research_expansion_plan.json", {}) or {}
    missing = read_json(state / "missing_feature_priority.json", {}) or {}
    feature_plan = Path(reports_dir) / "feature_engineering_plan.md"
    policy = load_research_policy()
    eligibility = final_eligibility or eligible_hypothesis_preflight(hypothesis_bank=hypothesis_bank, state_dir=state_dir)
    effective = eligibility.get("effective_summary") if isinstance(eligibility.get("effective_summary"), dict) else {}
    executable_sample = effective.get("executable_sample") or []
    checks = {
        "parent_locked": parent.get("current_parent_run_id") == "AUTO_002" and bool(parent.get("parent_promotion_blocked")),
        "candidate_consistent": candidate.get("status") in {"review_exhausted", "active", "disabled", None},
        "baseline_manual": bool(policy.get("promotion_policy", {}).get("baseline_promotion_requires_manual_review", True)),
        "no_auto_move_parent": bool(parent.get("parent_updates_require_manual_approval", True)),
        "has_plan_when_blocked": bool(plan) if blocker.get("status") == "blocked" else True,
        "has_missing_feature_priorities_or_no_tasks": (
            bool(missing.get("priorities"))
            or feature_plan.exists()
            or not (state / "missing_feature_tasks.jsonl").exists()
        ),
        "ready_only_if_selector_eligible": not eligibility.get("eligible") or eligibility.get("reason") == "selector_found_eligible_hypothesis",
        "no_exhausted_fspace_eligible": not any(str(x).startswith("HYP_FSPACE") for x in executable_sample),
    }
    return {"ok": all(checks.values()), "checks": checks, "eligibility": eligibility, "blocker": blocker, "parent": parent, "candidate": candidate}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--registry", default="configs/strategy_registry.json")
    p.add_argument("--repo-root", default=str(ROOT))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_autonomy_readiness(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir, hypothesis_bank=args.hypothesis_bank)
    result["scorecard"] = compute_readiness(state_dir=args.state_dir, registry_path=args.registry, repo_root=args.repo_root)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
