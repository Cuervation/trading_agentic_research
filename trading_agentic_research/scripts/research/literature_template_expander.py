"""Propose literature-derived templates that are supported by existing features.

The expander is conservative by design:
- it only proposes hypotheses whose required features already exist;
- unsupported paper ideas become missing-feature tasks, never fake hypotheses;
- duplicate override signatures are blocked;
- semantically exhausted families are avoided unless a proposal is explicitly
  marked as a new causal mechanism.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomous_hypothesis_factory import (  # noqa: E402
    append_jsonl,
    existing_ids,
    existing_override_sigs,
    read_json,
    read_jsonl,
    real_override_signature,
)
from scripts.research.effective_hypothesis_filter import effective_hypothesis_status  # noqa: E402
from scripts.research.literature_hypothesis_miner import (  # noqa: E402
    _missing_task,
    append_missing_tasks_dedup,
    available_weekly_features,
    ideas_from_paper_ideas,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _slug(text: str, max_len: int = 56) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text).upper()).strip("_")[:max_len] or "TEMPLATE"


def _condition(field: str, operator: str, value: float) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value, "enabled_if_field_exists": True}


def _current_parent(state_dir: str | Path) -> dict[str, Any]:
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    return {
        "run_id": str(current.get("current_parent_run_id") or "PARENT"),
        "hypothesis_id": current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id"),
        "config_path": current.get("current_parent_config_path"),
    }


def _semantic_exhausted_families(state_dir: str | Path) -> set[str]:
    semantic = read_json(Path(state_dir) / "semantic_branch_exhaustion.json", {}) or {}
    out: set[str] = set()
    for branch_key, payload in (semantic.get("branches", {}) or {}).items():
        if str(payload.get("status") or "").lower() == "exhausted" or payload.get("exhausted") is True:
            out.add(str(branch_key).split("/", 1)[0])
    return out


def _cooldown_info(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {}
    cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for family, detail in cooldowns.items():
        detail = detail if isinstance(detail, dict) else {"reason": str(detail)}
        out[str(family)] = {**detail, "hard": bool(detail.get("cooldown_until"))}
    return out


def _base_templates(parent_run_id: str) -> list[dict[str, Any]]:
    """Return deterministic template candidates that use existing/proxy columns.

    Thresholds are deliberately simple and auditable. They are not claimed as
    truth; they create falsifiable candidates only when the columns exist.
    """
    prefix = f"HYP_LITEXP_{_slug(parent_run_id, 24)}"
    return [
        {
            "hypothesis_id": f"{prefix}_RET52_DRAWDOWN26_PROXY_V1",
            "family": "paper_drawdown_proxy_momentum",
            "axis": "paper_drawdown_proxy_filter",
            "source_id": "drawdown_aware_momentum_proxy_template",
            "paper_title": "Drawdown-aware momentum using existing drawdown proxy",
            "claim": "52-week momentum filtered by an existing 26-week drawdown-from-high proxy may avoid fragile winners without new feature engineering.",
            "mechanism": "Severe recent drawdowns can indicate fragile momentum; using an existing drawdown proxy tests the causal filter before building max_drawdown_26w_pct.",
            "features_required": ["ret_52w_pct", "drawdown_from_high_26w_pct", "close"],
            "falsification_rule": "Reject if the drawdown proxy does not improve drawdown/yearly SPY comparison or materially harms CAGR.",
            "overrides": {
                "ranking": {"field": "ret_52w_pct", "order": "desc"},
                "risk_filters": {
                    "require_non_null_fields": ["ret_52w_pct", "drawdown_from_high_26w_pct", "close"],
                    "conditions": [_condition("drawdown_from_high_26w_pct", ">", -25.0)],
                },
                "changed_parameters": ["ranking.field", "risk_filters.conditions"],
                "expected_effect": "Test downside-risk filtering with an existing drawdown proxy before implementing new max-drawdown features.",
                "autonomy_reason": "literature_template_expander_v1",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_RET52_VOL12_LOW_VOL_PROXY_V1",
            "family": "paper_volatility_proxy_momentum",
            "axis": "paper_low_vol_proxy_filter",
            "source_id": "low_volatility_existing_proxy_template",
            "paper_title": "Low-volatility momentum using existing 12-week volatility proxy",
            "claim": "52-week momentum filtered by existing 12-week volatility may reduce crash-prone winners without inventing missing volatility features.",
            "mechanism": "Momentum names with lower realized volatility may have less crash exposure; volatility_12w_pct is an existing proxy for the missing 13-week volatility requests.",
            "features_required": ["ret_52w_pct", "volatility_12w_pct", "close"],
            "falsification_rule": "Reject if the volatility proxy does not improve drawdown or yearly robustness versus AUTO_002.",
            "overrides": {
                "ranking": {"field": "ret_52w_pct", "order": "desc"},
                "risk_filters": {
                    "require_non_null_fields": ["ret_52w_pct", "volatility_12w_pct", "close"],
                    "conditions": [_condition("volatility_12w_pct", "<", 12.0)],
                },
                "changed_parameters": ["ranking.field", "risk_filters.conditions"],
                "expected_effect": "Use an existing volatility proxy to open a risk-aware momentum family without new feature engineering.",
                "autonomy_reason": "literature_template_expander_v1",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_RET52_RET12_CONFIRM_PROXY_V1",
            "family": "paper_near_horizon_confirmation",
            "axis": "paper_ret12_confirmation_proxy",
            "source_id": "multi_lookback_existing_ret12_proxy_template",
            "paper_title": "Multi-lookback confirmation using existing ret_12w_pct proxy",
            "claim": "52-week momentum confirmed by existing 12-week return may approximate the blocked ret_13w confirmation axis without fabricating ret_13w_pct.",
            "mechanism": "Near-term positive momentum can filter stale long-lookback winners; ret_12w_pct is available and close to the paper template's missing ret_13w_pct.",
            "features_required": ["ret_52w_pct", "ret_12w_pct", "close"],
            "falsification_rule": "Reject if 12-week confirmation fails to improve robustness or duplicates old time-series momentum artifacts.",
            "overrides": {
                "ranking": {"field": "ret_52w_pct", "order": "desc"},
                "risk_filters": {
                    "require_non_null_fields": ["ret_52w_pct", "ret_12w_pct", "close"],
                    "conditions": [_condition("ret_12w_pct", ">", 0.0)],
                },
                "changed_parameters": ["ranking.field", "risk_filters.conditions"],
                "expected_effect": "Open a near-horizon confirmation family using an existing feature instead of missing ret_13w_pct.",
                "autonomy_reason": "literature_template_expander_v1",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_RET52_SPY_SLOPE_REGIME_V1",
            "family": "paper_regime_slope_filter",
            "axis": "paper_spy_slope_regime_filter",
            "source_id": "market_state_existing_spy_slope_template",
            "paper_title": "Market-state filter using existing SPY slope feature",
            "claim": "52-week momentum gated by positive SPY SMA50 slope may test market-state behavior without reusing the exhausted strict/relaxed SMA gate.",
            "mechanism": "The slope of the benchmark trend can be a different causal regime signal from level-above-SMA filters.",
            "features_required": ["ret_52w_pct", "spy_close_sma_50_slope_5d_pct", "close"],
            "falsification_rule": "Reject if SPY slope gating worsens CAGR without a meaningful drawdown/yearly robustness gain.",
            "overrides": {
                "ranking": {"field": "ret_52w_pct", "order": "desc"},
                "risk_filters": {
                    "require_non_null_fields": ["ret_52w_pct", "spy_close_sma_50_slope_5d_pct", "close"],
                    "conditions": [_condition("spy_close_sma_50_slope_5d_pct", ">", 0.0)],
                },
                "changed_parameters": ["ranking.field", "risk_filters.conditions"],
                "expected_effect": "Open a new regime-slope family distinct from duplicate strict/relaxed SPY level gates.",
                "autonomy_reason": "literature_template_expander_v1",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_R2_DRAWDOWN26_QUALITY_PULLBACK_V1",
            "family": "paper_quality_pullback_momentum",
            "axis": "paper_quality_drawdown_proxy_filter",
            "source_id": "quality_drawdown_existing_proxy_template",
            "paper_title": "Quality trend filtered by drawdown proxy",
            "claim": "Ranking by trend quality while excluding severe drawdown-from-high names may test whether clean trends with controlled pullbacks outperform raw momentum.",
            "mechanism": "Trend quality and recent downside proxy combine two existing, distinct mechanisms without requiring new columns.",
            "features_required": ["channel_r2", "drawdown_from_high_26w_pct", "close"],
            "falsification_rule": "Reject if quality-plus-drawdown filtering fails to improve drawdown-adjusted robustness.",
            "overrides": {
                "ranking": {"field": "channel_r2", "order": "desc"},
                "risk_filters": {
                    "require_non_null_fields": ["channel_r2", "drawdown_from_high_26w_pct", "close"],
                    "conditions": [_condition("drawdown_from_high_26w_pct", ">", -20.0)],
                },
                "changed_parameters": ["ranking.field", "risk_filters.conditions"],
                "expected_effect": "Test a new quality-plus-downside proxy family using existing features.",
                "autonomy_reason": "literature_template_expander_v1",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_RESIDUAL26_BREADTH45_DD26_V1",
            "family": "paper_residual_breadth_momentum",
            "axis": "paper_residual_breadth_drawdown_filter",
            "source_id": "residual_momentum_breadth_existing_features",
            "paper_title": "Residual momentum with breadth and drawdown controls",
            "claim": "26-week residual momentum gated by market breadth and recent drawdown may avoid beta-driven and fragile winners.",
            "mechanism": "Residual return removes broad SPY beta, breadth gating avoids weak market regimes, and drawdown control filters unstable momentum.",
            "features_required": ["residual_ret_26w_pct", "market_breadth_above_sma50_pct", "max_drawdown_26w_pct", "close"],
            "falsification_rule": "Reject if residual-breadth gating fails yearly/monthly SPY comparison or worsens drawdown versus AUTO_002.",
            "overrides": {
                "ranking": {"field": "residual_ret_26w_pct", "order": "desc"},
                "entry_rule": {"type": "top_n", "top_n": 10, "by": "residual_ret_26w_pct"},
                "risk_filters": {
                    "require_non_null_fields": ["residual_ret_26w_pct", "market_breadth_above_sma50_pct", "max_drawdown_26w_pct", "close"],
                    "conditions": [
                        _condition("market_breadth_above_sma50_pct", ">", 45.0),
                        _condition("max_drawdown_26w_pct", ">", -22.0),
                    ],
                },
                "changed_parameters": ["ranking.field", "entry_rule.by", "entry_rule.top_n", "risk_filters.conditions"],
                "expected_effect": "Test idiosyncratic momentum only when breadth is healthy and recent drawdown is controlled.",
                "autonomy_reason": "literature_template_expander_v2",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_RESIDUAL26_LOWVOL13_CONFIRM_V1",
            "family": "paper_residual_low_vol_momentum",
            "axis": "paper_residual_lowvol_confirmation",
            "source_id": "residual_low_vol_confirmation_existing_features",
            "paper_title": "Residual momentum with low-volatility confirmation",
            "claim": "Residual momentum confirmed by positive 13-week return and low realized volatility may reduce crash-prone momentum exposure.",
            "mechanism": "The template separates stock-specific persistence from market beta, then filters noisy/high-volatility names with existing features.",
            "features_required": ["residual_ret_26w_pct", "realized_vol_13w_pct", "ret_13w_pct", "close"],
            "falsification_rule": "Reject if low-vol residual confirmation does not improve drawdown or yearly robustness versus AUTO_002.",
            "overrides": {
                "ranking": {"field": "residual_ret_26w_pct", "order": "desc"},
                "entry_rule": {"type": "top_n", "top_n": 8, "by": "residual_ret_26w_pct"},
                "risk_filters": {
                    "require_non_null_fields": ["residual_ret_26w_pct", "realized_vol_13w_pct", "ret_13w_pct", "close"],
                    "conditions": [
                        _condition("realized_vol_13w_pct", "<", 10.0),
                        _condition("ret_13w_pct", ">", 0.0),
                    ],
                },
                "changed_parameters": ["ranking.field", "entry_rule.by", "entry_rule.top_n", "risk_filters.conditions"],
                "expected_effect": "Combine idiosyncratic momentum with low recent volatility and positive near-term confirmation.",
                "autonomy_reason": "literature_template_expander_v2",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_BREADTH_TREND_QUALITY_V1",
            "family": "paper_breadth_quality_trend",
            "axis": "paper_breadth_quality_filter",
            "source_id": "breadth_quality_trend_existing_features",
            "paper_title": "Breadth-gated trend quality",
            "claim": "Clean trend quality under positive market breadth may be more robust than raw return momentum.",
            "mechanism": "Trend smoothness plus cross-sectional breadth tests broad participation rather than individual acceleration alone.",
            "features_required": ["channel_r2", "channel_slope_pct", "market_breadth_above_sma50_pct", "close"],
            "falsification_rule": "Reject if breadth-gated quality trend fails to improve robustness or materially harms CAGR versus AUTO_002.",
            "overrides": {
                "ranking": {"field": "channel_r2", "order": "desc"},
                "entry_rule": {"type": "top_n", "top_n": 9, "by": "channel_r2"},
                "risk_filters": {
                    "require_non_null_fields": ["channel_r2", "channel_slope_pct", "market_breadth_above_sma50_pct", "close"],
                    "conditions": [
                        _condition("channel_slope_pct", ">", 0.0),
                        _condition("market_breadth_above_sma50_pct", ">", 50.0),
                    ],
                },
                "changed_parameters": ["ranking.field", "entry_rule.by", "entry_rule.top_n", "risk_filters.conditions"],
                "expected_effect": "Test smooth trend quality only when broad participation is positive.",
                "autonomy_reason": "literature_template_expander_v2",
            },
            "mechanism_is_clearly_new": True,
        },
        {
            "hypothesis_id": f"{prefix}_SECTOR_REL26_LOWDD_V1",
            "family": "paper_sector_relative_momentum",
            "axis": "paper_sector_relative_strength_filter",
            "source_id": "sector_industry_relative_momentum",
            "paper_title": "Sector-relative strength momentum",
            "claim": "Stocks outperforming their own sector on 26-week return may represent idiosyncratic strength rather than sector beta alone.",
            "mechanism": "Sector-relative return subtracts the contemporaneous sector median return by date, then filters recent drawdown to avoid fragile sector leaders.",
            "features_required": ["ret_vs_sector_26w_pct", "max_drawdown_26w_pct", "close"],
            "falsification_rule": "Reject if sector-relative strength does not improve yearly robustness or drawdown versus AUTO_002.",
            "overrides": {
                "ranking": {"field": "ret_vs_sector_26w_pct", "order": "desc"},
                "entry_rule": {"type": "top_n", "top_n": 10, "by": "ret_vs_sector_26w_pct"},
                "risk_filters": {
                    "require_non_null_fields": ["ret_vs_sector_26w_pct", "max_drawdown_26w_pct", "close"],
                    "conditions": [_condition("max_drawdown_26w_pct", ">", -24.0)],
                },
                "changed_parameters": ["ranking.field", "entry_rule.by", "entry_rule.top_n", "risk_filters.conditions"],
                "expected_effect": "Test stock-specific sector leadership after acquiring validated sector metadata.",
                "autonomy_reason": "literature_template_expander_v3_external_sector_metadata",
            },
            "mechanism_is_clearly_new": True,
        },
    ]


def _row_from_template(template: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    overrides = json.loads(json.dumps(template["overrides"], ensure_ascii=False))
    overrides["strategy_id"] = template["hypothesis_id"]
    overrides.setdefault("strategy_family", template["family"])
    return {
        "hypothesis_id": template["hypothesis_id"],
        "family": template["family"],
        "claim": template["claim"],
        "causal_mechanism": template["mechanism"],
        "bibliography_basis": [{"source_id": template["source_id"], "title": template["paper_title"]}],
        "empirical_basis": [{
            "run_id": parent.get("run_id"),
            "hypothesis_id": parent.get("hypothesis_id"),
            "reason": "Proposed by literature_template_expander using existing supported features after research-space exhaustion.",
        }],
        "features_required": list(template["features_required"]),
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": template["axis"],
        "falsification_rule": template["falsification_rule"],
        "strategy_overrides": overrides,
    }


def _record_missing_tasks_for_external_ideas(
    *,
    state_dir: str | Path,
    paper_ideas: str | Path,
    features: set[str],
    parent: dict[str, Any],
) -> int:
    tasks = []
    for idea in ideas_from_paper_ideas(paper_ideas):
        if set(idea.required_features).issubset(features):
            continue
        tasks.append(_missing_task(str(parent.get("run_id") or "PARENT"), parent.get("hypothesis_id"), idea, features))
    return append_missing_tasks_dedup(Path(state_dir) / "missing_feature_tasks.jsonl", tasks)


def propose_literature_templates(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path | None = None,
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    paper_ideas: str | Path = "bibliography/paper_ideas.jsonl",
    runs_dir: str | Path = "runs",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    max_new: int = 5,
    write: bool = False,
    record_missing_tasks: bool = False,
    allow_exhausted_new_mechanism: bool = False,
) -> dict[str, Any]:
    parent = _current_parent(state_dir)
    features = available_weekly_features(state_dir)
    bank = read_jsonl(hypothesis_bank)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    exhausted_families = _semantic_exhausted_families(state_dir)
    cooldowns = _cooldown_info(state_dir)

    proposals: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    rows_to_write: list[dict[str, Any]] = []

    for template in _base_templates(parent.get("run_id") or "PARENT"):
        missing = sorted(set(template["features_required"]).difference(features))
        row = _row_from_template(template, parent)
        sig = real_override_signature(row.get("strategy_overrides", {}))
        family = str(template["family"])
        reasons: list[str] = []
        effective_status: dict[str, Any] = {}
        if missing:
            reasons.append("missing_features")
        if template["hypothesis_id"] in ids:
            reasons.append("id_exists")
        if sig in sigs:
            reasons.append("duplicate_override_signature")
        if cooldowns.get(family, {}).get("hard"):
            reasons.append("family_hard_cooldown")
        if family in exhausted_families and not (allow_exhausted_new_mechanism and template.get("mechanism_is_clearly_new")):
            reasons.append("semantic_family_exhausted")
        if not reasons:
            effective_status = effective_hypothesis_status(
                hypothesis=row,
                state_dir=state_dir,
                runs_dir=runs_dir,
                strategy_registry_path=strategy_registry_path,
                repo_root=ROOT,
                check_exact_duplicate=True,
                block_feature_space_stall=True,
                block_family_stall=True,
            )
            if effective_status.get("blocked"):
                reasons.append(str(effective_status.get("reason") or "effective_hypothesis_blocked"))

        item = {
            "hypothesis_id": template["hypothesis_id"],
            "family": family,
            "axis": template["axis"],
            "source_id": template["source_id"],
            "paper_title": template["paper_title"],
            "claim": template["claim"],
            "features_required": list(template["features_required"]),
            "missing_features": missing,
            "mechanism_is_clearly_new": bool(template.get("mechanism_is_clearly_new")),
            "duplicate_override_signature": sig in sigs,
            "advisory_cooldown": family in cooldowns and not cooldowns.get(family, {}).get("hard"),
            "effective_status": effective_status,
            "blocked_reasons": reasons,
            "would_write": not reasons,
            "row": row if not reasons else None,
        }
        if reasons:
            blocked.append(item)
        else:
            proposals.append(item)
            if write and len(rows_to_write) < max_new:
                rows_to_write.append(row)
                ids.add(template["hypothesis_id"])
                sigs.add(sig)

    if write and rows_to_write:
        append_jsonl(hypothesis_bank, rows_to_write)

    missing_tasks_written = 0
    if record_missing_tasks:
        missing_tasks_written = _record_missing_tasks_for_external_ideas(
            state_dir=state_dir,
            paper_ideas=paper_ideas,
            features=features,
            parent=parent,
        )

    payload = {
        "generated_at": now_iso(),
        "mode": "write" if write else "dry_run",
        "available_feature_count": len(features),
        "proposals": [{k: v for k, v in item.items() if k != "row"} for item in proposals],
        "blocked": [{k: v for k, v in item.items() if k != "row"} for item in blocked],
        "written": [row.get("hypothesis_id") for row in rows_to_write],
        "missing_tasks_written": missing_tasks_written,
        "next_action": "Review proposals; if acceptable, run with --write after confirming they are genuinely new research mechanisms.",
    }

    if reports_dir is not None:
        state = Path(state_dir)
        reports = Path(reports_dir)
        write_json(state / "literature_template_expansion.json", payload)
        write_json(reports / "literature_template_expansion.json", payload)
        _write_markdown_report(reports / "literature_template_expansion.md", payload)
    return payload


def _write_markdown_report(path: str | Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Literature Template Expansion",
        "",
        "Planning report for new literature templates supported by existing feature columns.",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Mode: `{payload.get('mode')}`",
        f"- Writeable proposals: **{len(payload.get('proposals') or [])}**",
        f"- Blocked proposals: **{len(payload.get('blocked') or [])}**",
        "",
        "## Writeable proposals",
        "",
        "| hypothesis | family | required features |",
        "|---|---|---|",
    ]
    for item in payload.get("proposals", []) or []:
        lines.append(f"| `{item.get('hypothesis_id')}` | `{item.get('family')}` | {', '.join('`'+x+'`' for x in item.get('features_required', []))} |")
    if not payload.get("proposals"):
        lines.append("| - | - | - |")

    lines.extend(["", "## Blocked proposals", "", "| hypothesis | reasons | missing features |", "|---|---|---|"])
    for item in payload.get("blocked", []) or []:
        lines.append(
            f"| `{item.get('hypothesis_id')}` | {', '.join(item.get('blocked_reasons') or []) or '-'} | {', '.join(item.get('missing_features') or []) or '-'} |"
        )
    lines.extend([
        "",
        "## Suggested dry-run command",
        "",
        "```powershell",
        "python .\\scripts\\research\\literature_template_expander.py `",
        "  --state-dir .\\state `",
        "  --reports-dir .\\reports `",
        "  --hypothesis-bank .\\bibliography\\hypothesis_bank.jsonl `",
        "  --paper-ideas .\\bibliography\\paper_ideas.jsonl `",
        "  --no-record-missing-tasks",
        "```",
        "",
    ])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Propose supported literature templates without inventing missing features.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--max-new", type=int, default=5)
    p.add_argument("--write", action="store_true", help="Append writeable proposals to the hypothesis bank.")
    p.add_argument("--record-missing-tasks", dest="record_missing_tasks", action="store_true", default=True)
    p.add_argument("--no-record-missing-tasks", dest="record_missing_tasks", action="store_false")
    p.add_argument("--allow-exhausted-new-mechanism", action="store_true")
    args = p.parse_args()
    result = propose_literature_templates(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        runs_dir=args.runs_dir,
        strategy_registry_path=args.strategy_registry,
        max_new=args.max_new,
        write=bool(args.write),
        record_missing_tasks=bool(args.record_missing_tasks),
        allow_exhausted_new_mechanism=bool(args.allow_exhausted_new_mechanism),
    )
    print(json.dumps({
        "mode": result.get("mode"),
        "writeable": len(result.get("proposals") or []),
        "blocked": len(result.get("blocked") or []),
        "written": result.get("written"),
        "missing_tasks_written": result.get("missing_tasks_written"),
        "report": str(Path(args.reports_dir) / "literature_template_expansion.md"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
