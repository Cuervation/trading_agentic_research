"""Keep strategy_registry.json aligned with current champion state.

Idempotently adds/updates registry rows for:
- current parent / best champion
- promotion candidates when config exists
- aggressive/secondary/defensive candidates when config exists

This prevents the loop from knowing about a run in state but not knowing how to
reuse its config.
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


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _norm(path: str | Path) -> str:
    return str(Path(path).as_posix())


def _resolve_config_for_ids(root: Path, strategy_id: str | None, hypothesis_id: str | None, generated_dir: str = "configs/generated") -> str | None:
    names = []
    for value in (hypothesis_id, strategy_id):
        if value and str(value) not in names:
            names.append(str(value))
    for name in names:
        for candidate in (root / generated_dir / f"{name}.json", root / "configs" / f"{name}.json"):
            if candidate.exists():
                try:
                    return _norm(candidate.relative_to(root))
                except ValueError:
                    return _norm(candidate)
    return None


def _row_for_config(root: Path, strategy_id: str, config_path: str, status: str, notes: str) -> dict[str, Any]:
    cfg = read_json(root / config_path, {}) or {}
    return {
        "strategy_id": strategy_id,
        "strategy_family": cfg.get("strategy_family") or "unknown",
        "status": status,
        "benchmark_ticker": cfg.get("benchmark_ticker") or "SPY",
        "config_path": _norm(config_path),
        "signal_frequency": cfg.get("signal_frequency") or "weekly",
        "execution_frequency": cfg.get("execution_frequency") or "daily",
        "rebalance_frequency": cfg.get("rebalance_frequency") or "monthly",
        "notes": notes,
    }


def upsert(registry: dict[str, Any], row: dict[str, Any]) -> None:
    strategies = registry.setdefault("strategies", [])
    for idx, existing in enumerate(strategies):
        if str(existing.get("strategy_id")) == str(row.get("strategy_id")):
            merged = dict(existing)
            merged.update(row)
            strategies[idx] = merged
            return
    strategies.append(row)


def _register_snapshot(root: Path, registry: dict[str, Any], snapshot: dict[str, Any], status: str, notes: str) -> str | None:
    strategy_id = snapshot.get("strategy_id") or snapshot.get("hypothesis_id")
    hypothesis_id = snapshot.get("hypothesis_id") or strategy_id
    if not strategy_id:
        return None
    config_path = snapshot.get("config_path") or snapshot.get("strategy_config_path")
    if not config_path or not (root / str(config_path)).exists():
        config_path = _resolve_config_for_ids(root, str(strategy_id), str(hypothesis_id))
    if not config_path or not (root / str(config_path)).exists():
        return None
    upsert(registry, _row_for_config(root, str(strategy_id), str(config_path), status, notes))
    return str(strategy_id)


def sync_strategy_registry(
    *,
    registry_path: str | Path = "configs/strategy_registry.json",
    state_dir: str | Path = "state",
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(repo_root)
    registry_file = root / registry_path
    registry = read_json(registry_file, {"project_name": "trading_agentic_research", "version": 1, "strategies": []}) or {}
    parent = read_json(root / state_dir / "current_parent.json", {}) or {}
    champions = read_json(root / state_dir / "champion_runs.json", {}) or {}

    updated: list[str] = []
    missing: list[dict[str, Any]] = []

    # Current parent is the most important reusable config.
    parent_strategy_id = parent.get("current_parent_strategy_id")
    parent_config = parent.get("current_parent_config_path")
    if parent_strategy_id and parent_config and (root / parent_config).exists():
        upsert(registry, _row_for_config(
            root,
            str(parent_strategy_id),
            str(parent_config),
            "current_parent",
            f"Best champion/current parent from run {parent.get('current_parent_run_id')}",
        ))
        updated.append(str(parent_strategy_id))
    elif parent_strategy_id:
        missing.append({"strategy_id": parent_strategy_id, "status": "current_parent", "reason": "missing_config"})

    bucket_status = {
        "promotion_candidates": "promotion_candidate",
        "secondary_candidates": "secondary_candidate",
        "defensive_secondary_candidates": "defensive_secondary_candidate",
        "champion_runs": "champion_history",
    }
    for bucket, status in bucket_status.items():
        for row in champions.get(bucket, []) or []:
            sid = _register_snapshot(
                root,
                registry,
                row,
                status,
                f"Synced from champion governance bucket {bucket}; run {row.get('run_id')}",
            )
            if sid:
                updated.append(sid)
            else:
                missing.append({
                    "run_id": row.get("run_id"),
                    "strategy_id": row.get("strategy_id"),
                    "hypothesis_id": row.get("hypothesis_id"),
                    "status": status,
                    "reason": "config_not_found",
                })

    write_json(registry_file, registry)
    return {"registry_path": str(registry_file), "updated_strategy_ids": sorted(set(updated)), "missing_configs": missing}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="configs/strategy_registry.json")
    p.add_argument("--state-dir", default="state")
    args = p.parse_args()
    print(json.dumps(sync_strategy_registry(registry_path=args.registry, state_dir=args.state_dir, repo_root=ROOT), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
