"""Value-oriented, ledger-aware hypothesis fallback.

When the normal hypothesis generator returns no_new_candidates, generate a small
set of auditable hypotheses from the current champion/parent. This avoids random
search and avoids stopping the loop without value.

This version is deliberately conservative:
- dedupes by *real* overrides, ignoring metadata like strategy_id;
- uses research_ledger.jsonl to avoid axes that recently generated duplicates;
- still includes bibliography_basis + empirical_basis + falsification_rule.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METADATA_OVERRIDE_KEYS = {
    "strategy_id",
    "strategy_family",
    "hypothesis_id",
    "parent_strategy_id",
    "notes",
    "created_at",
    "updated_at",
}
BAD_VALUE_DELIVERED = {"duplicate_blocked", "metric_no_effect_blocked"}
WEAK_VALUE_DELIVERED = {"rejected_with_learning"}


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
                continue
    return rows


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _strip_metadata(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_metadata(v) for k, v in obj.items() if k not in METADATA_OVERRIDE_KEYS}
    if isinstance(obj, list):
        return [_strip_metadata(v) for v in obj]
    return obj


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def real_override_signature(overrides: dict[str, Any]) -> str:
    return stable_json(_strip_metadata(overrides or {}))


def existing_ids(bank: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("hypothesis_id")) for row in bank if row.get("hypothesis_id")}


def existing_override_sigs(bank: list[dict[str, Any]]) -> set[str]:
    sigs = set()
    for row in bank:
        overrides = row.get("strategy_overrides")
        if isinstance(overrides, dict) and overrides:
            sigs.add(real_override_signature(overrides))
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


def _uniq_specs(specs: list[Spec]) -> list[Spec]:
    seen: set[tuple[tuple[str, ...], str]] = set()
    out: list[Spec] = []
    for spec in specs:
        key = (spec.path, stable_json(spec.value))
        if key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def specs_from_parent(parent: dict[str, Any]) -> list[Spec]:
    top_n = int(deep_get(parent, ("entry_rule", "top_n"), 8) or 8)
    rank = int(deep_get(parent, ("exit_rule", "rank_threshold"), 24) or 24)
    ranking_field = str(deep_get(parent, ("ranking", "field"), "ret_52w_pct") or "ret_52w_pct")

    specs: list[Spec] = []
    for value in [max(3, top_n - 6), max(3, top_n - 4), max(3, top_n - 2), top_n + 2, top_n + 4, top_n + 6, 5, 7, 9, 11, 13, 17, 20]:
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

    for value in [max(3, rank - 10), max(3, rank - 6), max(3, rank - 3), rank + 3, rank + 6, rank + 10, 12, 16, 18, 24, 28, 32]:
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

    for value in [14, 18, 22, 26, 30]:
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

    for field in ["ret_52w_pct", "ret_26w_pct", "close_vs_sma52w_pct", "close_vs_sma20w_pct"]:
        if field == ranking_field:
            continue
        specs.append(Spec(
            suffix=f"RANK_{field.upper()}",
            family="time_series_momentum_refinement",
            axis="ranking_field",
            path=("ranking", "field"),
            value=field,
            claim=f"Cambiar ranking a {field} prueba una definición alternativa de persistencia de tendencia.",
            source_id="time_series_momentum_general",
            principle_id="multi_lookback_momentum_confirmation",
            falsification_rule="Rechazar si la nueva métrica no mejora SPY-relative robustness o si la feature falta.",
        ))
    return _uniq_specs(specs)


def _axis_from_text(row: dict[str, Any]) -> str | None:
    if row.get("axis"):
        return str(row["axis"])
    hyp = str(row.get("hypothesis_id") or "").upper()
    if "TOPN" in hyp or "CONCENTRATION" in hyp:
        return "concentration"
    if "EXIT" in hyp:
        return "exit_threshold"
    if "TRAIL" in hyp or "RISK" in hyp:
        return "risk_management"
    if "RANK" in hyp:
        return "ranking_field"
    return None


def exhausted_axes_from_ledger(state_dir: str | Path, threshold: int = 4) -> set[str]:
    ledger = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    counts: dict[str, int] = {}
    for row in ledger[-75:]:
        value = str(row.get("value_delivered") or "")
        if value not in BAD_VALUE_DELIVERED and value not in WEAK_VALUE_DELIVERED:
            continue
        axis = _axis_from_text(row)
        if not axis:
            continue
        weight = 2 if value in BAD_VALUE_DELIVERED else 1
        counts[axis] = counts.get(axis, 0) + weight
    return {axis for axis, score in counts.items() if score >= threshold}


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
    exhausted_axes = exhausted_axes_from_ledger(state_dir)
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    parent_run_id = current.get("current_parent_run_id") or "PARENT"
    parent_hypothesis_id = current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id")

    rows = []
    skipped_exhausted = []
    for spec in specs_from_parent(parent):
        if len(rows) >= max_new:
            break
        if spec.axis in exhausted_axes:
            skipped_exhausted.append(spec.axis)
            continue
        hypothesis_id = f"HYP_AUTOREFINE_{parent_run_id}_{spec.suffix}_V1"
        if hypothesis_id in ids:
            continue
        overrides: dict[str, Any] = {}
        deep_set(overrides, spec.path, spec.value)
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", parent.get("strategy_family") or spec.family)
        sig = real_override_signature(overrides)
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
        "skipped_exhausted_axes": sorted(set(skipped_exhausted)),
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
