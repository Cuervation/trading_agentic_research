"""Execute the DD20 controlled hypothesis batch without touching parent/baseline.

This runner is intentionally narrow:
- reads compact context/report files only;
- uses the existing backtester as-is;
- never edits current_parent/current_baseline/backtester;
- marks configs that need unsupported engine fields as requires_engine_support.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HYPOTHESIS_INDEX = ROOT / "reports" / "dd20_controlled_hypotheses" / "hypotheses.csv"
HYPOTHESIS_SUMMARY = ROOT / "reports" / "dd20_controlled_hypotheses" / "latest_summary.md"
CONFIG_DIR = ROOT / "configs" / "generated" / "dd20_controlled"
BATCH_REPORT_ROOT = ROOT / "reports" / "dd20_controlled_batch"
RUNS_DIR = ROOT / "runs"
PROJECT_CONFIG = ROOT / "configs" / "project_config.json"
RUN_BACKTEST = ROOT / "scripts" / "run_backtest.py"
GENERATED_EXEC_CONFIGS_DIRNAME = "executed_configs"
RUN_LOGS_DIRNAME = "run_logs"
EFFECTIVE_AUDITS_DIRNAME = "effective_config_audits"
RESTORED_AUDITS_DIRNAME = "restored_audits"

SUPPORTED_TRANSLATED_CONTROL_FIELDS = {
    "entry_rule.type",
    "entry_rule.top_n",
    "market_filter.soft_weak_regime_top_n",
    "market_filter.benchmark",
    "market_filter.require_positive_trend",
    "risk_management.max_gross_exposure_pct",
    "risk_management.dynamic_regime_exposure_pct.strong",
    "risk_management.dynamic_regime_exposure_pct.neutral",
    "risk_management.dynamic_regime_exposure_pct.weak",
    "risk_management.dynamic_regime_exposure_pct.crisis",
    "risk_management.equity_drawdown_guard.enabled",
    "risk_management.equity_drawdown_guard.stop_new_entries_drawdown_pct",
    "risk_management.equity_drawdown_guard.resume_drawdown_pct",
    "risk_management.equity_drawdown_guard.reduced_exposure_pct_when_active",
    "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n",
    "risk_management.stop_loss_pct",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DD20 controlled batch with strict governance and translation auditing.")
    parser.add_argument("--max-candidates", type=int, default=None, help="Optional cap for number of hypotheses to run (after filters).")
    parser.add_argument("--strategy-ids", default="", help="Optional comma-separated strategy_ids to run as a short validation batch.")
    return parser.parse_args()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for line in f:
            if line.strip():
                return ";" if ";" in line else ","
    return ","


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=detect_delimiter(path))
        return [dict(row) for row in reader]


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return default


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_variant(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def flatten_dict(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten_dict(child, next_prefix))
    else:
        out[prefix] = value
    return out


def path_is_covered(declared_path: str, covered_paths: set[str]) -> bool:
    return declared_path in covered_paths or any(
        declared_path.startswith(f"{covered}.") for covered in covered_paths
    )


def materialized_parent_strategy_override_fields(parent_cfg: dict[str, Any], candidate_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Document parent strategy_overrides fields materialized at top-level executable config."""
    if candidate_cfg is None:
        return {}
    documented: dict[str, Any] = {}
    parent_overrides = parent_cfg.get("strategy_overrides") or {}
    for top_key in ("market_filter", "ranking", "risk_filters"):
        declared = parent_overrides.get(top_key)
        if declared is not None and candidate_cfg.get(top_key) == declared:
            documented[f"strategy_overrides.{top_key}"] = {
                "materialized_as": top_key,
                "status": "preserved",
            }
    return documented


def changed_fields_vs_parent(parent_cfg: dict[str, Any], candidate_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parent_flat = flatten_dict(parent_cfg)
    candidate_flat = flatten_dict(candidate_cfg)
    changed: dict[str, dict[str, Any]] = {}
    for key in sorted(set(parent_flat) | set(candidate_flat)):
        p = parent_flat.get(key, "__MISSING__")
        c = candidate_flat.get(key, "__MISSING__")
        if p != c:
            changed[key] = {"parent": p, "candidate": c}
    return changed


def materialize_candidate_config(parent_cfg: dict[str, Any], hypothesis_cfg: dict[str, Any], translated_overrides: dict[str, Any]) -> dict[str, Any]:
    candidate = deep_merge(parent_cfg, translated_overrides)
    candidate["strategy_id"] = str(hypothesis_cfg.get("strategy_id") or parent_cfg.get("strategy_id") or "unknown_strategy")
    if hypothesis_cfg.get("hypothesis_id"):
        candidate["hypothesis_id"] = hypothesis_cfg.get("hypothesis_id")
    if "costs" in parent_cfg:
        costs = deepcopy(parent_cfg.get("costs", {}))
        costs["entry_cost_pct"] = parse_float(costs.get("entry_cost_pct"), 0.24)
        costs["exit_cost_pct"] = parse_float(costs.get("exit_cost_pct"), 0.24)
        candidate["costs"] = costs
    return candidate


def resolve_data_paths() -> tuple[str, str, list[str]]:
    from scripts.research.data_path_resolver import resolve_data_paths as _resolve

    resolution = _resolve(
        weekly_file=None,
        daily_folder=None,
        project_config=PROJECT_CONFIG,
        repo_root=ROOT,
        state_dir=ROOT / "state",
        persist=False,
    )
    if not resolution.can_run or not resolution.weekly_file or not resolution.daily_folder:
        raise RuntimeError(
            "Could not resolve data paths. "
            "Set TRADING_WEEKLY_FILE/TRADING_DAILY_FOLDER or configs/local_data_paths.json."
        )

    weekly = Path(str(resolution.weekly_file))
    daily = Path(str(resolution.daily_folder))
    data_dir = ROOT / "data"
    if (not daily.exists()) or daily.resolve() == ROOT.resolve():
        candidate_daily = None
        if data_dir.exists() and data_dir.is_dir():
            matches = sorted(data_dir.glob("sp500_feature_store_daily_master_*.csv"))
            if matches:
                candidate_daily = data_dir
        if candidate_daily is not None:
            daily = candidate_daily
    return str(weekly), str(daily), list(resolution.warnings)


def load_hypotheses_index() -> list[dict[str, str]]:
    return read_csv_rows(HYPOTHESIS_INDEX)


def load_hypothesis_config(strategy_id: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{strategy_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing hypothesis config: {path}")
    return read_json(path, {})


def load_parent_run_manifest(parent_run_id: str) -> dict[str, Any]:
    path = RUNS_DIR / parent_run_id / "run_manifest.json"
    if not path.exists():
        return {}
    return read_json(path, {})


def load_parent_artifacts(parent_run_id: str) -> dict[str, Any]:
    run_dir = RUNS_DIR / parent_run_id
    return {
        "run_dir": run_dir,
        "metrics": read_json(run_dir / "metrics.json", {}),
        "summary": read_json(run_dir / "spy_comparison_summary.json", {}),
        "yearly": read_csv_rows(run_dir / "spy_comparison_yearly.csv"),
        "monthly": read_csv_rows(run_dir / "spy_comparison_monthly.csv"),
        "summary_md": read_json(run_dir / "summary.md", None),
    }


def load_candidate_artifacts(run_id: str) -> dict[str, Any]:
    run_dir = RUNS_DIR / run_id
    return {
        "run_dir": run_dir,
        "metrics": read_json(run_dir / "metrics.json", {}),
        "summary": read_json(run_dir / "spy_comparison_summary.json", {}),
        "yearly": read_csv_rows(run_dir / "spy_comparison_yearly.csv"),
        "monthly": read_csv_rows(run_dir / "spy_comparison_monthly.csv"),
        "summary_md_exists": (run_dir / "summary.md").exists(),
    }


def extract_dd20_metrics(metrics_payload: dict[str, Any], summary_payload: dict[str, Any]) -> dict[str, Any]:
    strategy = metrics_payload.get("strategy", {}) if isinstance(metrics_payload, dict) else {}
    spy = metrics_payload.get("spy", {}) if isinstance(metrics_payload, dict) else {}
    diagnostics = metrics_payload.get("diagnostics", {}) if isinstance(metrics_payload, dict) else {}
    return {
        "cagr": parse_float(summary_payload.get("strategy_cagr_pct", strategy.get("cagr_pct"))),
        "spy_cagr": parse_float(summary_payload.get("spy_cagr_pct", spy.get("cagr_pct"))),
        "max_drawdown": parse_float(strategy.get("max_drawdown_pct")),
        "years_won": parse_int(summary_payload.get("years_beating_spy")),
        "years_lost": 0,
        "months_won": parse_int(summary_payload.get("months_beating_spy")),
        "months_lost": 0,
        "calmar": parse_float(strategy.get("cagr_pct")) / abs(parse_float(strategy.get("max_drawdown_pct"))) if parse_float(strategy.get("max_drawdown_pct")) else 0.0,
        "trades": parse_int(diagnostics.get("number_of_trades")),
        "decision": str(summary_payload.get("recommendation_hint", "")),
        "rejection_reason": "",
    }


def extract_strategy_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    strategy = metrics_payload.get("strategy", {}) if isinstance(metrics_payload, dict) else {}
    spy = metrics_payload.get("spy", {}) if isinstance(metrics_payload, dict) else {}
    diagnostics = metrics_payload.get("diagnostics", {}) if isinstance(metrics_payload, dict) else {}
    return {
        "strategy_cagr": parse_float(strategy.get("cagr_pct")),
        "strategy_total_return_pct": parse_float(strategy.get("total_return_pct")),
        "strategy_max_drawdown_pct": parse_float(strategy.get("max_drawdown_pct")),
        "spy_cagr": parse_float(spy.get("cagr_pct")),
        "spy_total_return_pct": parse_float(spy.get("total_return_pct")),
        "spy_max_drawdown_pct": parse_float(spy.get("max_drawdown_pct")),
        "trades": parse_int(diagnostics.get("number_of_trades")),
        "number_of_rebalances": parse_int(diagnostics.get("number_of_rebalances")),
    }


def get_parent_strategy_config_path(parent_run_id: str) -> Path | None:
    manifest = load_parent_run_manifest(parent_run_id)
    raw = manifest.get("strategy_config_path")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def translate_hypothesis_for_execution(
    hypothesis: dict[str, Any],
    parent_cfg: dict[str, Any],
    family: str,
) -> dict[str, Any]:
    """Translate DD20 hypothesis controls into an executable strategy config."""
    family = str(family).strip()
    hypothesis_cfg = deepcopy(hypothesis)
    overrides = deepcopy(hypothesis_cfg.get("strategy_overrides") or {})
    variant = parse_variant(hypothesis_cfg.get("variant"))
    translated_overrides: dict[str, Any] = {}
    translated_controls: dict[str, Any] = {}
    unsupported_controls: list[str] = []
    ignored_controls: list[str] = []
    support_issue: str | None = None
    note = ""

    if family == "spy_fallback_partial":
        fallback_pct = (
            variant.get("spy_fallback_partial_pct")
            or variant.get("fallback_pct")
            or hypothesis_cfg.get("spy_fallback_partial_pct")
        )
        unsupported_controls.append("risk_management.spy_fallback_partial_pct")
        support_issue = (
            "spy_fallback_partial_pct is not supported by the current backtester; "
            f"requested value={fallback_pct!r}."
        )

    elif family == "topn_dynamic":
        entry_declared = deepcopy(overrides.get("entry_rule") or {})
        strong_topn = parse_int(
            entry_declared.get("top_n_strong_regime", entry_declared.get("top_n", variant.get("strong_topn"))),
            parse_int((parent_cfg.get("entry_rule") or {}).get("top_n"), 12),
        )
        weak_topn = parse_int(
            entry_declared.get("top_n_weak_regime", variant.get("weak_topn")),
            8,
        )
        if entry_declared.get("type") == "top_n_dynamic":
            ignored_controls.extend(
                [
                    "entry_rule.type=top_n_dynamic",
                    "entry_rule.top_n_strong_regime",
                    "entry_rule.top_n_weak_regime",
                ]
            )
        translated_overrides["entry_rule"] = {
            "type": "top_n",
            "top_n": strong_topn,
            "by": (parent_cfg.get("entry_rule") or {}).get("by", "ret_52w_pct"),
        }
        market_filter = deepcopy(overrides.get("market_filter") or parent_cfg.get("market_filter") or {})
        market_filter["soft_weak_regime_top_n"] = weak_topn
        market_filter["benchmark"] = "SPY"
        market_filter["require_positive_trend"] = bool(market_filter.get("require_positive_trend", True))
        translated_overrides["market_filter"] = market_filter
        translated_controls["entry_rule.top_n"] = strong_topn
        translated_controls["market_filter.soft_weak_regime_top_n"] = weak_topn
        note = (
            f"Translated top_n_dynamic -> entry_rule.top_n={strong_topn}, "
            f"market_filter.soft_weak_regime_top_n={weak_topn}."
        )

    elif family == "guardrail_dynamic":
        rm_declared = deepcopy(overrides.get("risk_management") or {})
        guard_declared = deepcopy(rm_declared.get("equity_drawdown_guard") or {})
        rm = deepcopy(parent_cfg.get("risk_management") or {})
        guard = deepcopy(rm.get("equity_drawdown_guard") or {})
        if "max_gross_exposure_pct" in rm_declared:
            rm["max_gross_exposure_pct"] = rm_declared["max_gross_exposure_pct"]
            translated_controls["risk_management.max_gross_exposure_pct"] = rm_declared["max_gross_exposure_pct"]
        for key in (
            "enabled",
            "stop_new_entries_drawdown_pct",
            "resume_drawdown_pct",
            "reduced_exposure_pct_when_active",
            "allow_entries_when_active_top_n",
        ):
            if key in guard_declared:
                guard[key] = guard_declared[key]
                translated_controls[f"risk_management.equity_drawdown_guard.{key}"] = guard_declared[key]
        rm["equity_drawdown_guard"] = guard
        translated_overrides["risk_management"] = rm
        note = "Applied guardrail_dynamic controls to equity_drawdown_guard."

    elif family == "dd_compression":
        rm_declared = deepcopy(overrides.get("risk_management") or {})
        guard_declared = deepcopy(rm_declared.get("equity_drawdown_guard") or {})
        rm = deepcopy(parent_cfg.get("risk_management") or {})
        guard = deepcopy(rm.get("equity_drawdown_guard") or {})

        target_dd = guard_declared.get("max_drawdown_target_pct", variant.get("target_max_drawdown_pct"))
        if target_dd is not None:
            unsupported_controls.append("risk_management.equity_drawdown_guard.max_drawdown_target_pct")
            ignored_controls.append("risk_management.equity_drawdown_guard.max_drawdown_target_pct")

        gross = parse_int(
            rm_declared.get("max_gross_exposure_pct", variant.get("max_gross_exposure_pct")),
            parse_int(rm.get("max_gross_exposure_pct"), 50),
        )
        rm["max_gross_exposure_pct"] = gross
        translated_controls["risk_management.max_gross_exposure_pct"] = gross
        for key in ("enabled", "stop_new_entries_drawdown_pct", "resume_drawdown_pct", "reduced_exposure_pct_when_active"):
            if key in guard_declared:
                guard[key] = guard_declared[key]
                translated_controls[f"risk_management.equity_drawdown_guard.{key}"] = guard_declared[key]
        rm["equity_drawdown_guard"] = guard
        translated_overrides["risk_management"] = rm
        note = (
            "Applied dd_compression controls to max_gross_exposure_pct/equity_drawdown_guard; "
            "direct max_drawdown_target_pct is unsupported and ignored."
        )

    else:
        support_issue = f"Unknown or unsupported hypothesis family: {family}"

    translated_risk_fields = [
        k for k in translated_controls
        if k.startswith("risk_management.") or k.startswith("market_filter.")
    ]

    if support_issue:
        return {
            "family": family,
            "executable_config": None,
            "support_issue": support_issue,
            "engine_translation_note": note,
            "translated_controls": translated_controls,
            "unsupported_controls": unsupported_controls,
            "ignored_controls": ignored_controls,
            "risk_control_fields_applied": [],
            "risk_control_fields_ignored": [
                c for c in unsupported_controls + ignored_controls if c.startswith("risk_management.") or c.startswith("market_filter.")
            ],
        }

    executable = materialize_candidate_config(parent_cfg, hypothesis_cfg, translated_overrides)
    executable["engine_translation_note"] = note
    executable["strategy_overrides"] = translated_overrides
    return {
        "family": family,
        "executable_config": executable,
        "support_issue": None,
        "engine_translation_note": note,
        "translated_controls": translated_controls,
        "unsupported_controls": unsupported_controls,
        "ignored_controls": ignored_controls,
        "risk_control_fields_applied": translated_risk_fields,
        "risk_control_fields_ignored": [
            c for c in unsupported_controls + ignored_controls if c.startswith("risk_management.") or c.startswith("market_filter.")
        ],
    }


def build_run_command(
    *,
    weekly_file: str,
    daily_folder: str,
    strategy_config: Path,
    parent_strategy_config: Path,
    run_id: str,
    parent_run_id: str,
) -> list[str]:
    return [
        sys.executable,
        str(RUN_BACKTEST),
        "--weekly-file",
        weekly_file,
        "--daily-folder",
        daily_folder,
        "--strategy-config",
        str(strategy_config),
        "--project-config",
        str(PROJECT_CONFIG),
        "--run-id",
        run_id,
        "--runs-dir",
        str(RUNS_DIR),
        "--parent-run-id",
        parent_run_id,
        "--parent-strategy-config",
        str(parent_strategy_config),
    ]


def compare_rows(candidate: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    c = candidate
    p = parent
    candidate_dd = parse_float(c.get("max_drawdown_pct", c.get("max_drawdown")))
    parent_dd = parse_float(p.get("max_drawdown_pct", p.get("max_drawdown")))
    return {
        "run_id": c["run_id"],
        "strategy_id": c["strategy_id"],
        "family": c["family"],
        "parent_run_id": c["parent_run_id"],
        "parent_strategy_id": c["parent_strategy_id"],
        "candidate_cagr": c["cagr"],
        "candidate_max_drawdown_pct": candidate_dd,
        "candidate_years_won_vs_spy": c["years_won"],
        "candidate_months_won_vs_spy": c["months_won"],
        "candidate_trades": c["trades"],
        "candidate_calmar_ratio": c["calmar"],
        "parent_cagr": p["cagr"],
        "parent_max_drawdown_pct": parent_dd,
        "parent_years_won_vs_spy": p["years_won"],
        "parent_months_won_vs_spy": p["months_won"],
        "parent_trades": p["trades"],
        "parent_calmar_ratio": p["calmar"],
        "cagr_delta_vs_parent": c["cagr"] - p["cagr"],
        "dd_delta_vs_parent": candidate_dd - parent_dd,
        "years_won_delta_vs_parent": c["years_won"] - p["years_won"],
        "months_won_delta_vs_parent": c["months_won"] - p["months_won"],
        "trades_delta_vs_parent": c["trades"] - p["trades"],
        "accepted_rule": c.get("accepted_rule", ""),
        "rejection_reason": c.get("rejection_reason", ""),
        "support_status": c.get("support_status", ""),
        "support_issue": c.get("support_issue", ""),
    }


def classify_candidate(row: dict[str, Any], parent: dict[str, Any], effective_audit: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return (status, reason)."""
    if row.get("support_status") == "requires_engine_support":
        return "requires_engine_support", str(row.get("support_issue") or "Engine support missing for at least one required field.")

    cagr = parse_float(row.get("cagr"))
    spy_cagr = parse_float(row.get("spy_cagr"))
    dd = parse_float(row.get("max_drawdown"))
    parent_cagr = parse_float(parent.get("cagr"))
    parent_dd = parse_float(parent.get("max_drawdown"))
    years_won = parse_int(row.get("years_won"))
    months_won = parse_int(row.get("months_won"))
    parent_years_won = parse_int(parent.get("years_won"))
    parent_months_won = parse_int(parent.get("months_won"))
    cagr_delta = cagr - parent_cagr
    dd_delta = dd - parent_dd
    years_delta = years_won - parent_years_won
    months_delta = months_won - parent_months_won

    almost_no_effect = (
        abs(cagr_delta) < 0.10
        and abs(dd_delta) < 0.10
        and years_delta == 0
        and months_delta == 0
        and abs(parse_int(row.get("trades")) - parse_int(parent.get("trades"))) <= 5
    )
    if almost_no_effect:
        return "no_effect", "Result is identical or almost identical to the parent DD20 run."

    risk_applied = list((effective_audit or {}).get("risk_control_fields_applied") or [])
    if dd < -20.0 and not risk_applied:
        return "dd20_control_not_effective", "DD20 control declared but no risk controls were effectively applied in executable config."
    if dd < -20.0:
        return "rejected", "Breaks DD20: max_drawdown_pct is worse than -20%."
    if cagr <= spy_cagr:
        return "rejected", "CAGR does not exceed SPY."

    material_improvement = (
        cagr_delta >= 0.50
        or (-dd - (-parent_dd)) >= 1.0
        or years_delta >= 1
        or months_delta >= 6
    )
    if not material_improvement:
        return "no_effect", "No material improvement versus parent DD20 metrics."

    severe_regression = (
        (cagr_delta < -0.25)
        or (dd_delta > 1.0)
        or (years_delta <= -1)
        or (months_delta <= -6)
    )
    if severe_regression:
        return "rejected", "Improves one metric but regresses another too much."

    if dd >= -20.0 and cagr > spy_cagr and material_improvement:
        return "accepted_candidate", "Meets DD20, beats SPY, and improves at least one material metric versus parent."

    return "rejected", "Did not satisfy acceptance criteria."


def build_effective_config_audit(
    *,
    run_id: str,
    hypothesis_id: str,
    family: str,
    parent_cfg: dict[str, Any],
    candidate_cfg: dict[str, Any] | None,
    hypothesis_cfg: dict[str, Any],
    translation: dict[str, Any],
) -> dict[str, Any]:
    declared_controls = flatten_dict(hypothesis_cfg.get("strategy_overrides") or {})
    translated_controls = translation.get("translated_controls") or {}
    unsupported_controls = list(translation.get("unsupported_controls") or [])
    ignored_controls = list(translation.get("ignored_controls") or [])
    parent_hash = canonical_hash(parent_cfg)
    candidate_hash = canonical_hash(candidate_cfg) if candidate_cfg is not None else ""
    changed = changed_fields_vs_parent(parent_cfg, candidate_cfg or parent_cfg)
    effect_signature_payload = {
        "family": family,
        "translated_controls": translated_controls,
        "unsupported_controls": unsupported_controls,
        "ignored_controls": ignored_controls,
        "changed_fields": sorted(changed.keys()),
    }
    effect_signature = canonical_hash(effect_signature_payload)
    risk_applied = list(translation.get("risk_control_fields_applied") or [])
    risk_ignored = list(translation.get("risk_control_fields_ignored") or [])
    materialized_parent_overrides = materialized_parent_strategy_override_fields(parent_cfg, candidate_cfg)
    covered_controls = set(translated_controls) | set(unsupported_controls) | set(ignored_controls) | set(risk_applied) | set(risk_ignored)
    missing_declared_controls = sorted(
        path for path in declared_controls
        if not path_is_covered(path, covered_controls)
    )
    effect_signature_equals_parent = len(changed) == 0
    if translation.get("support_issue"):
        conclusion = "requires_engine_support"
    elif missing_declared_controls:
        conclusion = "declared_controls_not_fully_accounted"
    elif effect_signature_equals_parent:
        conclusion = "translation_collapse_no_effective_change"
    elif not translated_controls:
        conclusion = "translation_collapse_no_translated_controls"
    else:
        conclusion = "translated_controls_applied"
    return {
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "declared_controls": declared_controls,
        "translated_controls": translated_controls,
        "unsupported_controls": unsupported_controls,
        "ignored_controls": ignored_controls,
        "parent_config_hash": parent_hash,
        "candidate_config_hash": candidate_hash,
        "effect_signature": effect_signature,
        "effect_signature_equals_parent": effect_signature_equals_parent,
        "changed_fields_vs_parent": changed,
        "materialized_parent_strategy_overrides": materialized_parent_overrides,
        "risk_control_fields_applied": risk_applied,
        "risk_control_fields_ignored": risk_ignored,
        "covered_controls": sorted(covered_controls),
        "missing_declared_controls": missing_declared_controls,
        "conclusion": conclusion,
    }


def restore_audit_json(
    *,
    run_id: str,
    family: str,
    status: str,
    decision_reason: str,
    support_status: str,
    support_issue: str,
    effective_audit: dict[str, Any],
) -> dict[str, Any]:
    artifacts = load_candidate_artifacts(run_id)
    metrics = artifacts.get("metrics", {})
    summary = artifacts.get("summary", {})
    yearly = artifacts.get("yearly", [])
    monthly = artifacts.get("monthly", [])
    strategy_metrics = extract_strategy_metrics(metrics)
    dd20 = extract_dd20_metrics(metrics, summary)
    missing = []
    run_dir = artifacts["run_dir"]
    for name in ("metrics.json", "summary.md", "spy_comparison_daily.csv", "spy_comparison_monthly.csv", "spy_comparison_yearly.csv"):
        if not (run_dir / name).exists():
            missing.append(name)

    infrastructure_flags: list[str] = []
    risk_flags: list[str] = []
    if support_status == "requires_engine_support":
        infrastructure_flags.append("requires_engine_support")
    if effective_audit.get("conclusion", "").startswith("translation_collapse"):
        infrastructure_flags.append("translation_collapse")
    if effective_audit.get("conclusion") == "declared_controls_not_fully_accounted":
        infrastructure_flags.append("declared_controls_not_fully_accounted")
    if missing:
        infrastructure_flags.append("missing_artifacts")
    if parse_float(strategy_metrics.get("strategy_max_drawdown_pct")) < -20.0:
        risk_flags.append("dd20_broken")
    if parse_float(strategy_metrics.get("strategy_cagr")) <= parse_float(strategy_metrics.get("spy_cagr")):
        risk_flags.append("cagr_not_beating_spy")
    if status == "dd20_control_not_effective":
        risk_flags.append("dd20_control_not_effective")

    accepted_for_followup = status == "accepted_candidate"
    if "translation_collapse" in infrastructure_flags:
        accepted_for_followup = False
    if "declared_controls_not_fully_accounted" in infrastructure_flags:
        accepted_for_followup = False

    payload = {
        "run_id": run_id,
        "strategy_id": run_id,
        "family": family,
        "promoted_to_baseline": False,
        "accepted_for_followup": accepted_for_followup,
        "decision": status,
        "decision_reason": decision_reason,
        "infrastructure_flags": infrastructure_flags,
        "risk_flags": risk_flags,
        "missing_artifacts": missing,
        "metrics": {
            "strategy_cagr_pct": strategy_metrics.get("strategy_cagr"),
            "strategy_max_drawdown_pct": strategy_metrics.get("strategy_max_drawdown_pct"),
            "strategy_total_return_pct": strategy_metrics.get("strategy_total_return_pct"),
            "spy_cagr_pct": strategy_metrics.get("spy_cagr"),
            "spy_total_return_pct": strategy_metrics.get("spy_total_return_pct"),
            "years_beating_spy": dd20.get("years_won"),
            "months_beating_spy": dd20.get("months_won"),
            "trades": strategy_metrics.get("trades"),
        },
        "comparison_summary": summary,
        "comparison_rows": {
            "yearly_rows": len(yearly),
            "monthly_rows": len(monthly),
        },
        "support_status": support_status,
        "support_issue": support_issue,
        "effective_config_audit_path": str((run_dir / "effective_config_audit.json").resolve()),
    }
    write_json(run_dir / "audit.json", payload)
    return payload


def detect_translation_collapse(rows: list[dict[str, Any]]) -> tuple[bool, dict[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for row in rows:
        if str(row.get("status")) in {"requires_engine_support", "run_failed"}:
            continue
        key = json.dumps(
            {
                "cagr": round(parse_float(row.get("candidate_cagr")), 2),
                "dd": round(parse_float(row.get("candidate_max_drawdown_pct")), 2),
                "years": parse_int(row.get("candidate_years_won_vs_spy")),
                "trades": parse_int(row.get("candidate_trades")),
                "effect_signature": row.get("effect_signature", ""),
            },
            sort_keys=True,
        )
        groups.setdefault(key, []).append(str(row.get("strategy_id", "")))
    collapsed = {k: v for k, v in groups.items() if len(v) > 1}
    return bool(collapsed), collapsed


def filter_rankable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if str(row.get("status")) not in {"requires_engine_support", "run_failed"}
    ]


def main(args: argparse.Namespace | None = None) -> int:
    args = args or parse_args()
    HYPOTHESIS_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    batch_dir = BATCH_REPORT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir.mkdir(parents=True, exist_ok=False)
    exec_cfg_dir = batch_dir / GENERATED_EXEC_CONFIGS_DIRNAME
    logs_dir = batch_dir / RUN_LOGS_DIRNAME
    effective_audits_dir = batch_dir / EFFECTIVE_AUDITS_DIRNAME
    restored_audits_dir = batch_dir / RESTORED_AUDITS_DIRNAME
    exec_cfg_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    effective_audits_dir.mkdir(parents=True, exist_ok=True)
    restored_audits_dir.mkdir(parents=True, exist_ok=True)

    weekly_file, daily_folder, resolver_warnings = resolve_data_paths()
    hypotheses = load_hypotheses_index()
    if not hypotheses:
        raise RuntimeError(f"No hypotheses found at {HYPOTHESIS_INDEX}")
    requested_ids = {x.strip() for x in str(args.strategy_ids or "").split(",") if x.strip()}
    if requested_ids:
        hypotheses = [row for row in hypotheses if str(row.get("strategy_id") or "").strip() in requested_ids]
    if args.max_candidates is not None and args.max_candidates >= 0:
        hypotheses = hypotheses[: int(args.max_candidates)]
    if not hypotheses:
        raise RuntimeError("No hypotheses selected after applying --strategy-ids / --max-candidates filters.")

    batch_rows: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    no_effect_rows: list[dict[str, Any]] = []
    unsupported_rows: list[dict[str, Any]] = []
    dd20_not_effective_rows: list[dict[str, Any]] = []
    parent_comparison_rows: list[dict[str, Any]] = []
    spy_yearly_rows: list[dict[str, Any]] = []
    spy_monthly_rows: list[dict[str, Any]] = []
    executed_results: dict[str, dict[str, Any]] = {}

    for hyp_row in hypotheses:
        strategy_id = str(hyp_row.get("strategy_id") or "").strip()
        family = str(hyp_row.get("family") or "").strip()
        parent_run_id = str(hyp_row.get("parent_strategy") or "").strip()
        if not strategy_id:
            continue

        hyp_cfg = load_hypothesis_config(strategy_id)
        parent_manifest = load_parent_run_manifest(parent_run_id)
        parent_cfg_path = parent_manifest.get("strategy_config_path")
        if not parent_cfg_path:
            support_row = {
                "run_id": strategy_id,
                "strategy_id": strategy_id,
                "family": family,
                "parent_run_id": parent_run_id,
                "parent_strategy_id": parent_manifest.get("strategy_id", ""),
                "support_status": "requires_engine_support",
                "support_issue": f"Could not resolve parent strategy config path from runs/{parent_run_id}/run_manifest.json.",
            }
            batch_rows.append(support_row)
            unsupported_rows.append(support_row)
            continue

        parent_cfg_path = Path(parent_cfg_path)
        if not parent_cfg_path.is_absolute():
            parent_cfg_path = ROOT / parent_cfg_path
        if not parent_cfg_path.exists():
            support_row = {
                "run_id": strategy_id,
                "strategy_id": strategy_id,
                "family": family,
                "parent_run_id": parent_run_id,
                "parent_strategy_id": parent_manifest.get("strategy_id", ""),
                "support_status": "requires_engine_support",
                "support_issue": f"Parent strategy config missing: {parent_cfg_path}",
            }
            batch_rows.append(support_row)
            unsupported_rows.append(support_row)
            continue

        parent_cfg = read_json(parent_cfg_path, {})
        parent_artifacts = load_parent_artifacts(parent_run_id)
        parent_dd20 = extract_dd20_metrics(parent_artifacts.get("metrics", {}), parent_artifacts.get("summary", {}))
        parent_metrics = extract_strategy_metrics(parent_artifacts.get("metrics", {}))
        parent_profile = {
            "run_id": parent_run_id,
            "strategy_id": parent_manifest.get("strategy_id", ""),
            "cagr": parent_dd20["cagr"] if parent_dd20["cagr"] else parent_metrics["strategy_cagr"],
            "max_drawdown": parent_dd20["max_drawdown"] if parent_dd20["max_drawdown"] else parent_metrics["strategy_max_drawdown_pct"],
            "years_won": parent_dd20["years_won"],
            "months_won": parent_dd20["months_won"],
            "trades": parent_dd20["trades"] or parent_metrics["trades"],
            "calmar": parent_dd20["calmar"],
        }

        translation = translate_hypothesis_for_execution(hyp_cfg, parent_cfg, family)
        exec_hypothesis = translation.get("executable_config")
        support_issue = translation.get("support_issue")
        support_status = "supported" if exec_hypothesis is not None else "requires_engine_support"
        support_note = str(translation.get("engine_translation_note") or "")

        effective_audit = build_effective_config_audit(
            run_id=strategy_id,
            hypothesis_id=str(hyp_cfg.get("hypothesis_id") or strategy_id),
            family=family,
            parent_cfg=parent_cfg,
            candidate_cfg=exec_hypothesis,
            hypothesis_cfg=hyp_cfg,
            translation=translation,
        )
        effective_audit_path = effective_audits_dir / strategy_id / "effective_config_audit.json"
        write_json(effective_audit_path, effective_audit)

        base_row = {
            "run_id": strategy_id,
            "strategy_id": strategy_id,
            "family": family,
            "parent_run_id": parent_run_id,
            "parent_strategy_id": parent_manifest.get("strategy_id", ""),
            "parent_strategy_config_path": str(parent_cfg_path),
            "support_status": support_status,
            "support_issue": support_issue or "",
            "engine_translation_note": support_note,
            "config_path": str((CONFIG_DIR / f"{strategy_id}.json").resolve()),
            "weekly_file": weekly_file,
            "daily_folder": daily_folder,
            "batch_dir": str(batch_dir),
            "effect_signature": effective_audit.get("effect_signature", ""),
            "effective_config_audit_path": str(effective_audit_path.resolve()),
        }

        if exec_hypothesis is None:
            base_row["status"] = "requires_engine_support"
            base_row["decision_reason"] = support_issue or "Engine support missing for at least one required field."
            batch_rows.append(base_row)
            unsupported_rows.append(base_row)
            continue

        candidate_run_dir = RUNS_DIR / strategy_id
        cached_candidate = (
            (candidate_run_dir / "metrics.json").exists()
            and (candidate_run_dir / "spy_comparison_summary.json").exists()
            and (candidate_run_dir / "spy_comparison_yearly.csv").exists()
            and (candidate_run_dir / "spy_comparison_monthly.csv").exists()
        )

        if not cached_candidate:
            exec_config_path = exec_cfg_dir / f"{strategy_id}.json"
            write_json(exec_config_path, exec_hypothesis)

            cmd = build_run_command(
                weekly_file=weekly_file,
                daily_folder=daily_folder,
                strategy_config=exec_config_path,
                parent_strategy_config=parent_cfg_path,
                run_id=strategy_id,
                parent_run_id=parent_run_id,
            )

            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            stdout_path = logs_dir / f"{strategy_id}.stdout.log"
            stderr_path = logs_dir / f"{strategy_id}.stderr.log"
            stdout_path.write_text(proc.stdout or "", encoding="utf-8")
            stderr_path.write_text(proc.stderr or "", encoding="utf-8")

            if proc.returncode != 0:
                error_text = (proc.stderr or proc.stdout or "").lower()
                if any(token in error_text for token in ("unsupported", "not supported", "unknown field", "keyerror", "attributeerror")):
                    base_row.update(
                        {
                            "support_status": "requires_engine_support",
                            "status": "requires_engine_support",
                            "decision_reason": "Backtest rejected unsupported config field.",
                            "support_issue": proc.stderr.strip()[:500] if proc.stderr else "Backtest rejected unsupported config field.",
                        }
                    )
                    batch_rows.append(base_row)
                    unsupported_rows.append(base_row)
                    continue
                base_row.update(
                    {
                        "support_status": "supported",
                        "execution_status": "run_failed",
                        "status": "run_failed",
                        "decision_reason": f"Backtest failed with return code {proc.returncode}.",
                        "rejection_reason": f"Backtest failed with return code {proc.returncode}.",
                    }
                )
                batch_rows.append(base_row)
                rejected_rows.append(base_row)
                continue
        else:
            run_manifest = read_json(candidate_run_dir / "run_manifest.json", {})
            cached_hash = str(run_manifest.get("config_hash") or "").strip()
            current_hash = canonical_hash(exec_hypothesis)
            if cached_hash and cached_hash != current_hash:
                exec_config_path = exec_cfg_dir / f"{strategy_id}.json"
                write_json(exec_config_path, exec_hypothesis)
                cmd = build_run_command(
                    weekly_file=weekly_file,
                    daily_folder=daily_folder,
                    strategy_config=exec_config_path,
                    parent_strategy_config=parent_cfg_path,
                    run_id=strategy_id,
                    parent_run_id=parent_run_id,
                )
                proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                stdout_path = logs_dir / f"{strategy_id}.stdout.log"
                stderr_path = logs_dir / f"{strategy_id}.stderr.log"
                stdout_path.write_text(proc.stdout or "", encoding="utf-8")
                stderr_path.write_text(proc.stderr or "", encoding="utf-8")
                if proc.returncode != 0:
                    base_row.update(
                        {
                            "support_status": "supported",
                            "execution_status": "run_failed",
                            "status": "run_failed",
                            "decision_reason": f"Backtest failed with return code {proc.returncode} after cache invalidation rerun.",
                            "rejection_reason": f"Backtest failed with return code {proc.returncode} after cache invalidation rerun.",
                        }
                    )
                    batch_rows.append(base_row)
                    rejected_rows.append(base_row)
                    continue

        candidate_artifacts = load_candidate_artifacts(strategy_id)
        candidate_dd20 = extract_dd20_metrics(candidate_artifacts.get("metrics", {}), candidate_artifacts.get("summary", {}))
        candidate_metrics = extract_strategy_metrics(candidate_artifacts.get("metrics", {}))

        candidate_profile = {
            "run_id": strategy_id,
            "strategy_id": strategy_id,
            "cagr": candidate_dd20["cagr"] or candidate_metrics["strategy_cagr"],
            "spy_cagr": candidate_dd20["spy_cagr"] or candidate_metrics["spy_cagr"],
            "max_drawdown": candidate_dd20["max_drawdown"] or candidate_metrics["strategy_max_drawdown_pct"],
            "years_won": candidate_dd20["years_won"],
            "months_won": candidate_dd20["months_won"],
            "trades": candidate_dd20["trades"] or candidate_metrics["trades"],
            "calmar": candidate_dd20["calmar"],
            "accepted_rule": "",
            "rejection_reason": candidate_dd20["rejection_reason"],
            "support_status": "supported",
            "support_issue": "",
            "family": family,
        }

        status, reason = classify_candidate(candidate_profile, parent_profile, effective_audit)
        candidate_profile["accepted_rule"] = reason
        candidate_profile["status"] = status
        candidate_profile["parent_run_id"] = parent_run_id
        candidate_profile["parent_strategy_id"] = parent_manifest.get("strategy_id", "")
        candidate_profile["strategy_id"] = strategy_id

        compare_row = compare_rows(candidate_profile, parent_profile)
        compare_row.update(
            {
                "status": status,
                "decision_reason": reason,
                "engine_translation_note": support_note,
                "support_status": "supported",
                "support_issue": "",
                "candidate_summary_path": str((ROOT / "runs" / strategy_id / "summary.md").resolve()),
                "candidate_audit_status": candidate_dd20["decision"] or "",
                "candidate_rejection_reason": candidate_dd20["rejection_reason"] or "",
                "effect_signature": effective_audit.get("effect_signature", ""),
                "effective_config_audit_path": str(effective_audit_path.resolve()),
            }
        )
        batch_rows.append(compare_row)
        parent_comparison_rows.append(compare_row)
        executed_results[strategy_id] = {
            "status": status,
            "reason": reason,
            "cagr": candidate_profile["cagr"],
            "max_drawdown": candidate_profile["max_drawdown"],
            "years_won": candidate_profile["years_won"],
            "months_won": candidate_profile["months_won"],
        }

        # Aggregate per-run SPY comparison rows.
        for row in candidate_artifacts.get("yearly", []):
            spy_yearly_rows.append(
                {
                    "run_id": strategy_id,
                    "strategy_id": strategy_id,
                    "year": row.get("year", ""),
                    "strategy_return_pct": row.get("strategy_return_pct", ""),
                    "spy_return_pct": row.get("spy_return_pct", ""),
                    "diff_pct": row.get("excess_return_pct", row.get("diff_pct", "")),
                    "mark": row.get("winner", ""),
                }
            )
        for row in candidate_artifacts.get("monthly", []):
            spy_monthly_rows.append(
                {
                    "run_id": strategy_id,
                    "strategy_id": strategy_id,
                    "year": row.get("year", ""),
                    "month": row.get("month", ""),
                    "period": f"{row.get('year', '')}-{str(row.get('month', '')).zfill(2)}",
                    "strategy_return_pct": row.get("strategy_return_pct", ""),
                    "spy_return_pct": row.get("spy_return_pct", ""),
                    "diff_pct": row.get("excess_return_pct", row.get("diff_pct", "")),
                    "mark": row.get("winner", ""),
                }
            )

        write_json(candidate_artifacts["run_dir"] / "effective_config_audit.json", effective_audit)
        restored = restore_audit_json(
            run_id=strategy_id,
            family=family,
            status=status,
            decision_reason=reason,
            support_status="supported",
            support_issue="",
            effective_audit=effective_audit,
        )
        write_json(restored_audits_dir / f"{strategy_id}.audit.json", restored)

        if status == "accepted_candidate":
            accepted_rows.append(compare_row)
        elif status == "dd20_control_not_effective":
            dd20_not_effective_rows.append(compare_row)
            rejected_rows.append(compare_row)
        elif status == "no_effect":
            no_effect_rows.append(compare_row)
        else:
            rejected_rows.append(compare_row)

    # Stable output order.
    def sort_key(row: dict[str, Any]) -> tuple:
        return (str(row.get("family", "")), str(row.get("strategy_id", "")))

    batch_rows.sort(key=sort_key)
    accepted_rows.sort(key=sort_key)
    rejected_rows.sort(key=sort_key)
    no_effect_rows.sort(key=sort_key)
    unsupported_rows.sort(key=sort_key)
    parent_comparison_rows.sort(key=sort_key)

    # Write batch outputs.
    batch_summary_fields = [
        "run_id",
        "strategy_id",
        "family",
        "parent_run_id",
        "parent_strategy_id",
        "support_status",
        "support_issue",
        "engine_translation_note",
        "status",
        "decision_reason",
        "candidate_cagr",
        "candidate_max_drawdown_pct",
        "candidate_years_won_vs_spy",
        "candidate_months_won_vs_spy",
        "candidate_trades",
        "candidate_calmar_ratio",
        "parent_cagr",
        "parent_max_drawdown_pct",
        "parent_years_won_vs_spy",
        "parent_months_won_vs_spy",
        "parent_trades",
        "parent_calmar_ratio",
        "cagr_delta_vs_parent",
        "dd_delta_vs_parent",
        "years_won_delta_vs_parent",
        "months_won_delta_vs_parent",
        "trades_delta_vs_parent",
        "accepted_rule",
        "rejection_reason",
        "candidate_summary_path",
        "candidate_audit_status",
        "candidate_rejection_reason",
        "effect_signature",
        "effective_config_audit_path",
        "config_path",
        "parent_strategy_config_path",
        "weekly_file",
        "daily_folder",
        "batch_dir",
    ]

    # Normalize keys for rows that are not full comparison rows.
    normalized_batch_rows: list[dict[str, Any]] = []
    for row in batch_rows:
        norm = {k: row.get(k, "") for k in batch_summary_fields}
        if not norm.get("candidate_cagr") and row.get("cagr") is not None:
            norm["candidate_cagr"] = row.get("cagr", "")
        if not norm.get("candidate_max_drawdown_pct") and row.get("max_drawdown") is not None:
            norm["candidate_max_drawdown_pct"] = row.get("max_drawdown", "")
        if not norm.get("candidate_years_won_vs_spy") and row.get("years_won") is not None:
            norm["candidate_years_won_vs_spy"] = row.get("years_won", "")
        if not norm.get("candidate_months_won_vs_spy") and row.get("months_won") is not None:
            norm["candidate_months_won_vs_spy"] = row.get("months_won", "")
        if not norm.get("candidate_trades") and row.get("trades") is not None:
            norm["candidate_trades"] = row.get("trades", "")
        if not norm.get("candidate_calmar_ratio") and row.get("calmar") is not None:
            norm["candidate_calmar_ratio"] = row.get("calmar", "")
        normalized_batch_rows.append(norm)

    batch_invalid_translation_collapse, collapse_groups = detect_translation_collapse(normalized_batch_rows)
    if batch_invalid_translation_collapse:
        collapsed_strategy_ids = {sid for values in collapse_groups.values() for sid in values}
        for row in normalized_batch_rows:
            sid = str(row.get("strategy_id", ""))
            if sid in collapsed_strategy_ids:
                row["decision_reason"] = "batch_invalid_translation_collapse"
        for sid in collapsed_strategy_ids:
            audit_path = RUNS_DIR / sid / "audit.json"
            payload = read_json(audit_path, {})
            if isinstance(payload, dict) and payload:
                infra = list(payload.get("infrastructure_flags", []))
                if "batch_invalid_translation_collapse" not in infra:
                    infra.append("batch_invalid_translation_collapse")
                payload["infrastructure_flags"] = infra
                payload["accepted_for_followup"] = False
                if payload.get("decision") == "accepted_candidate":
                    payload["decision"] = "batch_invalid_translation_collapse"
                    payload["decision_reason"] = "batch_invalid_translation_collapse"
                write_json(audit_path, payload)

    write_csv_rows(batch_dir / "batch_summary.csv", normalized_batch_rows, batch_summary_fields)
    write_csv_rows(batch_dir / "accepted_candidates.csv", accepted_rows, [k for k in batch_summary_fields if k not in {"config_path", "parent_strategy_config_path", "weekly_file", "daily_folder", "batch_dir"}])
    write_csv_rows(batch_dir / "rejected_candidates.csv", rejected_rows, [k for k in batch_summary_fields if k not in {"config_path", "parent_strategy_config_path", "weekly_file", "daily_folder", "batch_dir"}])
    write_csv_rows(batch_dir / "dd20_control_not_effective.csv", dd20_not_effective_rows, [k for k in batch_summary_fields if k not in {"config_path", "parent_strategy_config_path", "weekly_file", "daily_folder", "batch_dir"}])
    write_csv_rows(batch_dir / "no_effect_candidates.csv", no_effect_rows, [k for k in batch_summary_fields if k not in {"config_path", "parent_strategy_config_path", "weekly_file", "daily_folder", "batch_dir"}])
    write_csv_rows(batch_dir / "requires_engine_support.csv", unsupported_rows, [k for k in batch_summary_fields if k not in {"config_path", "parent_strategy_config_path", "weekly_file", "daily_folder", "batch_dir"}])
    write_csv_rows(batch_dir / "comparison_vs_dd20_parents.csv", parent_comparison_rows, list(parent_comparison_rows[0].keys()) if parent_comparison_rows else [
        "run_id", "strategy_id", "family", "parent_run_id", "parent_strategy_id", "candidate_cagr", "candidate_max_drawdown_pct",
        "candidate_years_won_vs_spy", "candidate_months_won_vs_spy", "candidate_trades", "candidate_calmar_ratio", "parent_cagr",
        "parent_max_drawdown_pct", "parent_years_won_vs_spy", "parent_months_won_vs_spy", "parent_trades", "parent_calmar_ratio",
        "cagr_delta_vs_parent", "dd_delta_vs_parent", "years_won_delta_vs_parent", "months_won_delta_vs_parent", "trades_delta_vs_parent",
        "status", "decision_reason", "support_status", "support_issue", "engine_translation_note"
    ])
    write_csv_rows(batch_dir / "comparison_vs_spy_yearly.csv", spy_yearly_rows, ["run_id", "strategy_id", "year", "strategy_return_pct", "spy_return_pct", "diff_pct", "mark"])
    write_csv_rows(batch_dir / "comparison_vs_spy_monthly.csv", spy_monthly_rows, ["run_id", "strategy_id", "year", "month", "period", "strategy_return_pct", "spy_return_pct", "diff_pct", "mark"])

    # Human-readable README.
    executed_count = len(executed_results)
    accepted_count = len(accepted_rows)
    rejected_count = len(rejected_rows)
    no_effect_count = len(no_effect_rows)
    support_count = len(unsupported_rows)
    family_counts = Counter(str(r.get("family", "")) for r in batch_rows)
    rankable_rows = filter_rankable_rows(normalized_batch_rows)
    top_cagr = sorted(
        [r for r in rankable_rows if parse_float(r.get("candidate_max_drawdown_pct")) >= -20.0],
        key=lambda r: parse_float(r.get("candidate_cagr")),
        reverse=True,
    )[:5]
    top_dd = sorted(
        rankable_rows,
        key=lambda r: parse_float(r.get("candidate_max_drawdown_pct")),
        reverse=True,
    )[:5]
    top_years = sorted(
        rankable_rows,
        key=lambda r: parse_int(r.get("candidate_years_won_vs_spy")),
        reverse=True,
    )[:5]

    readme_lines = [
        "# DD20 Controlled Batch",
        "",
        "Batch de evaluación controlada para hipótesis DD20. El runner no tocó current_parent, current_baseline ni backtester.",
        "",
        "## Resumen",
        f"- Configs corridas: {executed_count}",
        f"- Accepted candidates: {accepted_count}",
        f"- Rejected candidates: {rejected_count}",
        f"- No effect: {no_effect_count}",
        f"- Requires engine support: {support_count}",
        "",
        "## Hipótesis por familia",
    ]
    for family, count in sorted(family_counts.items()):
        readme_lines.append(f"- {family}: {count}")
    readme_lines.extend(
        [
            "",
            "## Top 5 por CAGR con DD <= 20%",
        ]
    )
    if top_cagr:
        for row in top_cagr:
            readme_lines.append(
                f"- {row['strategy_id']}: CAGR {parse_float(row.get('candidate_cagr')):.2f}% | DD {parse_float(row.get('candidate_max_drawdown_pct')):.2f}% | status {row.get('status')}"
            )
    else:
        readme_lines.append("- none")
    readme_lines.extend(["", "## Top 5 por menor drawdown"])
    if top_dd:
        for row in top_dd:
            readme_lines.append(
                f"- {row['strategy_id']}: DD {parse_float(row.get('candidate_max_drawdown_pct')):.2f}% | CAGR {parse_float(row.get('candidate_cagr')):.2f}% | status {row.get('status')}"
            )
    else:
        readme_lines.append("- none")
    readme_lines.extend(["", "## Top 5 por años ganados vs SPY"])
    if top_years:
        for row in top_years:
            readme_lines.append(
                f"- {row['strategy_id']}: years won {parse_int(row.get('candidate_years_won_vs_spy'))} | CAGR {parse_float(row.get('candidate_cagr')):.2f}% | status {row.get('status')}"
            )
    else:
        readme_lines.append("- none")

    if batch_invalid_translation_collapse:
        recommendation = "No candidates recommended: batch_invalid_translation_collapse detected."
    elif accepted_rows:
        best = sorted(accepted_rows, key=lambda r: (parse_float(r.get("candidate_cagr")), parse_float(r.get("candidate_max_drawdown_pct"))), reverse=True)[0]
        recommendation = f"Manual review should start with accepted candidate `{best['strategy_id']}`."
    elif no_effect_rows:
        recommendation = (
            f"No accepted candidates yet. Manual review should start with the least-bad supported candidate `{sorted(no_effect_rows, key=lambda r: parse_float(r.get('cagr_delta_vs_parent')), reverse=True)[0]['strategy_id']}` "
            "and with the engine-support blockers."
        )
    elif accepted_count == 0 and rejected_count == 0 and support_count > 0:
        recommendation = "All candidate families need engine support or translation follow-up before meaningful batch evaluation."
    else:
        recommendation = "Manual review should focus on the best supported runner outcomes and whether the unsupported family needs engine support."

    readme_lines.extend(
        [
            "",
            "## Batch Status",
            f"- batch_invalid_translation_collapse: {'true' if batch_invalid_translation_collapse else 'false'}",
            "",
            "## Recommendation",
            recommendation,
            "",
            "## Notes",
            "- `requires_engine_support` is used when a hypothesis depends on a field the current engine does not implement.",
            "- This batch still compares every executed candidate against SPY and against its DD20 parent run.",
            "- If translation collapse is detected, no candidate is recommended regardless of raw metrics.",
            "- No promotion of baseline was performed.",
            "",
        ]
    )

    (batch_dir / "README_DD20_CONTROLLED_BATCH.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    write_json(
        batch_dir / "batch_status.json",
        {
            "batch_invalid_translation_collapse": batch_invalid_translation_collapse,
            "translation_collapse_groups": collapse_groups,
            "configs_queued": len(hypotheses),
            "configs_executed": executed_count,
            "accepted": accepted_count,
            "rejected": rejected_count,
            "no_effect": no_effect_count,
            "requires_engine_support": support_count,
            "dd20_control_not_effective": len(dd20_not_effective_rows),
        },
    )

    # Console summary.
    print(f"Batch folder: {batch_dir}")
    print(f"Configs queued: {len(hypotheses)}")
    print(f"Executed: {executed_count}")
    print(f"Accepted: {accepted_count}")
    print(f"Rejected: {rejected_count}")
    print(f"No effect: {no_effect_count}")
    print(f"DD20 control not effective: {len(dd20_not_effective_rows)}")
    print(f"Requires engine support: {support_count}")
    print(f"batch_invalid_translation_collapse: {'true' if batch_invalid_translation_collapse else 'false'}")
    print()
    print("Top 5 by CAGR with DD <= 20%:")
    if top_cagr:
        for row in top_cagr:
            print(f"- {row['strategy_id']} | CAGR {parse_float(row.get('candidate_cagr')):.2f}% | DD {parse_float(row.get('candidate_max_drawdown_pct')):.2f}%")
    else:
        print("- none")
    print()
    print("Top 5 by smaller drawdown:")
    if top_dd:
        for row in top_dd:
            print(f"- {row['strategy_id']} | DD {parse_float(row.get('candidate_max_drawdown_pct')):.2f}% | CAGR {parse_float(row.get('candidate_cagr')):.2f}%")
    else:
        print("- none")
    print()
    print("Top 5 by years won vs SPY:")
    if top_years:
        for row in top_years:
            print(f"- {row['strategy_id']} | years won {parse_int(row.get('candidate_years_won_vs_spy'))} | CAGR {parse_float(row.get('candidate_cagr')):.2f}%")
    else:
        print("- none")
    print()
    print(f"Recommendation: {recommendation}")

    # Optional detail for resolver warnings.
    if resolver_warnings:
        print("Resolver warnings:")
        for warning in resolver_warnings:
            print(f"- {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
