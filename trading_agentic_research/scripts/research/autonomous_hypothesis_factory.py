"""Value-oriented hypothesis fallback.

When the normal hypothesis generator returns no_new_candidates, generate a small
set of auditable hypotheses from the current champion/parent. This avoids random
search and avoids stopping the loop without value.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def existing_ids(bank: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("hypothesis_id")) for row in bank if row.get("hypothesis_id")}


def existing_override_sigs(bank: list[dict[str, Any]]) -> set[str]:
    sigs = set()
    for row in bank:
        overrides = row.get("strategy_overrides")
        if isinstance(overrides, dict) and overrides:
            sigs.add(stable_json(overrides))
    return sigs


def deep_get(d: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def deep_set(d: dict[str, Any], path: tuple[str, ...], value: Any) -> dict[str, Any]:
    cur = d
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value
    return d


@dataclass(frozen=True)
class Spec:
    suffix: str
    family: str
    axis: str
    path: tuple[str, ...]
    value: Any
    claim: str
    source_id: str
    principle_id: str
    falsification_rule: str


def specs_from_parent(parent: dict[str, Any]) -> list[Spec]:
    top_n = int(deep_get(parent, ("entry_rule", "top_n"), 8) or 8)
    rank = int(deep_get(parent, ("exit_rule", "rank_threshold"), 24) or 24)

    specs: list[Spec] = []
    for value in [max(3, top_n - 4), max(3, top_n - 2), top_n + 2, top_n + 4, 5, 7, 9, 11, 13, 15]:
        if value == top_n:
            continue
        specs.append(Spec(
            suffix=f"TOPN_{value}",
            family="time_series_momentum_refinement",
            axis="concentration",
            path=("entry_rule", "top_n"),
            value=value,
            claim=f"Refinar el champion con top_n={value} prueba concentración/diversificación del edge de momentum.",
            source_id="time_series_momentum_general",
            principle_id="trend_persistence_concentration_diversification",
            falsification_rule="Rechazar si no mejora CAGR/drawdown frente al parent o si duplica artefactos históricos.",
        ))

    for value in [max(3, rank - 8), max(3, rank - 4), rank + 4, rank + 8, 12, 18, 24, 32]:
        if value == rank:
            continue
        specs.append(Spec(
            suffix=f"EXIT_{value}",
            family="time_series_momentum_refinement",
            axis="exit_threshold",
            path=("exit_rule", "rank_threshold"),
            value=value,
            claim=f"Refinar el champion con rank_threshold={value} prueba cortar deterioro vs dejar correr ganadores.",
            source_id="trend_following_general",
            principle_id="cut_losers_let_winners_run",
            falsification_rule="Rechazar si empeora CAGR y no mejora drawdown/consistencia contra SPY.",
        ))

    for value in [14, 18, 22, 26]:
        specs.append(Spec(
            suffix=f"TRAILING_{value}",
            family="risk_control_refinement",
            axis="risk_management",
            path=("risk_management", "trailing_stop_pct"),
            value=value,
            claim=f"Agregar trailing_stop_pct={value} al champion prueba control de riesgo incremental.",
            source_id="risk_management_general",
            principle_id="trailing_stop_risk_control",
            falsification_rule="Rechazar si reduce demasiado CAGR o genera duplicado/no-effect.",
        ))
    return specs


def generate_value_hypotheses(
    *,
    parent_strategy_config_path: str | Path,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    max_new: int = 8,
    reason: str = "no_eligible_hypothesis",
) -> dict[str, Any]:
    parent = read_json(parent_strategy_config_path, {}) or {}
    if not parent:
        return {"generated": 0, "reason": "missing_parent_config", "parent_strategy_config": str(parent_strategy_config_path)}

    bank = read_jsonl(hypothesis_bank_path)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    parent_run_id = current.get("current_parent_run_id") or "PARENT"
    parent_hypothesis_id = current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id")

    rows = []
    for spec in specs_from_parent(parent):
        if len(rows) >= max_new:
            break
        hypothesis_id = f"HYP_AUTOREFINE_{parent_run_id}_{spec.suffix}_V1"
        if hypothesis_id in ids:
            continue
        overrides: dict[str, Any] = {}
        deep_set(overrides, spec.path, spec.value)
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", parent.get("strategy_family") or spec.family)
        sig = stable_json(overrides)
        if sig in sigs:
            continue
        row = {
            "hypothesis_id": hypothesis_id,
            "family": spec.family,
            "claim": spec.claim,
            "bibliography_basis": [{"source_id": spec.source_id, "principle_id": spec.principle_id}],
            "empirical_basis": [{"run_id": parent_run_id, "hypothesis_id": parent_hypothesis_id, "reason": f"Generated because {reason}; one-axis refinement: {spec.axis}."}],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "axis": spec.axis,
            "falsification_rule": spec.falsification_rule,
            "strategy_overrides": overrides,
        }
        rows.append(row)
        ids.add(hypothesis_id)
        sigs.add(sig)

    if rows:
        append_jsonl(hypothesis_bank_path, rows)
    return {
        "generated": len(rows),
        "reason": "autonomous_value_hypotheses_generated" if rows else "no_new_value_hypotheses",
        "hypotheses": [row["hypothesis_id"] for row in rows],
        "parent_strategy_config": str(parent_strategy_config_path),
        "parent_run_id": parent_run_id,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-new", type=int, default=8)
    p.add_argument("--reason", default="manual")
    args = p.parse_args()
    print(json.dumps(generate_value_hypotheses(
        parent_strategy_config_path=args.parent_strategy_config,
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=args.max_new,
        reason=args.reason,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
