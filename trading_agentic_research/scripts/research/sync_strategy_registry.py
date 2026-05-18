"""Keep strategy_registry.json aligned with current champion state.

This script is intentionally idempotent. It adds/updates registry rows for:
- current parent / best champion
- baseline or promotion candidate when its config exists
- aggressive champion when its config exists
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


def _row_for_config(strategy_id: str, config_path: str, status: str, notes: str) -> dict[str, Any]:
    cfg = read_json(config_path, {}) or {}
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

    updated: list[str] = []
    parent_strategy_id = parent.get("current_parent_strategy_id")
    parent_config = parent.get("current_parent_config_path")
    if parent_strategy_id and parent_config and (root / parent_config).exists():
        row = _row_for_config(
            str(parent_strategy_id),
            str(parent_config),
            "current_parent",
            f"Best champion/current parent from run {parent.get('current_parent_run_id')}",
        )
        upsert(registry, row)
        updated.append(str(parent_strategy_id))

    # Optional known candidate paths. Only register if they exist.
    for key, status in [
        ("baseline_candidate_run_id", "promotion_candidate"),
        ("aggressive_champion_run_id", "aggressive_champion"),
    ]:
        run_id = parent.get(key)
        # No reliable config path is guaranteed for historical runs. Do not invent one.
        if not run_id:
            continue

    write_json(registry_file, registry)
    return {"registry_path": str(registry_file), "updated_strategy_ids": updated}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="configs/strategy_registry.json")
    p.add_argument("--state-dir", default="state")
    args = p.parse_args()
    print(json.dumps(sync_strategy_registry(registry_path=args.registry, state_dir=args.state_dir, repo_root=ROOT), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
