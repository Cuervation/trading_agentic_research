"""Canonical strategy-effect signatures for pre-run duplicate protection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

METADATA_CONFIG_KEYS = {
    "strategy_id", "strategy_version", "hypothesis_id", "parent_strategy_id",
    "strategy_family", "bibliography_basis", "empirical_basis",
    "changed_parameters", "claim", "causal_mechanism", "expected_effect",
    "falsification_rule", "notes", "generated_at", "created_at",
    "updated_at", "autonomy_reason",
}

BEHAVIOR_KEYS_PREFERRED = {
    "ranking", "ranking_column", "entry_rule", "exit_rule", "market_filter",
    "risk_filters", "risk_management", "position_sizing", "rebalance",
    "rebalance_frequency", "holding_period", "max_positions",
    "benchmark_ticker", "trade_management", "universe_filter",
    "sector_filter", "volatility_filter",
}


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def _strip_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _strip_metadata(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            if str(k) not in METADATA_CONFIG_KEYS
        }
    if isinstance(value, list):
        return [_strip_metadata(v) for v in value]
    return value


def canonical_strategy_payload(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    clean = _strip_metadata(config)
    preferred = {k: clean.get(k) for k in sorted(BEHAVIOR_KEYS_PREFERRED) if k in clean}
    unknown = {k: v for k, v in clean.items() if k not in METADATA_CONFIG_KEYS and k not in preferred}
    payload = dict(preferred)
    for key in sorted(unknown):
        payload[key] = unknown[key]
    return payload


def strategy_effect_signature(config: dict[str, Any]) -> str:
    return stable_hash(canonical_strategy_payload(config))


def strategy_effect_summary(config: dict[str, Any]) -> dict[str, Any]:
    payload = canonical_strategy_payload(config)
    ranking = payload.get("ranking", {}) if isinstance(payload.get("ranking"), dict) else {}
    entry = payload.get("entry_rule", {}) if isinstance(payload.get("entry_rule"), dict) else {}
    exit_rule = payload.get("exit_rule", {}) if isinstance(payload.get("exit_rule"), dict) else {}
    return {
        "signature": strategy_effect_signature(config),
        "ranking_field": ranking.get("field") or payload.get("ranking_column"),
        "ranking_order": ranking.get("order"),
        "top_n": entry.get("top_n"),
        "rank_threshold": exit_rule.get("rank_threshold"),
        "has_market_filter": bool(payload.get("market_filter")),
        "has_risk_filters": bool(payload.get("risk_filters")),
        "payload_keys": sorted(payload.keys()),
    }


def branch_key_from_config(config: dict[str, Any], family: str | None = None) -> str:
    payload = canonical_strategy_payload(config)
    ranking = payload.get("ranking", {}) if isinstance(payload.get("ranking"), dict) else {}
    entry = payload.get("entry_rule", {}) if isinstance(payload.get("entry_rule"), dict) else {}
    exit_rule = payload.get("exit_rule", {}) if isinstance(payload.get("exit_rule"), dict) else {}
    rank_field = str(ranking.get("field") or payload.get("ranking_column") or "unknown_rank")
    if payload.get("market_filter"):
        axis = "market_filter"
    elif payload.get("risk_filters"):
        axis = "rank_confirm"
    elif entry.get("top_n") is not None:
        axis = "rank_topn"
    elif exit_rule.get("rank_threshold") is not None:
        axis = "rank_exit"
    else:
        axis = "rank"
    fam = str(family or config.get("strategy_family") or "unknown_family")
    return f"{fam}/{rank_field}/{axis}"
