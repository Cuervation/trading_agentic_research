"""Generate a strategy config from a hypothesis + parent config (auditable, non-random)."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_hypotheses_from_bibliography import validate_candidate_basis
from scripts.research_loop import read_jsonl


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def deep_merge(base: dict, overrides: dict) -> dict:
    """Deep merge overrides into base (dicts only)."""
    merged = deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def generate_strategy_config_from_hypothesis(*, hypothesis: dict, parent_strategy_config: dict) -> dict:
    """Return a new strategy config dict from an explicit override patch."""
    validate_candidate_basis(hypothesis)
    overrides = hypothesis.get("strategy_overrides")
    if not isinstance(overrides, dict) or not overrides:
        raise ValueError("Hypothesis must include non-empty strategy_overrides to generate a strategy config.")

    generated = deep_merge(parent_strategy_config, overrides)
    generated["parent_strategy_id"] = str(parent_strategy_config.get("strategy_id"))

    # Strategy id must identify the candidate, not the parent. If the hypothesis does not
    # explicitly override strategy_id, default to hypothesis_id.
    if "strategy_id" not in overrides:
        generated["strategy_id"] = str(hypothesis["hypothesis_id"])

    generated.setdefault(
        "strategy_family",
        parent_strategy_config.get("strategy_family") or hypothesis.get("family"),
    )
    generated["hypothesis_id"] = str(hypothesis["hypothesis_id"])

    generated.setdefault("bibliography_basis", [])
    generated.setdefault("empirical_basis", [])
    return generated


def upsert_strategy_registry(
    *,
    registry_path: str | Path,
    strategy_id: str,
    config_path: str,
    strategy_family: str,
    status: str = "candidate",
    notes: str = "",
) -> dict:
    path = Path(registry_path)
    registry = (
        read_json(path)
        if path.exists()
        else {"project_name": "trading_agentic_research", "version": 1, "strategies": []}
    )

    strategies = registry.setdefault("strategies", [])
    for row in strategies:
        if row.get("strategy_id") == strategy_id:
            row.update(
                {
                    "strategy_family": strategy_family,
                    "status": status,
                    "config_path": config_path,
                    "notes": notes or row.get("notes", ""),
                }
            )
            write_json(path, registry)
            return registry

    strategies.append(
        {
            "strategy_id": strategy_id,
            "strategy_family": strategy_family,
            "status": status,
            "benchmark_ticker": "SPY",
            "config_path": config_path,
            "signal_frequency": "weekly",
            "execution_frequency": "daily",
            "rebalance_frequency": "monthly",
            "notes": notes,
        }
    )
    write_json(path, registry)
    return registry


def _find_hypothesis(hypothesis_id: str, hypothesis_bank: str | Path) -> dict | None:
    for row in read_jsonl(hypothesis_bank):
        if row.get("hypothesis_id") == hypothesis_id:
            return row
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a strategy config from hypothesis + parent strategy config.")
    p.add_argument("--hypothesis-id", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--output-config", required=True)
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--notes", default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    hypothesis = _find_hypothesis(args.hypothesis_id, args.hypothesis_bank)
    if hypothesis is None:
        raise FileNotFoundError(f"Hypothesis not found: {args.hypothesis_id}")

    parent_cfg = read_json(args.parent_strategy_config)
    generated = generate_strategy_config_from_hypothesis(hypothesis=hypothesis, parent_strategy_config=parent_cfg)
    write_json(args.output_config, generated)

    upsert_strategy_registry(
        registry_path=args.strategy_registry,
        strategy_id=str(generated.get("strategy_id")),
        config_path=str(Path(args.output_config).as_posix()),
        strategy_family=str(generated.get("strategy_family")),
        status="candidate",
        notes=args.notes,
    )

    print(f"Generated strategy config: {args.output_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
