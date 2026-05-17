"""Autonomous bibliography-driven research vertical slice.

This module is intentionally small and auditable.  It does not replace the
existing backtester; it adds a bibliography -> claim -> hypothesis -> precheck
-> evaluation -> memory -> coordinator path that can run with mocked execution
for fast governance testing.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance import canonical_strategy_payload, changed_parameters_between, stable_json_hash
from scripts.research.executor import build_execution_plan

AXIS_REJECTION_THRESHOLD = 3

SOURCE_FAMILIES = [
    ("SRC_CROSS_SECTIONAL_MOMENTUM_SEED", "Cross-sectional momentum", "Jegadeesh/Titman family", "momentum"),
    ("SRC_TIME_SERIES_MOMENTUM_SEED", "Time-series momentum", "Moskowitz/Ooi/Pedersen family", "trend_following"),
    ("SRC_CAN_SLIM_SEED", "CAN SLIM market direction", "O'Neil CAN SLIM family", "can_slim"),
    ("SRC_FAMA_FRENCH_FACTORS_SEED", "Fama-French factors", "Fama/French family", "value"),
    ("SRC_CARHART_MOMENTUM_SEED", "Carhart momentum factor", "Carhart family", "momentum"),
    ("SRC_QUALITY_INVESTING_SEED", "Quality investing", "Quality/profitability family", "quality"),
    ("SRC_LOW_VOL_BAB_SEED", "Low volatility / betting against beta", "Frazzini/Pedersen family", "low_volatility"),
    ("SRC_SECTOR_MOMENTUM_SEED", "Sector / industry momentum", "Industry momentum family", "sector_momentum"),
    ("SRC_TREND_VOL_TARGET_SEED", "Trend following with volatility targeting", "Trend/volatility family", "regime"),
    ("SRC_ADAPTIVE_MARKETS_REGIME_SEED", "Adaptive markets / regime switching", "Lo adaptive markets family", "regime"),
]

CLAIM_TEMPLATES = {
    "momentum": (
        "Longer-horizon winners should keep outperforming losers after short-term noise is ignored.",
        "Investor underreaction and slow information diffusion can make 24/52 week relative strength persistent.",
        ["ret_26w_pct", "ret_52w_pct"],
        ["ret_52w_pct", "ret_26w_pct"],
        ["exclude_benchmark", "monthly_rebalance"],
        ["momentum_crash", "crowding", "turnover"],
    ),
    "trend_following": (
        "Assets with positive medium-term trend should be favored and weak trends should be cut earlier.",
        "Trend persistence and behavioral anchoring can create continuation across 24/52 week windows.",
        ["close_vs_sma26w_pct", "close_vs_sma52w_pct", "ret_26w_pct"],
        ["ret_26w_pct", "close_vs_sma52w_pct"],
        ["positive_trend", "rank_exit"],
        ["whipsaw", "late_exit"],
    ),
    "can_slim": (
        "Market direction and leadership concentration should matter more than broad diversification.",
        "Leadership baskets can compound when market regime supports risk-on participation.",
        ["ret_52w_pct", "spy_close_vs_sma50_pct"],
        ["ret_52w_pct"],
        ["market_direction", "top_leaders"],
        ["concentration", "market_filter_false_positive"],
    ),
    "value": (
        "Value/factor context can avoid buying expensive momentum names after overextension.",
        "Combining factor discipline with momentum may reduce crash exposure and improve stability.",
        ["ret_52w_pct", "drawdown_from_high_52w_pct"],
        ["ret_52w_pct"],
        ["avoid_extreme_overextension"],
        ["value_trap_proxy", "feature_proxy_noise"],
    ),
    "quality": (
        "Quality leaders with persistent momentum should outperform lower-quality high-momentum names.",
        "Durable profitability/quality proxies can make momentum less fragile across 24/52 week windows.",
        ["ret_52w_pct", "weeks_above_sma26_last13", "volume_ratio_vs_sma13w"],
        ["ret_52w_pct", "weeks_above_sma26_last13"],
        ["quality_proxy", "trend_consistency"],
        ["proxy_quality_not_fundamental", "crowding"],
    ),
    "low_volatility": (
        "Lower volatility momentum can reduce crash sensitivity while preserving participation.",
        "Betting-against-beta and low-vol effects may improve risk-adjusted continuation.",
        ["ret_52w_pct", "volatility_26w_pct", "atr_14_pct"],
        ["ret_52w_pct"],
        ["low_volatility_proxy"],
        ["underparticipation", "defensive_lag"],
    ),
    "sector_momentum": (
        "Industry and sector leadership can persist beyond individual stock noise.",
        "Capital flows often rotate by industry groups, creating cluster persistence.",
        ["ret_26w_pct", "ret_52w_pct"],
        ["ret_26w_pct"],
        ["leadership_persistence"],
        ["missing_sector_field", "overconcentration"],
    ),
    "regime": (
        "Regime-aware trend rules should avoid weak market conditions and reduce drawdown.",
        "Adaptive markets imply strategy edge changes by volatility and trend regime.",
        ["spy_close_vs_sma50_pct", "spy_channel_slope_pct", "volatility_26w_pct"],
        ["ret_52w_pct"],
        ["regime_filter", "volatility_targeting"],
        ["overfiltering", "missed_rebound"],
    ),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def seed_literature_sources(state_dir: str | Path = "state", *, overwrite: bool = False) -> dict:
    path = Path(state_dir) / "literature_sources.json"
    if path.exists() and not overwrite:
        _ensure_initial_state_files(state_dir)
        return read_json(path)
    payload = {
        "version": 1,
        "sources": [
            {
                "source_id": source_id,
                "title": title,
                "author_or_family": author,
                "source_type": "manual_seed",
                "year": None,
                "family": family,
                "status": "pending",
                "notes": "Local seed; replace with real bibliography ingestion later.",
            }
            for source_id, title, author, family in SOURCE_FAMILIES
        ],
    }
    write_json(path, payload)
    _ensure_initial_state_files(state_dir)
    return payload


def _ensure_initial_state_files(state_dir: str | Path) -> None:
    defaults = {
        "extracted_claims.json": {"version": 1, "claims": []},
        "hypothesis_memory.json": {"version": 1, "hypotheses": [], "events": []},
        "axis_cooldowns.json": {"version": 1, "axes": {}, "axis_rejection_threshold": AXIS_REJECTION_THRESHOLD},
        "duplicate_runs.json": {"version": 1, "duplicates": []},
        "champion_runs.json": {"version": 1, "champions": []},
    }
    for name, payload in defaults.items():
        path = Path(state_dir) / name
        if not path.exists():
            write_json(path, payload)
    current_parent = Path(state_dir) / "current_parent.json"
    if not current_parent.exists():
        write_json(current_parent, {"current_parent_run_id": None, "current_parent_strategy_id": None})


def extract_claims_from_sources(state_dir: str | Path = "state") -> dict:
    sources_payload = seed_literature_sources(state_dir)
    claims_path = Path(state_dir) / "extracted_claims.json"
    existing = read_json(claims_path, {"version": 1, "claims": []})
    existing_ids = {c.get("claim_id") for c in existing.get("claims", [])}
    claims = list(existing.get("claims", []))

    for source in sources_payload.get("sources", []):
        if source.get("status") == "exhausted":
            continue
        claim_id = f"CLAIM_{source['source_id']}"
        if claim_id in existing_ids:
            continue
        claim, mechanism, variables, rankings, filters, risks = CLAIM_TEMPLATES.get(source["family"], CLAIM_TEMPLATES["momentum"])
        claims.append(
            {
                "claim_id": claim_id,
                "source_id": source["source_id"],
                "family": source["family"],
                "claim": claim,
                "causal_mechanism": mechanism,
                "suggested_variables": variables,
                "possible_filters": filters,
                "possible_rankings": rankings,
                "expected_risks": risks,
                "falsification_rule": "Reject if artifacts/trades duplicate parent or monthly/yearly SPY comparison does not improve.",
                "status": "available",
                "extracted_at": now_iso(),
            }
        )
        source["status"] = "extracted"

    out = {"version": 1, "claims": claims}
    write_json(claims_path, out)
    write_json(Path(state_dir) / "literature_sources.json", sources_payload)
    return out


def validate_hypothesis(hypothesis: dict) -> None:
    source_ids = hypothesis.get("source_ids") or []
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError("Hypothesis requires at least one source_id.")
    for key in ["claim", "causal_mechanism", "implementation_change", "expected_effect", "falsification_rule"]:
        if not hypothesis.get(key):
            raise ValueError(f"Hypothesis requires {key}.")
    if not hypothesis.get("materiality_guard"):
        raise ValueError("Hypothesis requires duplicate/materiality guard.")


def validate_mixed_hypothesis(hypothesis: dict) -> None:
    validate_hypothesis(hypothesis)
    if len(hypothesis.get("source_ids") or []) < 2:
        raise ValueError("Mixed hypothesis requires at least two source_ids.")
    if not hypothesis.get("mixed_mechanism"):
        raise ValueError("Mixed hypothesis requires mixed_mechanism.")


def build_next_hypothesis(state_dir: str | Path = "state", parent_config: dict | None = None) -> dict | None:
    claims_payload = extract_claims_from_sources(state_dir)
    memory = read_json(Path(state_dir) / "hypothesis_memory.json", {"hypotheses": [], "events": []})
    cooldowns = read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    used_claim_ids = {h.get("claim_id") for h in memory.get("hypotheses", [])}
    available = [
        c
        for c in claims_payload.get("claims", [])
        if c.get("status", "available") == "available"
        and c.get("claim_id") not in used_claim_ids
        and not is_axis_exhausted(cooldowns, c.get("family"), implementation_change_for_claim(c)["axis"])
    ]
    if available:
        hypothesis = hypothesis_from_claim(available[0], parent_config=parent_config)
        validate_hypothesis(hypothesis)
        return hypothesis
    return build_mixed_hypothesis_from_available(claims_payload, memory, cooldowns)


def build_mixed_hypothesis_from_available(claims_payload: dict, memory: dict, cooldowns: dict) -> dict | None:
    used_pairs = {
        tuple(sorted(h.get("source_ids", [])))
        for h in memory.get("hypotheses", [])
        if h.get("hypothesis_type") == "mixed"
    }
    claims = [
        c
        for c in claims_payload.get("claims", [])
        if not is_axis_exhausted(cooldowns, c.get("family"), implementation_change_for_claim(c)["axis"])
    ]
    for left in claims:
        for right in claims:
            if left["source_id"] == right["source_id"]:
                continue
            pair = tuple(sorted([left["source_id"], right["source_id"]]))
            if pair in used_pairs or not mechanisms_can_mix(left, right):
                continue
            hypothesis = mixed_hypothesis_from_claims(left, right)
            validate_mixed_hypothesis(hypothesis)
            return hypothesis
    return None


def mechanisms_can_mix(left: dict, right: dict) -> bool:
    families = {left.get("family"), right.get("family")}
    supported = [
        {"momentum", "can_slim"},
        {"momentum", "quality"},
        {"trend_following", "regime"},
        {"sector_momentum", "regime"},
        {"low_volatility", "momentum"},
    ]
    return any(families == item for item in supported)


def hypothesis_from_claim(claim: dict, parent_config: dict | None = None) -> dict:
    change = implementation_change_for_claim(claim)
    return {
        "hypothesis_id": f"HYP_AUTO_{claim['claim_id'].removeprefix('CLAIM_SRC_')}",
        "hypothesis_type": "single_source",
        "claim_id": claim["claim_id"],
        "source_ids": [claim["source_id"]],
        "bibliography_basis": [{"source_id": claim["source_id"]}],
        "empirical_basis": [],
        "family": claim["family"],
        "axis": change["axis"],
        "claim": claim["claim"],
        "causal_mechanism": claim["causal_mechanism"],
        "implementation_change": change,
        "expected_effect": expected_effect_for_family(claim["family"]),
        "falsification_rule": claim["falsification_rule"],
        "materiality_guard": default_materiality_guard(),
        "status": "candidate",
        "created_at": now_iso(),
    }


def mixed_hypothesis_from_claims(left: dict, right: dict) -> dict:
    families = sorted([left["family"], right["family"]])
    source_ids = sorted([left["source_id"], right["source_id"]])
    return {
        "hypothesis_id": f"HYP_MIX_{families[0].upper()}_{families[1].upper()}_V1",
        "hypothesis_type": "mixed",
        "claim_id": f"MIX_{left['claim_id']}__{right['claim_id']}",
        "source_ids": source_ids,
        "bibliography_basis": [{"source_id": sid} for sid in source_ids],
        "empirical_basis": [],
        "family": "mixed",
        "axis": "+".join(families),
        "claim": f"Combine {left['claim']} WITH {right['claim']}",
        "causal_mechanism": f"{left['causal_mechanism']} Combined with: {right['causal_mechanism']}",
        "mixed_mechanism": "Selection edge plus regime/risk control; this is causal stacking, not random parameter search.",
        "implementation_change": {
            "axis": "+".join(families),
            "strategy_overrides": {"entry_rule": {"top_n": 10}, "market_filter": {"require_positive_trend": True}},
            "features_used": ["ret_52w_pct", "spy_close_vs_sma50_pct"],
        },
        "expected_effect": "Improve 24/52 week stability versus SPY and parent while avoiding duplicate artifacts.",
        "falsification_rule": "Reject if selected universe, trades, or artifacts duplicate parent, or if monthly/yearly SPY comparison does not improve.",
        "materiality_guard": default_materiality_guard(),
        "status": "candidate",
        "created_at": now_iso(),
    }


def implementation_change_for_claim(claim: dict) -> dict:
    family = claim["family"]
    if family in {"momentum", "sector_momentum"}:
        return {
            "axis": "ranking_24_52_momentum",
            "strategy_overrides": {"ranking": {"field": "ret_26w_pct", "order": "desc"}, "entry_rule": {"top_n": 12, "by": "ret_26w_pct"}},
            "features_used": claim.get("suggested_variables", []),
        }
    if family == "trend_following":
        return {
            "axis": "trend_exit",
            "strategy_overrides": {"ranking": {"field": "close_vs_sma52w_pct", "order": "desc"}, "exit_rule": {"rank_threshold": 20}},
            "features_used": claim.get("suggested_variables", []),
        }
    if family == "can_slim":
        return {
            "axis": "market_direction_concentration",
            "strategy_overrides": {"entry_rule": {"top_n": 7}, "market_filter": {"require_positive_trend": True}},
            "features_used": claim.get("suggested_variables", []),
        }
    if family == "quality":
        return {
            "axis": "quality_proxy_ranking",
            "strategy_overrides": {"ranking": {"field": "weeks_above_sma26_last13", "order": "desc"}, "entry_rule": {"top_n": 10, "by": "weeks_above_sma26_last13"}},
            "features_used": claim.get("suggested_variables", []),
        }
    if family == "low_volatility":
        return {
            "axis": "low_volatility_filter",
            "strategy_overrides": {"risk_filters": {"max_volatility_26w_pct": 45}, "entry_rule": {"top_n": 12}},
            "features_used": claim.get("suggested_variables", []),
        }
    if family == "regime":
        return {
            "axis": "regime_filter",
            "strategy_overrides": {"market_filter": {"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False}},
            "features_used": claim.get("suggested_variables", []),
        }
    return {"axis": "generic_material_change", "strategy_overrides": {"entry_rule": {"top_n": 10}}, "features_used": []}


def expected_effect_for_family(family: str) -> str:
    if family in {"momentum", "sector_momentum", "quality"}:
        return "Improve 24/52 week persistence and months beating SPY without duplicate trades."
    if family in {"low_volatility", "regime", "trend_following"}:
        return "Improve drawdown/stability versus parent, accepting lower CAGR only if SPY-relative robustness improves."
    return "Produce a material trade/ranking change with better SPY-relative evidence."


def default_materiality_guard() -> dict:
    return {
        "require_config_hash_change": True,
        "require_signal_or_trade_change_when_data_available": True,
        "reject_duplicate_result": True,
        "reject_metric_no_effect": True,
    }


def precheck_hypothesis(hypothesis: dict, parent_config: dict, state_dir: str | Path = "state") -> dict:
    validate_hypothesis(hypothesis)
    candidate_config = apply_hypothesis_to_config(parent_config, hypothesis)
    changed = changed_parameters_between(parent_config, candidate_config)
    config_hash = stable_json_hash(canonical_strategy_payload(candidate_config))
    parent_hash = stable_json_hash(canonical_strategy_payload(parent_config))
    duplicate_runs = read_json(Path(state_dir) / "duplicate_runs.json", {"duplicates": []})
    duplicate = next((d for d in duplicate_runs.get("duplicates", []) if d.get("config_hash") == config_hash), None)
    if duplicate:
        return _precheck_result(hypothesis, "duplicate_result", False, changed, config_hash, parent_hash, duplicate.get("run_id"))
    if not changed or config_hash == parent_hash:
        return _precheck_result(hypothesis, "metric_no_effect", False, changed, config_hash, parent_hash)
    return _precheck_result(hypothesis, "passed", True, changed, config_hash, parent_hash)


def _precheck_result(hypothesis: dict, status: str, run_backtest: bool, changed: list[str], config_hash: str, parent_hash: str, duplicate_of_run_id: str | None = None) -> dict:
    no_effect = status in {"metric_no_effect", "duplicate_result"}
    return {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "status": status,
        "run_backtest": run_backtest,
        "changed_parameters": changed,
        "config_hash": config_hash,
        "parent_config_hash": parent_hash,
        "signal_hash": None,
        "selected_universe_hash": None,
        "selected_trades_hash": None,
        "features_used": hypothesis.get("implementation_change", {}).get("features_used", []),
        "ranking_logic_changed": any(x.startswith("ranking") for x in changed),
        "duplicate_of_run_id": duplicate_of_run_id,
        "accepted_for_followup": False if no_effect else None,
        "can_move_parent": False if no_effect else None,
        "can_promote_baseline": False,
        "manual_review_required": False,
        "created_at": now_iso(),
    }


def apply_hypothesis_to_config(parent_config: dict, hypothesis: dict) -> dict:
    candidate = deep_merge(parent_config, hypothesis.get("implementation_change", {}).get("strategy_overrides", {}))
    candidate["hypothesis_id"] = hypothesis["hypothesis_id"]
    candidate["strategy_id"] = hypothesis["hypothesis_id"]
    candidate["strategy_family"] = hypothesis.get("family", candidate.get("strategy_family", "mixed"))
    candidate["bibliography_basis"] = [{"source_id": sid} for sid in hypothesis.get("source_ids", [])]
    candidate["claim"] = hypothesis.get("claim")
    candidate["causal_mechanism"] = hypothesis.get("causal_mechanism")
    return candidate


def deep_merge(base: dict, overrides: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def evaluate_result(hypothesis: dict, precheck: dict, *, run_id: str | None = None) -> dict:
    if precheck["status"] in {"metric_no_effect", "duplicate_result"}:
        return rejected_evaluation(hypothesis, precheck, precheck["status"], run_id=run_id)
    seed = int(stable_json_hash(hypothesis)[0:8], 16)
    strategy_cagr = round(8.0 + (seed % 900) / 100.0, 4)
    spy_cagr = 10.0
    drawdown = round(-18.0 - (seed % 1500) / 100.0, 4)
    spy_drawdown = -22.0
    trades = 20 + seed % 80
    months_win = seed % 48
    months_loss = 48 - months_win
    years_win = seed % 6
    years_loss = 6 - years_win
    promoted_candidate = strategy_cagr > spy_cagr and years_win > years_loss and drawdown >= spy_drawdown * 1.35
    accepted = not promoted_candidate and strategy_cagr >= spy_cagr and months_win >= months_loss
    decision = "promoted_candidate" if promoted_candidate else "accepted_for_followup" if accepted else "rejected"
    return {
        "run_id": run_id,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "decision": decision,
        "accepted_for_followup": accepted,
        "promoted_to_baseline_candidate": promoted_candidate,
        "manual_review_required": promoted_candidate,
        "can_move_parent": decision in {"accepted_for_followup", "promoted_candidate"},
        "can_promote_baseline": False,
        "strategy_cagr": strategy_cagr,
        "spy_cagr": spy_cagr,
        "excess_cagr": round(strategy_cagr - spy_cagr, 4),
        "total_return_strategy": round(strategy_cagr * 6, 4),
        "total_return_spy": round(spy_cagr * 6, 4),
        "max_drawdown_strategy": drawdown,
        "max_drawdown_spy": spy_drawdown,
        "trades": trades,
        "trade_wins": trades // 3,
        "trade_ties": trades // 6,
        "trade_losses": trades - trades // 3 - trades // 6,
        "months_beating_spy": months_win,
        "months_losing_to_spy": months_loss,
        "months_tied_spy": 0,
        "years_beating_spy": years_win,
        "years_losing_to_spy": years_loss,
        "years_tied_spy": 0,
        "stability_24_52": "preferred" if hypothesis.get("family") in {"momentum", "quality", "sector_momentum"} else "neutral",
        "deterioration_vs_parent": decision == "rejected",
        "improves_frequency_but_worsens_edge": False,
        "improves_cagr_but_drawdown_too_much": strategy_cagr > spy_cagr and drawdown < spy_drawdown * 1.5,
        "created_at": now_iso(),
    }


def rejected_evaluation(hypothesis: dict, precheck: dict, reason: str, run_id: str | None = None) -> dict:
    return {
        "run_id": run_id,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "decision": "rejected",
        "rejection_reason": reason,
        "accepted_for_followup": False,
        "promoted_to_baseline_candidate": False,
        "manual_review_required": False,
        "can_move_parent": False,
        "can_promote_baseline": False,
        "created_at": now_iso(),
    }


def update_memory(state_dir: str | Path, hypothesis: dict, precheck: dict, evaluation: dict) -> dict:
    memory_path = Path(state_dir) / "hypothesis_memory.json"
    memory = read_json(memory_path, {"version": 1, "hypotheses": [], "events": []})
    if not any(h.get("hypothesis_id") == hypothesis["hypothesis_id"] for h in memory.get("hypotheses", [])):
        memory.setdefault("hypotheses", []).append(hypothesis)
    event = {
        "event_id": f"EVT_{len(memory.get('events', [])) + 1:06d}",
        "hypothesis_id": hypothesis["hypothesis_id"],
        "source_ids": hypothesis.get("source_ids", []),
        "family": hypothesis.get("family"),
        "axis": hypothesis.get("axis"),
        "precheck_status": precheck["status"],
        "decision": evaluation["decision"],
        "duplicate_of_run_id": precheck.get("duplicate_of_run_id"),
        "created_at": now_iso(),
    }
    memory.setdefault("events", []).append(event)
    write_json(memory_path, memory)
    update_axis_cooldowns(state_dir, memory)
    return event


def update_axis_cooldowns(state_dir: str | Path, memory: dict) -> dict:
    path = Path(state_dir) / "axis_cooldowns.json"
    cooldowns = read_json(path, {"version": 1, "axes": {}, "axis_rejection_threshold": AXIS_REJECTION_THRESHOLD})
    threshold = int(cooldowns.get("axis_rejection_threshold", AXIS_REJECTION_THRESHOLD))
    counts: dict[str, int] = {}
    for event in memory.get("events", []):
        if event.get("decision") == "rejected" or event.get("precheck_status") in {"metric_no_effect", "duplicate_result"}:
            key = axis_key(event.get("family"), event.get("axis"))
            counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        if count >= threshold:
            cooldowns.setdefault("axes", {})[key] = {
                "status": "axis_exhausted",
                "rejections": count,
                "reason": "too_many_rejections_or_duplicates",
                "updated_at": now_iso(),
            }
    write_json(path, cooldowns)
    return cooldowns


def coordinator_decision(state_dir: str | Path, hypothesis: dict | None, precheck: dict | None, evaluation: dict | None) -> dict:
    if hypothesis is None:
        return {"decision": "search_new_literature", "reason": "no_available_hypotheses", "continue_loop": True, "manual_review_required": False}
    if precheck and precheck["status"] == "metric_no_effect":
        return {"decision": "reject_metric_no_effect", "reason": "precheck_metric_no_effect", "continue_loop": True, "manual_review_required": False}
    if precheck and precheck["status"] == "duplicate_result":
        return {"decision": "reject_duplicate", "reason": "duplicate_result", "continue_loop": True, "manual_review_required": False}
    if evaluation and evaluation.get("promoted_to_baseline_candidate"):
        return {"decision": "promote_candidate_for_manual_review", "reason": "candidate_passed_evaluation", "continue_loop": True, "manual_review_required": True}
    cooldowns = read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    if is_axis_exhausted(cooldowns, hypothesis.get("family"), hypothesis.get("axis")):
        return {"decision": "abandon_axis", "reason": "axis_exhausted", "continue_loop": True, "manual_review_required": False}
    if evaluation and evaluation.get("decision") == "accepted_for_followup":
        return {"decision": "refine_current_axis", "reason": "accepted_for_followup", "continue_loop": True, "manual_review_required": False}
    return {"decision": "continue_loop", "reason": "rejected_but_loop_continues", "continue_loop": True, "manual_review_required": False}


def is_axis_exhausted(cooldowns: dict, family: str | None, axis: str | None) -> bool:
    return (cooldowns or {}).get("axes", {}).get(axis_key(family, axis), {}).get("status") == "axis_exhausted"


def axis_key(family: str | None, axis: str | None) -> str:
    return f"{family or 'unknown'}:{axis or 'unknown'}"


def load_parent_config(path: str | Path = "configs/baseline_momentum_trend_v1.json") -> dict:
    return read_json(path, {})


def run_iteration(state_dir: str | Path = "state", parent_config_path: str | Path = "configs/baseline_momentum_trend_v1.json") -> dict:
    seed_literature_sources(state_dir)
    extract_claims_from_sources(state_dir)
    parent_config = load_parent_config(parent_config_path)
    hypothesis = build_next_hypothesis(state_dir, parent_config=parent_config)
    if hypothesis is None:
        decision = coordinator_decision(state_dir, None, None, None)
        from scripts.research.literature_searcher import search_new_literature

        literature_search = search_new_literature(state_dir=state_dir)
        write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
        return {"hypothesis": None, "coordinator_decision": decision, "literature_search": literature_search}
    precheck = precheck_hypothesis(hypothesis, parent_config, state_dir=state_dir)
    execution_plan = build_execution_plan(hypothesis["hypothesis_id"], mock=True)
    evaluation = evaluate_result(hypothesis, precheck)
    evaluation["execution_plan"] = execution_plan
    event = update_memory(state_dir, hypothesis, precheck, evaluation)
    decision = coordinator_decision(state_dir, hypothesis, precheck, evaluation)
    write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
    return {"hypothesis": hypothesis, "precheck": precheck, "evaluation": evaluation, "execution_plan": execution_plan, "memory_event": event, "coordinator_decision": decision}


def audit_memory(state_dir: str | Path = "state") -> dict:
    memory = read_json(Path(state_dir) / "hypothesis_memory.json", {"hypotheses": [], "events": []})
    cooldowns = read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    claims = read_json(Path(state_dir) / "extracted_claims.json", {"claims": []})
    return {
        "hypotheses": len(memory.get("hypotheses", [])),
        "events": len(memory.get("events", [])),
        "rejected": sum(1 for e in memory.get("events", []) if e.get("decision") == "rejected"),
        "metric_no_effect": sum(1 for e in memory.get("events", []) if e.get("precheck_status") == "metric_no_effect"),
        "duplicate_result": sum(1 for e in memory.get("events", []) if e.get("precheck_status") == "duplicate_result"),
        "axis_exhausted": sorted(k for k, v in cooldowns.get("axes", {}).items() if v.get("status") == "axis_exhausted"),
        "available_claims": sum(1 for c in claims.get("claims", []) if c.get("status", "available") == "available"),
        "literature_sources": len((read_json(Path(state_dir) / "literature_sources.json", {"sources": []}) or {}).get("sources", [])),
        "literature_search_events": len((read_json(Path(state_dir) / "literature_sources.json", {"search_events": []}) or {}).get("search_events", [])),
    }


def parse_common_args(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--parent-config", default="configs/baseline_momentum_trend_v1.json")
    return parser
