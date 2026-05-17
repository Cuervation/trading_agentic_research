"""Hypothesis generation utilities (bibliography + evidence driven, non-random).

Design goals:
- Never generate candidates without bibliography_basis or empirical_basis.
- Generate small, auditable changes (one axis at a time) with explicit strategy_overrides.
- Avoid duplicates (same axis/value already present in hypothesis_bank).
- Respect family cooldowns (external gating happens in scoring).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AxisMutation:
    axis: str
    override_path: tuple[str, ...]
    value: Any
    bibliography_basis: list[dict]
    claim: str


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _deep_set(d: dict, path: tuple[str, ...], value: Any) -> dict:
    cur = d
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value
    return d


def strategy_override_signature(strategy_overrides: dict) -> str:
    """Return a short signature used for novelty/deduping.

    Important: it intentionally ignores basis fields and focuses on the
    effective override patch.
    """
    return _stable_json(strategy_overrides or {})


def existing_override_signatures(hypothesis_bank: list[dict]) -> set[str]:
    sigs: set[str] = set()
    for h in hypothesis_bank or []:
        overrides = h.get("strategy_overrides")
        if isinstance(overrides, dict) and overrides:
            sigs.add(strategy_override_signature(overrides))
    return sigs


def next_versioned_id(base_id: str, existing_ids: set[str]) -> str:
    """Return base_id if unused; otherwise append _V{n} (n>=2)."""
    if base_id not in existing_ids:
        return base_id
    # If base_id already ends with _Vn, keep base stem and bump.
    stem = base_id
    if "_V" in base_id and base_id.rsplit("_V", 1)[-1].isdigit():
        stem = base_id.rsplit("_V", 1)[0]

    n = 2
    while f"{stem}_V{n}" in existing_ids:
        n += 1
    return f"{stem}_V{n}"


def build_mutations_for_family(*, family: str) -> list[AxisMutation]:
    """Return a small set of predefined, bibliography-justified mutations.

    This is intentionally conservative. Add more axes over time, but keep each
    hypothesis to a single axis change.
    """
    if family == "cross_sectional_momentum":
        return [
            AxisMutation(
                axis="concentration",
                override_path=("entry_rule", "top_n"),
                value=8,
                bibliography_basis=[
                    {"source_id": "academic_momentum_jegadeesh_titman_1993", "principle_id": "academic_momentum_relative_winners"}
                ],
                claim="Test a more concentrated winner basket (top_n=8) to reduce noise/turnover while preserving momentum edge.",
            ),
            AxisMutation(
                axis="concentration",
                override_path=("entry_rule", "top_n"),
                value=12,
                bibliography_basis=[
                    {"source_id": "academic_momentum_jegadeesh_titman_1993", "principle_id": "academic_momentum_relative_winners"}
                ],
                claim="Test a slightly less concentrated basket (top_n=12) to trade off diversification vs momentum edge.",
            ),
            AxisMutation(
                axis="exit_threshold",
                override_path=("exit_rule", "rank_threshold"),
                value=15,
                bibliography_basis=[
                    {"source_id": "trend_following_general", "principle_id": "trend_following_cut_losers"}
                ],
                claim="Tighten rank exit threshold (rank_threshold=15) to cut deteriorating names earlier.",
            ),
            AxisMutation(
                axis="exit_threshold",
                override_path=("exit_rule", "rank_threshold"),
                value=25,
                bibliography_basis=[
                    {"source_id": "trend_following_general", "principle_id": "trend_following_cut_losers"}
                ],
                claim="Loosen rank exit threshold (rank_threshold=25) to reduce churn and allow trends to run longer.",
            ),
        ]

    if family == "tactical_asset_allocation":
        return [
            AxisMutation(
                axis="market_filter",
                override_path=("market_filter", "require_positive_trend"),
                value=True,
                bibliography_basis=[
                    {"source_id": "faber_tactical_asset_allocation", "principle_id": "market_trend_filter"}
                ],
                claim="Enforce a market trend filter gate (risk-off when benchmark trend is negative).",
            )
        ]

    if family == "risk_management":
        return [
            AxisMutation(
                axis="risk_management",
                override_path=("risk_management", "trailing_stop_pct"),
                value=15,
                bibliography_basis=[
                    {"source_id": "risk_management_general", "principle_id": "risk_management_stops"}
                ],
                claim="Test a tighter trailing stop (15%) to reduce drawdowns at the cost of more exits.",
            ),
            AxisMutation(
                axis="risk_management",
                override_path=("risk_management", "trailing_stop_pct"),
                value=25,
                bibliography_basis=[
                    {"source_id": "risk_management_general", "principle_id": "risk_management_stops"}
                ],
                claim="Test a looser trailing stop (25%) to reduce whipsaw while still controlling tail risk.",
            ),
        ]

    return []


def generate_hypotheses_from_parent(
    *,
    family: str,
    parent_strategy_config: dict,
    parent_run_id: str | None,
    parent_learning_id: str | None,
    existing_ids: set[str],
    existing_override_sigs: set[str],
    max_new: int = 6,
) -> list[dict]:
    """Generate new hypotheses (dict rows for hypothesis_bank.jsonl)."""
    mutations = build_mutations_for_family(family=family)
    out: list[dict] = []
    for mut in mutations:
        if len(out) >= max_new:
            break

        overrides = {}
        _deep_set(overrides, mut.override_path, mut.value)

        # Always stamp strategy id deterministically; allow versioning via hypothesis id.
        base_hypothesis_id = f"HYP_{family.upper()}_{mut.axis.upper()}_{str(mut.value).replace('.', '_')}_V1"
        hypothesis_id = next_versioned_id(base_hypothesis_id, existing_ids)

        # Create a strategy_id that mirrors hypothesis_id by default.
        overrides.setdefault("strategy_id", hypothesis_id)
        overrides.setdefault("strategy_family", parent_strategy_config.get("strategy_family") or family)

        # Apply minimal patch only; rest comes from parent_strategy_config at config-gen time.
        strategy_overrides = overrides
        sig = strategy_override_signature(strategy_overrides)
        if sig in existing_override_sigs:
            continue

        row = {
            "hypothesis_id": hypothesis_id,
            "family": family,
            "bibliography_basis": list(mut.bibliography_basis),
            "empirical_basis": (
                [{"run_id": parent_run_id, "learning_id": parent_learning_id}] if (parent_run_id or parent_learning_id) else []
            ),
            "strategy_overrides": strategy_overrides,
            "claim": mut.claim,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        }
        out.append(row)
        existing_ids.add(hypothesis_id)
        existing_override_sigs.add(sig)

    return out


def append_jsonl(path: str | Path, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8-sig") if p.exists() else ""
    with p.open("w", encoding="utf-8") as f:
        if existing.strip():
            f.write(existing.rstrip("\n") + "\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

