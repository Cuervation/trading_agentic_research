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
        "hypothesis_blocklist.json": {"version": 1, "hypothesis_ids": [], "mixed_pairs": []},
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
        template_claim, template_mechanism, template_variables, template_rankings, template_filters, template_risks = CLAIM_TEMPLATES.get(
            source["family"], CLAIM_TEMPLATES["momentum"]
        )
        claim = source.get("claim") or template_claim
        mechanism = source.get("causal_mechanism") or template_mechanism
        variables = source.get("suggested_variables") or template_variables
        rankings = source.get("possible_rankings") or template_rankings
        filters = source.get("possible_filters") or template_filters
        risks = source.get("expected_risks") or template_risks
        implementation_change = None
        if source.get("strategy_overrides") or source.get("research_axis"):
            implementation_change = {
                "axis": source.get("research_axis") or implementation_change_for_family(source["family"])["axis"],
                "strategy_overrides": source.get("strategy_overrides") or implementation_change_for_family(source["family"])["strategy_overrides"],
                "features_used": source.get("features_used") or variables,
            }
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
                "falsification_rule": source.get("falsification_rule")
                or "Reject if artifacts/trades duplicate parent or monthly/yearly SPY comparison does not improve.",
                **({"implementation_change": implementation_change} if implementation_change else {}),
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
    blocklist = read_json(Path(state_dir) / "hypothesis_blocklist.json", {"version": 1, "hypothesis_ids": [], "mixed_pairs": []})
    used_claim_ids = {h.get("claim_id") for h in memory.get("hypotheses", [])}
    used_claim_ids.update(e.get("claim_id") for e in memory.get("events", []) if e.get("claim_id"))
    used_hypothesis_ids = {e.get("hypothesis_id") for e in memory.get("events", []) if e.get("can_repeat") is False}
    used_hypothesis_ids.update(item.get("hypothesis_id") for item in blocklist.get("hypothesis_ids", []) if item.get("hypothesis_id"))
    available = [
        c
        for c in claims_payload.get("claims", [])
        if c.get("status", "available") == "available"
        and c.get("claim_id") not in used_claim_ids
        and not is_axis_exhausted(cooldowns, c.get("family"), implementation_change_for_claim(c)["axis"])
    ]
    for claim in available:
        hypothesis = hypothesis_from_claim(claim, parent_config=parent_config)
        if hypothesis["hypothesis_id"] in used_hypothesis_ids:
            continue
        validate_hypothesis(hypothesis)
        return hypothesis
    return build_mixed_hypothesis_from_available(claims_payload, memory, cooldowns, state_dir=state_dir)


def build_mixed_hypothesis_from_available(
    claims_payload: dict,
    memory: dict,
    cooldowns: dict,
    *,
    state_dir: str | Path = "state",
) -> dict | None:
    blocklist = read_json(Path(state_dir) / "hypothesis_blocklist.json", {"version": 1, "hypothesis_ids": [], "mixed_pairs": []})
    used_pairs = {
        tuple(sorted(h.get("source_ids", [])))
        for h in memory.get("hypotheses", [])
        if h.get("hypothesis_type") == "mixed"
    }
    used_pairs.update(tuple(sorted(e.get("source_ids", []))) for e in memory.get("events", []) if len(e.get("source_ids", [])) > 1)
    used_hypothesis_ids = {e.get("hypothesis_id") for e in memory.get("events", []) if e.get("can_repeat") is False}
    used_hypothesis_ids.update(item.get("hypothesis_id") for item in blocklist.get("hypothesis_ids", []) if item.get("hypothesis_id"))
    used_pairs.update(
        tuple(sorted(item.get("source_ids", [])))
        for item in blocklist.get("mixed_pairs", [])
        if len(item.get("source_ids", [])) > 1
    )
    claims = [
        c
        for c in claims_payload.get("claims", [])
        if not is_axis_exhausted(cooldowns, c.get("family"), implementation_change_for_claim(c)["axis"])
    ]
    prioritized_pairs = prioritized_mixed_claim_pairs(state_dir, claims_payload, memory, cooldowns)
    for left, right in prioritized_pairs:
        pair = tuple(sorted([left["source_id"], right["source_id"]]))
        if pair in used_pairs:
            continue
        hypothesis = mixed_hypothesis_from_claims(left, right)
        if hypothesis["hypothesis_id"] in used_hypothesis_ids:
            continue
        validate_mixed_hypothesis(hypothesis)
        return hypothesis
    for left in claims:
        for right in claims:
            if left["source_id"] == right["source_id"]:
                continue
            pair = tuple(sorted([left["source_id"], right["source_id"]]))
            if pair in used_pairs or not mechanisms_can_mix(left, right):
                continue
            hypothesis = mixed_hypothesis_from_claims(left, right)
            if hypothesis["hypothesis_id"] in used_hypothesis_ids:
                continue
            validate_mixed_hypothesis(hypothesis)
            return hypothesis
    return None


def prioritized_mixed_claim_pairs(state_dir: str | Path, claims_payload: dict, memory: dict, cooldowns: dict) -> list[tuple[dict, dict]]:
    claims_by_source = {claim.get("source_id"): claim for claim in claims_payload.get("claims", [])}
    champion_state = read_json(Path(state_dir) / "champion_runs.json", {})
    secondary_ids = champion_state.get("secondary_candidates", []) or []
    events_by_run = {event.get("run_id"): event for event in memory.get("events", []) if event.get("run_id")}
    pairs: list[tuple[dict, dict]] = []
    seen: set[tuple[str, str]] = set()

    for left_run_id in secondary_ids:
        left_event = events_by_run.get(left_run_id)
        left_claim = claim_for_event(left_event, claims_by_source, cooldowns)
        if not left_claim:
            continue
        for right_run_id in secondary_ids:
            if right_run_id == left_run_id:
                continue
            right_event = events_by_run.get(right_run_id)
            right_claim = claim_for_event(right_event, claims_by_source, cooldowns)
            if not right_claim or not mechanisms_can_mix(left_claim, right_claim):
                continue
            key = tuple(sorted((left_claim["source_id"], right_claim["source_id"])))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((left_claim, right_claim))

    return sorted(pairs, key=mix_pair_priority, reverse=True)


def claim_for_event(event: dict | None, claims_by_source: dict[str, dict], cooldowns: dict) -> dict | None:
    if not event:
        return None
    source_ids = event.get("source_ids") or []
    if not source_ids:
        return None
    claim = claims_by_source.get(source_ids[0])
    if not claim:
        return None
    axis = implementation_change_for_claim(claim)["axis"]
    if is_axis_exhausted(cooldowns, claim.get("family"), axis):
        return None
    return claim


def mix_pair_priority(pair: tuple[dict, dict]) -> tuple[int, int, int]:
    left, right = pair
    left_change = implementation_change_for_claim(left)
    right_change = implementation_change_for_claim(right)
    left_keys = set((left_change.get("strategy_overrides") or {}).keys())
    right_keys = set((right_change.get("strategy_overrides") or {}).keys())
    structural_gain = len(left_keys.symmetric_difference(right_keys))
    filter_gain = int(bool({"market_filter", "risk_filters"} & (left_keys | right_keys)))
    feature_gain = len(set(left_change.get("features_used") or []).union(right_change.get("features_used") or []))
    return (filter_gain, structural_gain, feature_gain)


def mechanisms_can_mix(left: dict, right: dict) -> bool:
    families = {left.get("family"), right.get("family")}
    supported = [
        {"momentum", "can_slim"},
        {"momentum", "regime"},
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
    left_change = implementation_change_for_claim(left)
    right_change = implementation_change_for_claim(right)
    families = [left["family"], right["family"]]
    source_ids = [left["source_id"], right["source_id"]]
    pair_slug = mixed_pair_slug(left, right)
    merged_overrides = merge_mixed_strategy_overrides(left_change, right_change)
    features = sorted(set((left_change.get("features_used") or []) + (right_change.get("features_used") or [])))
    mixed_axis = f"{left_change['axis']}+{right_change['axis']}"
    return {
        "hypothesis_id": f"HYP_MIX_{pair_slug}_V1",
        "hypothesis_type": "mixed",
        "claim_id": f"MIX_{left['claim_id']}__{right['claim_id']}",
        "source_ids": sorted(source_ids),
        "bibliography_basis": [{"source_id": sid} for sid in source_ids],
        "empirical_basis": [],
        "family": "mixed",
        "axis": mixed_axis,
        "claim": f"Combine {left['claim']} WITH {right['claim']}",
        "causal_mechanism": f"{left['causal_mechanism']} Combined with: {right['causal_mechanism']}",
        "mixed_mechanism": mixed_mechanism_for_claims(left, right, left_change, right_change),
        "implementation_change": {
            "axis": mixed_axis,
            "strategy_overrides": merged_overrides,
            "features_used": features,
        },
        "expected_effect": "Improve 24/52 week stability versus SPY and parent while avoiding duplicate artifacts.",
        "falsification_rule": "Reject if selected universe, trades, or artifacts duplicate parent, or if monthly/yearly SPY comparison does not improve.",
        "materiality_guard": default_materiality_guard(),
        "status": "candidate",
        "created_at": now_iso(),
    }


def implementation_change_for_claim(claim: dict) -> dict:
    if isinstance(claim.get("implementation_change"), dict):
        return claim["implementation_change"]
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


def implementation_change_for_family(family: str) -> dict:
    return implementation_change_for_claim({"family": family, "suggested_variables": []})


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


def precheck_hypothesis(
    hypothesis: dict,
    parent_config: dict,
    state_dir: str | Path = "state",
    weekly_file: str | Path | None = None,
) -> dict:
    validate_hypothesis(hypothesis)
    candidate_config = apply_hypothesis_to_config(parent_config, hypothesis)
    changed = changed_parameters_between(parent_config, candidate_config)
    config_hash = stable_json_hash(canonical_strategy_payload(candidate_config))
    parent_hash = stable_json_hash(canonical_strategy_payload(parent_config))
    duplicate_runs = read_json(Path(state_dir) / "duplicate_runs.json", {"duplicates": []})
    duplicate = next((d for d in duplicate_runs.get("duplicates", []) if d.get("config_hash") == config_hash), None)
    if not duplicate:
        memory = read_json(Path(state_dir) / "hypothesis_memory.json", {"events": []})
        duplicate = next(
            (
                {"run_id": e.get("run_id"), "reason": "hypothesis_already_executed"}
                for e in memory.get("events", [])
                if e.get("hypothesis_id") == hypothesis.get("hypothesis_id") and e.get("can_repeat") is False
            ),
            None,
        )
    if duplicate:
        return _precheck_result(hypothesis, "duplicate_result", False, changed, config_hash, parent_hash, duplicate.get("run_id"))
    if not changed or config_hash == parent_hash:
        return _precheck_result(hypothesis, "metric_no_effect", False, changed, config_hash, parent_hash)

    probe = build_materiality_probe(parent_config, candidate_config, weekly_file=weekly_file)
    if probe.get("available") and probe.get("signal_hash") == probe.get("parent_signal_hash"):
        result = _precheck_result(hypothesis, "low_materiality", False, changed, config_hash, parent_hash)
        result.update(probe)
        return result

    result = _precheck_result(hypothesis, "passed", True, changed, config_hash, parent_hash)
    result.update(probe)
    return result


def build_materiality_probe(parent_config: dict, candidate_config: dict, weekly_file: str | Path | None = None) -> dict:
    if not weekly_file:
        return {"available": False, "reason": "weekly_file_not_provided"}
    try:
        import pandas as pd
        from backtester.signal_builder import build_momentum_trend_signals

        weekly = pd.read_csv(weekly_file, nrows=50000)
        if "date" not in weekly.columns and "signal_date" in weekly.columns:
            weekly = weekly.rename(columns={"signal_date": "date"})
        parent_signals = build_momentum_trend_signals(weekly, parent_config)
        candidate_signals = build_momentum_trend_signals(weekly, candidate_config)
        return {
            "available": True,
            "parent_signal_hash": dataframe_hash(parent_signals),
            "signal_hash": dataframe_hash(candidate_signals),
            "parent_selected_universe_hash": selected_universe_hash(parent_signals),
            "selected_universe_hash": selected_universe_hash(candidate_signals),
            "parent_selected_trades_preview_hash": selected_trades_preview_hash(parent_signals),
            "selected_trades_preview_hash": selected_trades_preview_hash(candidate_signals),
        }
    except Exception as exc:
        return {"available": False, "reason": f"materiality_probe_failed:{exc}"}


def dataframe_hash(df) -> str:
    if df is None or df.empty:
        return stable_json_hash([])
    return stable_json_hash(df.astype(str).to_dict(orient="records"))


def selected_universe_hash(signals) -> str:
    if signals is None or signals.empty or "selected_top_n" not in signals.columns:
        return stable_json_hash([])
    selected = signals.loc[signals["selected_top_n"].astype(bool), ["signal_date", "ticker"]].astype(str)
    return stable_json_hash(selected.to_dict(orient="records"))


def selected_trades_preview_hash(signals) -> str:
    if signals is None or signals.empty:
        return stable_json_hash([])
    cols = [c for c in ["signal_date", "ticker", "rank", "action_candidate"] if c in signals.columns]
    selected = signals.loc[signals.get("selected_top_n", False).astype(bool), cols].astype(str) if "selected_top_n" in signals.columns else signals[cols].astype(str)
    return stable_json_hash(selected.to_dict(orient="records"))


def _precheck_result(hypothesis: dict, status: str, run_backtest: bool, changed: list[str], config_hash: str, parent_hash: str, duplicate_of_run_id: str | None = None) -> dict:
    no_effect = status in {"metric_no_effect", "duplicate_result", "low_materiality"}
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
        "claim_id": hypothesis.get("claim_id"),
        "source_ids": hypothesis.get("source_ids", []),
        "family": hypothesis.get("family"),
        "axis": hypothesis.get("axis"),
        "parent_run_id": evaluation.get("parent_run_id"),
        "precheck_status": precheck["status"],
        "decision": evaluation["decision"],
        "value_delivered": evaluation.get("value_delivered") or value_delivered_for(precheck, evaluation),
        "learned": evaluation.get("learned") or learning_for(precheck, evaluation),
        "next_action": evaluation.get("next_action") or next_action_for(precheck, evaluation),
        "duplicate_of_run_id": evaluation.get("duplicate_of_run_id") or precheck.get("duplicate_of_run_id"),
        "can_repeat": bool(evaluation.get("can_repeat", False)),
        "run_id": evaluation.get("run_id"),
        "execution_mode": evaluation.get("execution_mode", "unknown"),
        "backtest_real": evaluation.get("evaluation_source") == "real_artifacts",
        "promoted_to_baseline_candidate": evaluation.get("promoted_to_baseline_candidate", False),
        "accepted_for_followup": evaluation.get("accepted_for_followup", False),
        "manual_review_required": evaluation.get("manual_review_required", False),
        "created_at": now_iso(),
    }


def mixed_pair_slug(left: dict, right: dict) -> str:
    def token(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.upper())
        return "_".join(part for part in cleaned.split("_") if part)

    left_token = token(left["source_id"].removeprefix("SRC_").removesuffix("_SEED"))
    right_token = token(right["source_id"].removeprefix("SRC_").removesuffix("_SEED"))
    return f"{left_token}__{right_token}"


def merge_mixed_strategy_overrides(left_change: dict, right_change: dict) -> dict:
    left_overrides = deepcopy(left_change.get("strategy_overrides") or {})
    right_overrides = deepcopy(right_change.get("strategy_overrides") or {})
    merged = deep_merge(left_overrides, right_overrides)
    if left_overrides.get("ranking"):
        merged["ranking"] = deepcopy(left_overrides["ranking"])
    if left_overrides.get("entry_rule") or right_overrides.get("entry_rule"):
        merged["entry_rule"] = deep_merge(left_overrides.get("entry_rule", {}), right_overrides.get("entry_rule", {}))
        top_n_values = [
            value
            for value in [left_overrides.get("entry_rule", {}).get("top_n"), right_overrides.get("entry_rule", {}).get("top_n")]
            if isinstance(value, (int, float))
        ]
        if top_n_values:
            merged["entry_rule"]["top_n"] = int(min(top_n_values))
    if left_overrides.get("exit_rule") or right_overrides.get("exit_rule"):
        merged["exit_rule"] = deep_merge(left_overrides.get("exit_rule", {}), right_overrides.get("exit_rule", {}))
        thresholds = [
            value
            for value in [left_overrides.get("exit_rule", {}).get("rank_threshold"), right_overrides.get("exit_rule", {}).get("rank_threshold")]
            if isinstance(value, (int, float))
        ]
        if thresholds:
            merged["exit_rule"]["rank_threshold"] = int(min(thresholds))
    return merged


def mixed_mechanism_for_claims(left: dict, right: dict, left_change: dict, right_change: dict) -> str:
    left_keys = set((left_change.get("strategy_overrides") or {}).keys())
    right_keys = set((right_change.get("strategy_overrides") or {}).keys())
    if "ranking" in left_keys and {"market_filter", "risk_filters"} & right_keys:
        return "Primary selection comes from the first source while the second source adds regime/risk gating to avoid fragile continuation."
    if "ranking" in right_keys and {"market_filter", "risk_filters"} & left_keys:
        return "Primary selection comes from the second source while the first source adds regime/risk gating to avoid fragile continuation."
    return "Stack the first source selection logic with the second source confirmation logic so the mix changes ranking or filters in a materially distinct way."
    memory.setdefault("events", []).append(event)
    write_json(memory_path, memory)
    update_axis_cooldowns(state_dir, memory)
    return event


def record_hypothesis_block(state_dir: str | Path, hypothesis: dict, precheck: dict, evaluation: dict) -> None:
    path = Path(state_dir) / "hypothesis_blocklist.json"
    payload = read_json(path, {"version": 1, "hypothesis_ids": [], "mixed_pairs": []})
    hypothesis_id = hypothesis.get("hypothesis_id")
    if hypothesis_id and not any(item.get("hypothesis_id") == hypothesis_id for item in payload.get("hypothesis_ids", [])):
        payload.setdefault("hypothesis_ids", []).append(
            {
                "hypothesis_id": hypothesis_id,
                "source_ids": hypothesis.get("source_ids", []),
                "axis": hypothesis.get("axis"),
                "decision": evaluation.get("decision"),
                "precheck_status": precheck.get("status"),
                "reason": evaluation.get("reason") or evaluation.get("rejection_reason") or precheck.get("status"),
                "created_at": now_iso(),
            }
        )
    source_ids = sorted(hypothesis.get("source_ids", []))
    if len(source_ids) > 1 and not any(tuple(sorted(item.get("source_ids", []))) == tuple(source_ids) for item in payload.get("mixed_pairs", [])):
        payload.setdefault("mixed_pairs", []).append(
            {
                "source_ids": source_ids,
                "hypothesis_id": hypothesis_id,
                "axis": hypothesis.get("axis"),
                "decision": evaluation.get("decision"),
                "precheck_status": precheck.get("status"),
                "reason": evaluation.get("reason") or evaluation.get("rejection_reason") or precheck.get("status"),
                "created_at": now_iso(),
            }
        )
    write_json(path, payload)


def value_delivered_for(precheck: dict, evaluation: dict) -> str:
    if precheck.get("status") == "duplicate_result" or evaluation.get("decision") == "duplicate_result":
        return "duplicate_blocked"
    if precheck.get("status") in {"metric_no_effect", "low_materiality"}:
        return "rejected_with_learning"
    decision = evaluation.get("champion_decision") or evaluation.get("decision")
    if decision in {"new_champion", "promoted_candidate"}:
        return "new_champion"
    if decision in {"secondary_candidate", "accepted_for_followup"}:
        return "secondary_candidate"
    if decision == "axis_exhausted":
        return "axis_exhausted"
    return "rejected_with_learning"


def learning_for(precheck: dict, evaluation: dict) -> str:
    value = value_delivered_for(precheck, evaluation)
    if value == "duplicate_blocked":
        return f"Duplicate artifacts/config detected against {evaluation.get('duplicate_of_run_id') or precheck.get('duplicate_of_run_id')}; do not repeat this hypothesis."
    if value == "new_champion":
        return "Candidate delivered champion-level SPY-relative value and requires manual review."
    if value == "secondary_candidate":
        return "Candidate improved one research axis but did not safely replace the champion."
    return f"Rejected with evidence: {evaluation.get('rejection_reason') or evaluation.get('reason') or precheck.get('status')}."


def next_action_for(precheck: dict, evaluation: dict) -> str:
    value = value_delivered_for(precheck, evaluation)
    if value == "duplicate_blocked":
        return "change_axis_or_search_new_literature"
    if value == "new_champion":
        return "manual_review_then_refine_adjacent_axis"
    if value == "secondary_candidate":
        return "refine_different_material_change"
    return "search_or_mix_new_literature"


def update_axis_cooldowns(state_dir: str | Path, memory: dict) -> dict:
    path = Path(state_dir) / "axis_cooldowns.json"
    cooldowns = read_json(path, {"version": 1, "axes": {}, "axis_rejection_threshold": AXIS_REJECTION_THRESHOLD})
    threshold = int(cooldowns.get("axis_rejection_threshold", AXIS_REJECTION_THRESHOLD))
    counts: dict[str, dict[str, int]] = {}
    consecutive: dict[str, int] = {}
    for event in memory.get("events", []):
        key = axis_key(event.get("family"), event.get("axis"))
        counts.setdefault(key, {"duplicate_result": 0, "metric_no_effect": 0, "rejected": 0})
        status = event.get("precheck_status")
        decision = event.get("decision")
        if status == "duplicate_result" or decision == "duplicate_result":
            counts[key]["duplicate_result"] += 1
        if status == "metric_no_effect":
            counts[key]["metric_no_effect"] += 1
        if decision == "rejected":
            counts[key]["rejected"] += 1
            consecutive[key] = consecutive.get(key, 0) + 1
        elif event.get("value_delivered") in {"new_champion", "secondary_candidate"}:
            consecutive[key] = 0
    for key, bucket in counts.items():
        if bucket["duplicate_result"] >= threshold or bucket["metric_no_effect"] >= threshold or consecutive.get(key, 0) >= threshold:
            cooldowns.setdefault("axes", {})[key] = {
                "status": "axis_exhausted",
                **bucket,
                "consecutive_rejected": consecutive.get(key, 0),
                "reason": "too_many_duplicate_metric_no_effect_or_rejected",
                "updated_at": now_iso(),
            }
    write_json(path, cooldowns)
    return cooldowns


def coordinator_decision(state_dir: str | Path, hypothesis: dict | None, precheck: dict | None, evaluation: dict | None) -> dict:
    if hypothesis is None:
        return {"decision": "search_new_literature", "reason": "no_available_hypotheses", "continue_loop": True, "manual_review_required": False}
    if precheck and precheck["status"] in {"metric_no_effect", "low_materiality"}:
        return {"decision": "reject_metric_no_effect", "reason": f"precheck_{precheck['status']}", "continue_loop": True, "manual_review_required": False}
    if precheck and precheck["status"] == "duplicate_result":
        return {"decision": "reject_duplicate", "reason": "duplicate_result", "continue_loop": True, "manual_review_required": False}
    if evaluation and evaluation.get("value_delivered") == "new_champion":
        return {"decision": "promote_candidate_for_manual_review", "reason": "candidate_passed_evaluation", "continue_loop": True, "manual_review_required": True}
    if evaluation and evaluation.get("value_delivered") == "secondary_candidate":
        return {"decision": "mix_with_other_source", "reason": "secondary_candidate", "continue_loop": True, "manual_review_required": False}
    if evaluation and evaluation.get("decision") == "rejected" and evaluation.get("reason") == "beats_spy_but_materially_loses_to_best_champion":
        return {"decision": "abandon_axis", "reason": "loses_to_champion_materially", "continue_loop": True, "manual_review_required": False}
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


def resolve_parent_run_id(state_dir: str | Path = "state", runs_dir: str | Path = "runs", requested_parent_run_id: str | None = None) -> str | None:
    if requested_parent_run_id:
        return requested_parent_run_id
    current = read_json(Path(state_dir) / "current_parent.json", {})
    parent = current.get("current_parent_run_id")
    if parent:
        return parent
    champions = read_json(Path(state_dir) / "champion_runs.json", {})
    parent = champions.get("best_champion_run_id")
    if parent:
        write_json(Path(state_dir) / "current_parent.json", {"current_parent_run_id": parent, "source": "best_champion_fallback"})
        return parent
    existing = [p for p in Path(runs_dir).glob("*_*") if p.is_dir() and (p.name.startswith("EXP_") or p.name.startswith("AUTO_"))]
    return None if not existing else None


def run_iteration(
    state_dir: str | Path = "state",
    parent_config_path: str | Path = "configs/baseline_momentum_trend_v1.json",
    *,
    mock: bool = False,
    weekly_file: str | Path | None = None,
    daily_folder: str | Path | None = None,
    project_config: str | Path = "configs/project_config.json",
    runs_dir: str | Path = "runs",
    parent_run_id: str | None = None,
    parent_strategy_config: str | Path | None = None,
    generated_config_dir: str | Path = "configs/generated",
    runner=None,
) -> dict:
    seed_literature_sources(state_dir)
    extract_claims_from_sources(state_dir)
    parent_run_id = resolve_parent_run_id(state_dir, runs_dir, parent_run_id)
    parent_config = load_parent_config(parent_strategy_config or parent_config_path)
    hypothesis = build_next_hypothesis(state_dir, parent_config=parent_config)
    if hypothesis is None:
        decision = coordinator_decision(state_dir, None, None, None)
        from scripts.research.literature_searcher import search_new_literature

        literature_search = search_new_literature(state_dir=state_dir)
        write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
        return {"hypothesis": None, "coordinator_decision": decision, "literature_search": literature_search}

    precheck = precheck_hypothesis(hypothesis, parent_config, state_dir=state_dir, weekly_file=weekly_file)
    execution_plan = build_execution_plan(hypothesis["hypothesis_id"], mock=mock)

    if not precheck.get("run_backtest"):
        evaluation = rejected_evaluation(hypothesis, precheck, precheck["status"])
        evaluation["execution_mode"] = "mock" if mock else "real_precheck_only"
        event = update_memory(state_dir, hypothesis, precheck, evaluation)
        record_hypothesis_block(state_dir, hypothesis, precheck, evaluation)
        decision = coordinator_decision(state_dir, hypothesis, precheck, evaluation)
        write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
        return {"hypothesis": hypothesis, "precheck": precheck, "evaluation": evaluation, "execution_plan": execution_plan, "memory_event": event, "coordinator_decision": decision}

    if mock:
        evaluation = evaluate_result(hypothesis, precheck)
        evaluation["execution_mode"] = "mock"
        evaluation["execution_plan"] = execution_plan
        event = update_memory(state_dir, hypothesis, precheck, evaluation)
        record_hypothesis_block(state_dir, hypothesis, precheck, evaluation)
        decision = coordinator_decision(state_dir, hypothesis, precheck, evaluation)
        write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
        return {"hypothesis": hypothesis, "precheck": precheck, "evaluation": evaluation, "execution_plan": execution_plan, "memory_event": event, "coordinator_decision": decision}

    if not weekly_file or not daily_folder:
        raise ValueError("Real autonomous iteration requires --weekly-file and --daily-folder. Use --mock for tests.")

    from scripts.research.candidate_config_writer import write_candidate_config
    from scripts.research.artifact_index import find_duplicate_artifact, update_artifact_index
    from scripts.research.champion_governance import update_champion_governance
    from scripts.research.real_evaluator import evaluate_completed_run
    from scripts.research.real_executor import run_evaluate_candidate, run_real_backtest_iteration

    config_path = write_candidate_config(parent_config, hypothesis, generated_config_dir)
    run_id = next_research_run_id(runs_dir)
    execution = run_real_backtest_iteration(
        run_id=run_id,
        strategy_config_path=config_path,
        weekly_file=weekly_file,
        daily_folder=daily_folder,
        project_config=project_config,
        runs_dir=runs_dir,
        parent_run_id=parent_run_id,
        parent_strategy_config=parent_strategy_config or parent_config_path,
        runner=runner,
    )
    parent_run_dir = Path(runs_dir) / parent_run_id if parent_run_id else None
    audit_execution = run_evaluate_candidate(
        run_id=run_id,
        runs_dir=runs_dir,
        parent_run_id=parent_run_id,
        hypothesis_id=hypothesis.get("hypothesis_id"),
        family=hypothesis.get("family"),
        state_dir=state_dir,
        runner=runner,
    )
    duplicate = find_duplicate_artifact(execution["run_dir"], state_dir)
    artifact_update = update_artifact_index(execution["run_dir"], state_dir)
    evaluation = evaluate_completed_run(execution["run_dir"], parent_run_dir=parent_run_dir, hypothesis=hypothesis)
    if duplicate:
        evaluation.update(
            {
                "decision": "duplicate_result",
                "accepted_for_followup": False,
                "promoted_to_baseline_candidate": False,
                "manual_review_required": False,
                "can_move_parent": False,
                "can_promote_baseline": False,
                "duplicate_of_run_id": duplicate.get("duplicate_of_run_id"),
                "value_delivered": "duplicate_blocked",
            }
        )
    champion_update = update_champion_governance(execution["run_dir"], state_dir=state_dir, parent_run_id=parent_run_id)
    if not duplicate:
        classification = champion_update["classification"]
        evaluation["champion_decision"] = classification["decision"]
        evaluation["audit_decision"] = evaluation.get("decision")
        evaluation["decision"] = classification["decision"] if classification.get("decision") else evaluation.get("decision")
        evaluation["value_delivered"] = classification["value_delivered"]
        evaluation["can_move_parent"] = bool(evaluation.get("can_move_parent")) and bool(classification["can_move_parent"])
        evaluation["promoted_to_baseline_candidate"] = bool(classification["promoted_to_baseline_candidate"])
        evaluation["manual_review_required"] = bool(classification["manual_review_required"])
        evaluation["reason"] = classification["reason"]
        evaluation["next_action"] = next_action_for(precheck, evaluation)
    evaluation["execution_mode"] = "real"
    evaluation["parent_run_id"] = parent_run_id
    evaluation["candidate_config_path"] = str(config_path)
    event = update_memory(state_dir, hypothesis, precheck, evaluation)
    record_hypothesis_block(state_dir, hypothesis, precheck, evaluation)
    update_duplicate_memory_from_evaluation(state_dir, precheck, evaluation)
    decision = coordinator_decision(state_dir, hypothesis, precheck, evaluation)
    write_json(Path(state_dir) / "last_coordinator_decision.json", decision)
    return {
        "hypothesis": hypothesis,
        "precheck": precheck,
        "execution": {**execution, "audit": audit_execution},
        "evaluation": evaluation,
        "artifact_index": artifact_update,
        "champion_governance": champion_update,
        "execution_plan": execution_plan,
        "memory_event": event,
        "coordinator_decision": decision,
    }


def next_research_run_id(runs_dir: str | Path = "runs", prefix: str = "AUTO") -> str:
    path = Path(runs_dir)
    max_number = 0
    for run_path in path.glob(f"{prefix}_*"):
        suffix = run_path.name.removeprefix(f"{prefix}_")
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return f"{prefix}_{max_number + 1:03d}"


def update_duplicate_memory_from_evaluation(state_dir: str | Path, precheck: dict, evaluation: dict) -> None:
    flags = set(evaluation.get("flags", []) or [])
    artifact_payload = evaluation.get("artifact_hashes", {}) if isinstance(evaluation, dict) else {}
    if "duplicate_artifact" not in flags and not artifact_payload.get("duplicate_artifact") and evaluation.get("decision") != "duplicate_result":
        return
    path = Path(state_dir) / "duplicate_runs.json"
    payload = read_json(path, {"version": 1, "duplicates": []})
    payload.setdefault("duplicates", []).append(
        {
            "run_id": evaluation.get("run_id"),
            "duplicate_of_run_id": evaluation.get("duplicate_of_run_id") or artifact_payload.get("duplicate_run_id"),
            "config_hash": precheck.get("config_hash"),
            "reason": "duplicate_artifact",
            "decision": "duplicate_result",
            "value_delivered": "duplicate_blocked",
            "created_at": now_iso(),
        }
    )
    write_json(path, payload)


def audit_memory(state_dir: str | Path = "state") -> dict:
    memory = read_json(Path(state_dir) / "hypothesis_memory.json", {"hypotheses": [], "events": []})
    cooldowns = read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    claims = read_json(Path(state_dir) / "extracted_claims.json", {"claims": []})
    literature = read_json(Path(state_dir) / "literature_sources.json", {"sources": [], "search_events": []})
    events = memory.get("events", [])
    return {
        "hypotheses": len(memory.get("hypotheses", [])),
        "events": len(events),
        "real_hypotheses_run": sum(1 for e in events if e.get("execution_mode") == "real"),
        "mock_hypotheses_run": sum(1 for e in events if e.get("execution_mode") == "mock"),
        "backtest_real": sum(1 for e in events if e.get("backtest_real")),
        "precheck_rejected": sum(1 for e in events if e.get("precheck_status") in {"metric_no_effect", "duplicate_result", "low_materiality"}),
        "rejected": sum(1 for e in events if e.get("decision") == "rejected"),
        "metric_no_effect": sum(1 for e in events if e.get("precheck_status") == "metric_no_effect"),
        "duplicate_result": sum(1 for e in events if e.get("precheck_status") == "duplicate_result"),
        "axis_exhausted": sorted(k for k, v in cooldowns.get("axes", {}).items() if v.get("status") == "axis_exhausted"),
        "available_claims": sum(1 for c in claims.get("claims", []) if c.get("status", "available") == "available"),
        "literature_sources": len(literature.get("sources", [])),
        "literature_search_events": len(literature.get("search_events", [])),
        "new_bibliography_added": sum(len(e.get("added_source_ids", [])) for e in literature.get("search_events", [])),
        "accepted_for_followup_runs": [e.get("run_id") for e in events if e.get("accepted_for_followup")],
        "promoted_to_baseline_candidate_pending_review": [e.get("run_id") for e in events if e.get("promoted_to_baseline_candidate")],
    }


def parse_common_args(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--parent-config", default="configs/baseline_momentum_trend_v1.json")
    return parser
