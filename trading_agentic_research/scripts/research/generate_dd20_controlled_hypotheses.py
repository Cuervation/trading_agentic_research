"""Generate controlled DD20 hypotheses from compact audit evidence.

Read scope is intentionally narrow:
- context packs under reports/context_packs/
- the newest reports/dd20_champion_audit/ folder

No backtests are run. No baseline/current_parent files are modified.
The script only writes hypothesis configs and compact reports.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_DIR = REPO_ROOT / "reports" / "context_packs"
AUDIT_ROOT = REPO_ROOT / "reports" / "dd20_champion_audit"
CONFIG_OUT_DIR = REPO_ROOT / "configs" / "generated" / "dd20_controlled"
REPORT_OUT_DIR = REPO_ROOT / "reports" / "dd20_controlled_hypotheses"

AUDIT_FILES = {
    "champion_summary.csv",
    "bad_period_metrics.csv",
    "trade_quality.csv",
    "regime_breakdown.csv",
    "README_AUDIT_DD20_CHAMPIONS.md",
}

PARENT_BY_FAMILY = {
    "spy_fallback_partial": "DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1",
    "topn_dynamic": "DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1",
    "guardrail_dynamic": "DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1",
    "dd_compression": "DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1",
}

FAMILY_ORDER = [
    "spy_fallback_partial",
    "topn_dynamic",
    "guardrail_dynamic",
    "dd_compression",
]

DEFAULT_BENCHMARK = "SPY"


@dataclass
class Hypothesis:
    strategy_id: str
    family: str
    parent_strategy: str
    config: dict[str, Any]
    summary_row: dict[str, Any]
    evidence_notes: list[str]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def detect_delimiter(header_line: str) -> str:
    return ";" if ";" in header_line else ","


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        first = ""
        for line in f:
            if line.strip():
                first = line
                break
        if not first:
            return []
        f.seek(0)
        reader = csv.DictReader(f, delimiter=detect_delimiter(first))
        return [dict(row) for row in reader]


def latest_audit_dir() -> Path | None:
    if not AUDIT_ROOT.exists():
        return None
    folders = [p for p in AUDIT_ROOT.iterdir() if p.is_dir()]
    if not folders:
        return None
    return max(folders, key=lambda p: p.stat().st_mtime)


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def fmt_pct(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}%"


def load_context_availability() -> dict[str, str]:
    expected = [
        "repo_context_pack.md",
        "coordinator_context.md",
        "analyst_context.md",
        "coder_context.md",
        "executor_context.md",
        "auditor_context.md",
        "librarian_context.md",
        "literature_researcher_context.md",
    ]
    out: dict[str, str] = {}
    for name in expected:
        path = CONTEXT_DIR / name
        out[name] = "ok" if path.exists() else "missing"
    return out


def load_audit_evidence(audit_dir: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    missing: list[str] = []
    for filename in sorted(AUDIT_FILES):
        path = audit_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        if filename.endswith(".csv"):
            evidence[filename] = read_csv_rows(path)
        else:
            evidence[filename] = read_text(path)
    evidence["missing_files"] = missing
    evidence["audit_dir"] = str(audit_dir)
    return evidence


def summarize_champions(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = row.get("run_id", "")
        if not run_id:
            continue
        out[run_id] = {
            "run_id": run_id,
            "strategy_id": row.get("strategy_id", ""),
            "CAGR": parse_float(row.get("CAGR")),
            "SPY_CAGR": parse_float(row.get("SPY_CAGR")),
            "max_drawdown_pct": parse_float(row.get("max_drawdown_pct")),
            "years_won_vs_spy": int(parse_float(row.get("years_won_vs_spy"))),
            "years_lost_vs_spy": int(parse_float(row.get("years_lost_vs_spy"))),
            "months_won_vs_spy": int(parse_float(row.get("months_won_vs_spy"))),
            "months_lost_vs_spy": int(parse_float(row.get("months_lost_vs_spy"))),
            "trades": int(parse_float(row.get("trades"))),
            "calmar_ratio": parse_float(row.get("calmar_ratio")),
            "total_return_pct": parse_float(row.get("total_return_pct")),
            "SPY_total_return_pct": parse_float(row.get("SPY_total_return_pct")),
            "excess_CAGR": parse_float(row.get("excess_CAGR")),
        }
    return out


def period_snapshot(rows: list[dict[str, str]], period: str, run_id: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("run_id") == run_id and row.get("period") == period:
            return {
                "period": period,
                "strategy_return_pct": parse_float(row.get("strategy_return_pct")),
                "spy_return_pct": parse_float(row.get("spy_return_pct")),
                "diff_pct": parse_float(row.get("diff_pct")),
                "avg_cash_pct": parse_float(row.get("avg_cash_pct")),
                "avg_gross_exposure_pct": parse_float(row.get("avg_gross_exposure_pct")),
                "avg_positions_count": parse_float(row.get("avg_positions_count")),
                "trades": int(parse_float(row.get("trades"))),
                "trade_avg_return_pct": parse_float(row.get("trade_avg_return_pct")),
                "trade_loss_rate_pct": parse_float(row.get("trade_loss_rate_pct")),
                "stop_loss_trades": int(parse_float(row.get("stop_loss_trades"))),
                "stop_loss_rate_pct": parse_float(row.get("stop_loss_rate_pct")),
            }
    return None


def build_evidence_notes(
    family: str,
    parent_strategy: str,
    champions: dict[str, dict[str, Any]],
    bad_period_rows: list[dict[str, str]],
    trade_rows: list[dict[str, str]],
) -> list[str]:
    notes: list[str] = []
    parent = champions.get(parent_strategy, {})
    if parent:
        notes.append(
            f"Parent {parent_strategy}: CAGR {fmt_pct(parent['CAGR'])}, DD {fmt_pct(parent['max_drawdown_pct'])}, "
            f"years W/L {parent['years_won_vs_spy']}/{parent['years_lost_vs_spy']}, months W/L {parent['months_won_vs_spy']}/{parent['months_lost_vs_spy']}."
        )
    y2023 = period_snapshot(bad_period_rows, "2023", parent_strategy)
    y2025 = period_snapshot(bad_period_rows, "2025", parent_strategy)
    y2024 = period_snapshot(bad_period_rows, "2024", parent_strategy)
    if y2023:
        notes.append(
            f"2023 weakness: strategy {fmt_pct(y2023['strategy_return_pct'])} vs SPY {fmt_pct(y2023['spy_return_pct'])}, "
            f"diff {fmt_pct(y2023['diff_pct'])}, cash {fmt_pct(y2023['avg_cash_pct'])}, exposure {fmt_pct(y2023['avg_gross_exposure_pct'])}."
        )
    if y2025:
        notes.append(
            f"2025 weakness: strategy {fmt_pct(y2025['strategy_return_pct'])} vs SPY {fmt_pct(y2025['spy_return_pct'])}, "
            f"diff {fmt_pct(y2025['diff_pct'])}, cash {fmt_pct(y2025['avg_cash_pct'])}, stop-loss rate {fmt_pct(y2025['stop_loss_rate_pct'])}."
        )
    if y2024:
        notes.append(
            f"2024 bull regime: strategy {fmt_pct(y2024['strategy_return_pct'])} vs SPY {fmt_pct(y2024['spy_return_pct'])}; "
            f"this suggests the issue is not universal, but regime-sensitive opportunity loss."
        )
    for row in trade_rows:
        if row.get("run_id") == parent_strategy:
            notes.append(
                f"Trade quality: {row.get('trade_bucket')} bucket had median {row.get('median_return_pct', 'n/a')} and average duration {row.get('avg_duration_days', 'n/a')} days."
            )
            break
    if family == "spy_fallback_partial":
        notes.append("Audit pattern: cash sat above 80% in bad years; partial SPY fallback should reduce opportunity loss when regime is positive.")
    elif family == "topn_dynamic":
        notes.append("Audit pattern: winners are concentrated and top sector is Information Technology; controlled TOPN expansion in strong regimes may improve capture without always raising exposure.")
    elif family == "guardrail_dynamic":
        notes.append("Audit pattern: the guard activated multiple times and produced partial rebalances; dynamic relaxation only when DD is still controlled may restore participation.")
    elif family == "dd_compression":
        notes.append("Audit pattern: current champions already sit just under the -20% cap; compressing DD toward -15/-17 is plausible but must preserve CAGR above SPY.")
    return notes


def make_metadata(
    *,
    strategy_id: str,
    family: str,
    parent_strategy: str,
    expected_effect: str,
    risk: str,
    why_this_should_help: str,
    success_rule: str,
    rejection_rule: str,
    guardrail_max_drawdown_pct: int = -20,
) -> dict[str, Any]:
    return {
        "parent_strategy": parent_strategy,
        "hypothesis_family": family,
        "expected_effect": expected_effect,
        "risk": risk,
        "why_this_should_help": why_this_should_help,
        "guardrail_max_drawdown_pct": guardrail_max_drawdown_pct,
        "success_rule": success_rule,
        "rejection_rule": rejection_rule,
    }


def promise_score(family: str, variant: Any) -> float:
    if family == "spy_fallback_partial":
        return {25: 0.85, 50: 1.0, 75: 0.7}.get(int(variant), 0.5)
    if family == "topn_dynamic":
        item = variant if isinstance(variant, dict) else {}
        key = (int(item.get("strong_topn", 0)), int(item.get("weak_topn", 0)))
        return {(12, 8): 1.0, (16, 8): 0.85, (18, 6): 0.7}.get(key, 0.5)
    if family == "guardrail_dynamic":
        item = variant if isinstance(variant, dict) else {}
        key = (abs(int(item.get("resume_drawdown_pct", 0))), int(item.get("reduced_exposure_pct_when_active", 0)))
        return {(12, 20): 0.95, (13, 25): 0.8, (14, 30): 0.6}.get(key, 0.5)
    if family == "dd_compression":
        item = variant if isinstance(variant, dict) else {}
        key = (int(item.get("target_max_drawdown_pct", 0)), int(item.get("max_gross_exposure_pct", 0)))
        return {(-17, 45): 1.0, (-16, 40): 0.8, (-15, 35): 0.6}.get(key, 0.5)
    return 0.5


def build_controlled_hypotheses(evidence: dict[str, Any]) -> list[Hypothesis]:
    champions = summarize_champions(evidence.get("champion_summary.csv", []))
    bad_period_rows = evidence.get("bad_period_metrics.csv", [])
    trade_rows = evidence.get("trade_quality.csv", [])

    defs: list[dict[str, Any]] = []

    # 1) SPY fallback partial
    for weight in (25, 50, 75):
        strategy_id = f"HYP_DD20_CTRL_SPY_FALLBACK_{weight}_V1"
        parent = PARENT_BY_FAMILY["spy_fallback_partial"]
        evidence_notes = build_evidence_notes("spy_fallback_partial", parent, champions, bad_period_rows, trade_rows)
        defs.append(
            {
                "strategy_id": strategy_id,
                "family": "spy_fallback_partial",
                "parent_strategy": parent,
                "hypothesis_subfamily": "partial_spy_cash_replacement",
                "variant": weight,
                "title": f"SPY fallback partial {weight}%",
                "expected_effect": "Reduce opportunity loss in positive SPY regimes by replacing a controlled slice of idle cash with SPY exposure.",
                "risk": "Medium: adds benchmark exposure and could dilute alpha if the regime signal is wrong.",
                "why": "The audit shows 2023 and 2025 underperformance with cash above 80% and very low exposure; partial SPY fallback should recover upside that the champion left on the table in bull regimes.",
                "success_rule": "max_drawdown_pct no worse than -20%; CAGR above SPY; and at least one material gain vs parent: CAGR +0.5pt, DD +1pt, years won +1, or months won +6.",
                "rejection_rule": "Reject if drawdown breaks -20, CAGR does not exceed SPY, or the fallback merely increases exposure without improving any parent DD20 metric materially.",
                "metadata": make_metadata(
                    strategy_id=strategy_id,
                    family="spy_fallback_partial",
                    parent_strategy=parent,
                    expected_effect="Replace 25/50/75% of idle cash with SPY only when SPY regime is positive.",
                    risk="Medium",
                    why_this_should_help="2023/2025 were dominated by high cash and missed upside; controlled SPY fallback targets that specific opportunity loss.",
                    success_rule="max_drawdown_pct no worse than -20; CAGR must exceed SPY; and improve at least one material metric versus parent DD20.",
                    rejection_rule="Reject if DD < -20, CAGR <= SPY, or no parent metric improves materially.",
                ),
                "strategy_overrides": {
                    "market_filter": {
                        "benchmark": DEFAULT_BENCHMARK,
                        "require_positive_trend": True,
                        "condition_any": [
                            {"field": "spy_close_vs_sma50_pct", "operator": ">", "value": 0, "enabled_if_field_exists": True}
                        ],
                    },
                    "risk_management": {
                        "spy_fallback_partial_pct": weight,
                        "spy_fallback_only_when_positive_regime": True,
                        "max_gross_exposure_pct": 100,
                    },
                },
                "empirical_basis": [{"run_id": parent, "reason": "Champion audit and bad-period metrics show high cash / low exposure in weak years."}],
                "evidence_notes": evidence_notes,
                "generation_axis": "spy_fallback_partial",
            }
        )

    # 2) TOPN dynamic
    for strong_topn, weak_topn in ((12, 8), (16, 8), (18, 6)):
        strategy_id = f"HYP_DD20_CTRL_TOPN_DYNAMIC_{strong_topn}_{weak_topn}_V1"
        parent = PARENT_BY_FAMILY["topn_dynamic"]
        evidence_notes = build_evidence_notes("topn_dynamic", parent, champions, bad_period_rows, trade_rows)
        defs.append(
            {
                "strategy_id": strategy_id,
                "family": "topn_dynamic",
                "parent_strategy": parent,
                "hypothesis_subfamily": "dynamic_topn_by_regime",
                "variant": {"strong_topn": strong_topn, "weak_topn": weak_topn},
                "title": f"TOPN dynamic strong {strong_topn} / weak {weak_topn}",
                "expected_effect": "Expand the book only in strong SPY regimes and keep TOPN tight when SPY is weak.",
                "risk": "Medium: higher breadth can add noisy names if the regime classifier is late.",
                "why": "The audit shows concentrated weakness in bear/defensive periods and strong performance when regime is favorable; controlled TOPN expansion is a low-risk way to harvest more names only in bullish conditions.",
                "success_rule": "max_drawdown_pct no worse than -20; CAGR above SPY; and at least one parent metric improves materially.",
                "rejection_rule": "Reject if breadth expansion increases drawdown or lowers CAGR below SPY, or if it does not improve over parent DD20 metrics.",
                "metadata": make_metadata(
                    strategy_id=strategy_id,
                    family="topn_dynamic",
                    parent_strategy=parent,
                    expected_effect=f"Use TOPN={strong_topn} in strong regimes and TOPN={weak_topn} in weak regimes.",
                    risk="Medium",
                    why_this_should_help="The audit shows 2023/2025 underperformance with low exposure; dynamic breadth should help capture more winners in strong regimes without always increasing risk.",
                    success_rule="max_drawdown_pct no worse than -20; CAGR must exceed SPY; and one parent DD20 metric must improve materially.",
                    rejection_rule="Reject if DD < -20, CAGR <= SPY, or no parent metric improves materially.",
                ),
                "strategy_overrides": {
                    "entry_rule": {
                        "type": "top_n_dynamic",
                        "top_n_strong_regime": strong_topn,
                        "top_n_weak_regime": weak_topn,
                        "benchmark": DEFAULT_BENCHMARK,
                    },
                    "market_filter": {
                        "benchmark": DEFAULT_BENCHMARK,
                        "require_positive_trend": True,
                        "condition_any": [
                            {"field": "spy_close_vs_sma50_pct", "operator": ">", "value": 0, "enabled_if_field_exists": True}
                        ],
                    },
                },
                "empirical_basis": [{"run_id": parent, "reason": "Champion audit shows strong bull-regime performance but weak years with high cash and low exposure."}],
                "evidence_notes": evidence_notes,
                "generation_axis": "topn_dynamic",
            }
        )

    # 3) Guardrail dynamic
    for resume, reduced in ((12, 20), (13, 25), (14, 30)):
        strategy_id = f"HYP_DD20_CTRL_GUARD_DYNAMIC_{resume}_{reduced}_V1"
        parent = PARENT_BY_FAMILY["guardrail_dynamic"]
        evidence_notes = build_evidence_notes("guardrail_dynamic", parent, champions, bad_period_rows, trade_rows)
        defs.append(
            {
                "strategy_id": strategy_id,
                "family": "guardrail_dynamic",
                "parent_strategy": parent,
                "hypothesis_subfamily": "adaptive_drawdown_guard",
                "variant": {"resume_drawdown_pct": -resume, "reduced_exposure_pct_when_active": reduced},
                "title": f"Guardrail dynamic resume -{resume} / reduced exposure {reduced}%",
                "expected_effect": "Reduce time spent locked out by the guard while still hard-stopping near -20%.",
                "risk": "Medium-high: easing a guard can restore upside, but it can also let DD drift back toward the hard cap.",
                "why": "The audit shows the guard activated multiple times and the champion already sat close to the -20% limit; a dynamic resume threshold may recover participation without losing drawdown control.",
                "success_rule": "max_drawdown_pct no worse than -20; CAGR above SPY; and at least one material parent metric improves.",
                "rejection_rule": "Reject if DD breaks -20, CAGR fails to beat SPY, or the guard tweak adds no measurable improvement vs parent DD20.",
                "metadata": make_metadata(
                    strategy_id=strategy_id,
                    family="guardrail_dynamic",
                    parent_strategy=parent,
                    expected_effect=f"Resume at {resume}% DD with reduced exposure {reduced}% while preserving the -20% hard cap.",
                    risk="Medium-high",
                    why_this_should_help="The guard was active several times and caused partial rebalances; a dynamic guard should restore participation when DD is still under control.",
                    success_rule="max_drawdown_pct no worse than -20; CAGR must exceed SPY; and one parent DD20 metric must improve materially.",
                    rejection_rule="Reject if DD < -20, CAGR <= SPY, or no parent metric improves materially.",
                ),
                "strategy_overrides": {
                    "risk_management": {
                        "equity_drawdown_guard": {
                            "enabled": True,
                            "stop_new_entries_drawdown_pct": -18,
                            "resume_drawdown_pct": -resume,
                            "reduced_exposure_pct_when_active": reduced,
                        },
                        "max_gross_exposure_pct": 50,
                    },
                },
                "empirical_basis": [{"run_id": parent, "reason": "Guard activations and partial rebalances suggest the current lockout is active enough to matter."}],
                "evidence_notes": evidence_notes,
                "generation_axis": "guardrail_dynamic",
            }
        )

    # 4) DD compression
    for target_dd, gross in ((-17, 45), (-16, 40), (-15, 35)):
        strategy_id = f"HYP_DD20_CTRL_DD_COMPRESS_{abs(target_dd)}_{gross}_V1"
        parent = PARENT_BY_FAMILY["dd_compression"]
        evidence_notes = build_evidence_notes("dd_compression", parent, champions, bad_period_rows, trade_rows)
        defs.append(
            {
                "strategy_id": strategy_id,
                "family": "dd_compression",
                "parent_strategy": parent,
                "hypothesis_subfamily": "compress_drawdown_band",
                "variant": {"target_max_drawdown_pct": target_dd, "max_gross_exposure_pct": gross},
                "title": f"DD compression target {target_dd}% / gross exposure {gross}%",
                "expected_effect": "Move max drawdown toward -15/-17 while keeping the strategy above SPY.",
                "risk": "High: tighter risk control may improve DD but can easily crush CAGR and trade participation.",
                "why": "The three audited champions are all already near -19.2 to -19.8 DD. That makes DD compression a sensible controlled experiment, but only if CAGR stays above SPY.",
                "success_rule": "max_drawdown_pct no worse than -20 and preferably near the target band; CAGR above SPY; and at least one parent metric improves materially.",
                "rejection_rule": "Reject if DD breaks -20, CAGR <= SPY, or the tighter risk band meaningfully weakens parent DD20 metrics without a compensating DD reduction.",
                "metadata": make_metadata(
                    strategy_id=strategy_id,
                    family="dd_compression",
                    parent_strategy=parent,
                    expected_effect=f"Target max drawdown {target_dd}% with gross exposure capped near {gross}%.",
                    risk="High",
                    why_this_should_help="All current champions are clustered just under the -20% cap; compressed DD is the natural next safety experiment if CAGR survives.",
                    success_rule="max_drawdown_pct no worse than -20; CAGR must exceed SPY; and one parent DD20 metric must improve materially.",
                    rejection_rule="Reject if DD < -20, CAGR <= SPY, or no parent metric improves materially.",
                ),
                "strategy_overrides": {
                    "risk_management": {
                        "equity_drawdown_guard": {
                            "enabled": True,
                            "stop_new_entries_drawdown_pct": -18,
                            "resume_drawdown_pct": -12,
                            "max_drawdown_target_pct": target_dd,
                        },
                        "max_gross_exposure_pct": gross,
                    },
                },
                "empirical_basis": [{"run_id": parent, "reason": "Champion cluster already sits near the DD cap; this family tests whether that band can be compressed without losing SPY-beating CAGR."}],
                "evidence_notes": evidence_notes,
                "generation_axis": "dd_compression",
            }
        )

    hypotheses: list[Hypothesis] = []
    for item in defs[:12]:
        strategy_id = item["strategy_id"]
        family = item["family"]
        parent_strategy = item["parent_strategy"]
        base_config = {
            "strategy_id": strategy_id,
            "hypothesis_id": strategy_id,
            "strategy_family": "dd20_controlled_hypotheses",
            "benchmark_ticker": DEFAULT_BENCHMARK,
            "rebalance_frequency": "monthly",
            "costs": {"entry_cost_pct": 0.24, "exit_cost_pct": 0.24},
            "universe": {"source": "feature_store_tickers", "exclude_tickers": ["SPY"], "trade_spy": False},
            "market_filter": {
                "benchmark": DEFAULT_BENCHMARK,
                "require_positive_trend": True,
                "condition_any": [
                    {"field": "spy_close_vs_sma50_pct", "operator": ">", "value": 0, "enabled_if_field_exists": True}
                ],
            },
            "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]},
            "claim": item["expected_effect"],
            "causal_mechanism": item["why"],
            "changed_parameters": list(item["strategy_overrides"].keys()),
            "expected_effect": item["expected_effect"],
            "falsification_rule": item["rejection_rule"],
            "generation_axis": item["generation_axis"],
            "parent_strategy_id": parent_strategy,
            "parent_hypothesis_id": parent_strategy,
            "parent_strategy": parent_strategy,
            "empirical_basis": item["empirical_basis"],
            "metadata": item["metadata"],
            "strategy_overrides": item["strategy_overrides"],
            "evaluation_mode": "dd20_controlled_hypotheses",
            "status": "draft_controlled_hypothesis",
            "risk_of_overfit": "Controlled: evidence-driven and limited to 12 variants.",
            "novelty_reason": "Derived directly from the latest DD20 champion audit and bad-period evidence.",
            "why_not_duplicate": f"Each variant changes one controlled lever within {family} rather than making random parameter noise.",
        }
        hypotheses.append(
            Hypothesis(
                strategy_id=strategy_id,
                family=family,
                parent_strategy=parent_strategy,
                config=base_config,
                summary_row={
                    "strategy_id": strategy_id,
                    "family": family,
                    "parent_strategy": parent_strategy,
                    "config_path": f"configs/generated/dd20_controlled/{strategy_id}.json",
                    "expected_effect": item["expected_effect"],
                    "risk": item["metadata"]["risk"],
                    "why_this_should_help": item["metadata"]["why_this_should_help"],
                    "guardrail_max_drawdown_pct": item["metadata"]["guardrail_max_drawdown_pct"],
                    "success_rule": item["metadata"]["success_rule"],
                    "rejection_rule": item["metadata"]["rejection_rule"],
                    "variant": json.dumps(item["variant"], ensure_ascii=False),
                    "evidence_anchor": "; ".join(item["evidence_notes"][:3]),
                    "promise_score": promise_score(family, item["variant"]),
                },
                evidence_notes=item["evidence_notes"],
            )
        )
    return hypotheses


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def render_latest_summary(
    *,
    audit_dir: Path | None,
    context_status: dict[str, str],
    missing_audit_files: list[str],
    hypotheses: list[Hypothesis],
) -> str:
    family_counts = Counter(h.family for h in hypotheses)
    promising = sorted(
        hypotheses,
        key=lambda h: (-float(h.summary_row.get("promise_score", 0.0)), h.summary_row["risk"], h.strategy_id),
    )[:4]

    lines = [
        "# DD20 Controlled Hypotheses",
        "",
        "Esta generación usa solo evidencia compacta: context packs + última auditoría DD20. No se ejecutaron backtests y no se tocó current_parent ni current_baseline.",
        "",
        "## Fuente de evidencia",
        f"- Audit folder: `{audit_dir}`" if audit_dir else "- Audit folder: missing",
    ]
    if missing_audit_files:
        lines.append(f"- Missing audit files: {', '.join(missing_audit_files)}")
    lines.extend(
        [
            "",
            "## Context packs disponibles",
            "",
        ]
    )
    for name, status in context_status.items():
        lines.append(f"- `{name}`: {status}")
    lines.extend(
        [
            "",
            "## Resumen",
            f"- Hipótesis generadas: {len(hypotheses)}",
            f"- Familias: {', '.join(f'{family}={count}' for family, count in family_counts.items())}",
            "",
            "## Hipótesis más prometedoras",
        ]
    )
    for hyp in promising:
        lines.append(
            f"- `{hyp.strategy_id}` — {hyp.summary_row['expected_effect']} "
            f"(parent `{hyp.parent_strategy}`, riesgo {hyp.summary_row['risk']})."
        )
    lines.extend(
        [
            "",
            "## Criterios usados",
            "- No más de 12 hipótesis.",
            "- Cada hipótesis surge de una lectura causal de la auditoría: cash alto, exposición baja, guard activado, o DD cerca del cap.",
            "- Sin variantes random.",
            "- Sin backtests.",
            "",
            "## Próximo paso recomendado",
            "Si querés validar estas hipótesis, el siguiente paso debería ser un filtro de prioridad o un set de tareas de ejecución, no correr todo de golpe.",
            "",
        ]
    )
    return "\n".join(lines)


def render_readme() -> str:
    return "\n".join(
        [
            "# DD20 Controlled Hypotheses",
            "",
            "Este directorio contiene hipótesis DD20 controladas derivadas de la última auditoría compacta.",
            "",
            "## Qué hay acá",
            "",
            "- `configs/generated/dd20_controlled/*.json`: configs hipótesis, una por variante controlada.",
            "- `reports/dd20_controlled_hypotheses/hypotheses.csv`: índice compacto de todas las hipótesis.",
            "- `reports/dd20_controlled_hypotheses/latest_summary.md`: lectura humana rápida.",
            "",
            "## Cómo usarlo",
            "",
            "1. Revisá `latest_summary.md`.",
            "2. Elegí solo las hipótesis con mejor alineación causal con la auditoría.",
            "3. No correr backtests hasta tener aprobación explícita.",
            "4. No tocar `current_parent` ni `current_baseline` desde acá.",
            "",
            "## Familias",
            "",
            "- `spy_fallback_partial`: usar SPY parcialmente cuando el régimen es positivo y el portafolio está demasiado en cash.",
            "- `topn_dynamic`: expandir TOPN solo en régimen fuerte.",
            "- `guardrail_dynamic`: relajar/resumir el guardrail de forma dinámica sin romper el cap de DD.",
            "- `dd_compression`: apretar el drawdown objetivo hacia -15/-17 sin matar el CAGR.",
            "",
            "## Disciplina",
            "",
            "- No generar variantes random.",
            "- No promover baseline.",
            "- No leer CSV grandes ni runs completos para esta tarea.",
            "- Si una hipótesis no mejora nada material contra su parent DD20, se descarta.",
            "",
        ]
    )


def main() -> int:
    context_status = load_context_availability()
    audit_dir = latest_audit_dir()
    if audit_dir is None:
        REPORT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_OUT_DIR / "latest_summary.md").write_text(
            "# DD20 Controlled Hypotheses\n\nNo audit folder found.\n",
            encoding="utf-8",
        )
        (REPORT_OUT_DIR / "README.md").write_text(render_readme(), encoding="utf-8")
        return 0

    evidence = load_audit_evidence(audit_dir)
    hypotheses = build_controlled_hypotheses(evidence)

    CONFIG_OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_OUT_DIR.mkdir(parents=True, exist_ok=True)

    for hyp in hypotheses:
        write_json(CONFIG_OUT_DIR / f"{hyp.strategy_id}.json", hyp.config)

    summary_rows = [hyp.summary_row for hyp in hypotheses]
    fieldnames = [
        "strategy_id",
        "family",
        "parent_strategy",
        "config_path",
        "expected_effect",
        "risk",
        "why_this_should_help",
        "guardrail_max_drawdown_pct",
        "success_rule",
        "rejection_rule",
        "variant",
        "evidence_anchor",
        "promise_score",
    ]
    write_csv(REPORT_OUT_DIR / "hypotheses.csv", summary_rows, fieldnames)
    (REPORT_OUT_DIR / "latest_summary.md").write_text(
        render_latest_summary(
            audit_dir=audit_dir,
            context_status=context_status,
            missing_audit_files=evidence.get("missing_files", []),
            hypotheses=hypotheses,
        ),
        encoding="utf-8",
    )
    (REPORT_OUT_DIR / "README.md").write_text(render_readme(), encoding="utf-8")

    family_counts = Counter(h.family for h in hypotheses)
    print(f"Generated {len(hypotheses)} hypotheses from {audit_dir}")
    for family in FAMILY_ORDER:
        if family in family_counts:
            print(f"- {family}: {family_counts[family]}")
    print("Files created:")
    for hyp in hypotheses:
        print(f"- {CONFIG_OUT_DIR / (hyp.strategy_id + '.json')}")
    print(f"- {REPORT_OUT_DIR / 'latest_summary.md'}")
    print(f"- {REPORT_OUT_DIR / 'hypotheses.csv'}")
    print(f"- {REPORT_OUT_DIR / 'README.md'}")
    print("Most promising hypotheses:")
    for hyp in sorted(hypotheses, key=lambda h: (-float(h.summary_row.get("promise_score", 0.0)), h.strategy_id))[:4]:
        print(f"- {hyp.strategy_id}: {hyp.summary_row['expected_effect']} (score {float(hyp.summary_row.get('promise_score', 0.0)):.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
