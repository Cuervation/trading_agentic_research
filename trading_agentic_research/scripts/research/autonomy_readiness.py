"""Autonomy readiness score for the trading research loop.

All repository-relative paths are resolved from repo_root, so this command can be
run from any working directory without false negatives.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


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
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--registry", default="configs/strategy_registry.json")
    p.add_argument("--repo-root", default=str(ROOT))
    args = p.parse_args()
    print(json.dumps(
        compute_readiness(state_dir=args.state_dir, registry_path=args.registry, repo_root=args.repo_root),
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
