"""Canonical strategy-effect signatures for autonomous research.

The goal is to identify strategy configs that are materially the same even when
metadata differs (strategy_id, hypothesis_id, claims, bibliography, etc.).  This
is intentionally stricter than a raw config hash and looser than artifact hashes:
it catches many duplicate/no-effect candidates before the expensive backtest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


METADATA_KEYS = {
    "strategy_id",
    "strategy_version",
    "hypothesis_id",
    "parent_strategy_id",
    "strategy_family",
    "family",
    "bibliography_basis",
    "empirical_basis",
    "changed_parameters",
    "claim",
    "causal_mechanism",
    "expected_effect",
    "falsification_rule",
    "notes",
    "generated_at",
    "created_at",
    "updated_at",
    "autonomy_reason",
}

FUTURE_REAL_KNOBS = (
    "position_sizing",
    "rebalance",
    "execution",
    "constraints",
    "sector_filters",
    "volatility_targeting",
    "regime_switching",
    "portfolio_filters",
)


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


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in sorted(value.items()) if k not in METADATA_KEYS and v is not None}
    if isinstance(value, list):
        cleaned = [_clean(v) for v in value if v is not None]
        # Lists of scalar fields/conditions should be order-insensitive where possible.
        try:
            return sorted(cleaned, key=lambda x: stable_json(x))
        except TypeError:
            return cleaned
    return value


def _ranking_payload(config: dict[str, Any]) -> dict[str, Any]:
    ranking = config.get("ranking", {}) if isinstance(config.get("ranking"), dict) else {}
    field = config.get("ranking_column") or ranking.get("field") or "ret_52w_pct"
    order = str(ranking.get("order") or "desc").lower()
    if order in {"descending"}:
        order = "desc"
    if order in {"ascending"}:
        order = "asc"
    return {"field": str(field), "order": order}


def _entry_payload(config: dict[str, Any]) -> dict[str, Any]:
    entry = config.get("entry_rule", {}) if isinstance(config.get("entry_rule"), dict) else {}
    out: dict[str, Any] = {"top_n": int(entry.get("top_n", 15) or 15)}
    for k, v in sorted(entry.items()):
        if k != "top_n" and v is not None:
            out[str(k)] = _clean(v)
    return out


def _exit_payload(config: dict[str, Any]) -> dict[str, Any]:
    exit_rule = config.get("exit_rule", {}) if isinstance(config.get("exit_rule"), dict) else {}
    out: dict[str, Any] = {"rank_threshold": int(exit_rule.get("rank_threshold", 30) or 30)}
    for k, v in sorted(exit_rule.items()):
        if k != "rank_threshold" and v is not None:
            out[str(k)] = _clean(v)
    return out


def _market_filter_payload(config: dict[str, Any]) -> dict[str, Any]:
    market = config.get("market_filter", {}) if isinstance(config.get("market_filter"), dict) else {}
    out = {
        "require_positive_trend": bool(market.get("require_positive_trend", True)),
        "fallback_allow_if_missing_spy_metric": bool(market.get("fallback_allow_if_missing_spy_metric", True)),
    }
    for k, v in sorted(market.items()):
        if k not in out and v is not None:
            out[str(k)] = _clean(v)
    return out


def canonical_strategy_effect(config: dict[str, Any]) -> dict[str, Any]:
    """Return only the real knobs that should affect backtest behavior."""
    config = config or {}
    payload: dict[str, Any] = {
        "benchmark_ticker": str(config.get("benchmark_ticker") or "SPY"),
        "ranking": _ranking_payload(config),
        "entry_rule": _entry_payload(config),
        "exit_rule": _exit_payload(config),
        "market_filter": _market_filter_payload(config),
    }

    risk_filters = config.get("risk_filters")
    if isinstance(risk_filters, dict) and risk_filters:
        payload["risk_filters"] = _clean(risk_filters)

    risk_management = config.get("risk_management")
    if isinstance(risk_management, dict) and risk_management:
        payload["risk_management"] = _clean(risk_management)

    for key in FUTURE_REAL_KNOBS:
        value = config.get(key)
        if isinstance(value, dict) and value:
            payload[key] = _clean(value)
        elif value not in (None, "", [], {}):
            payload[key] = _clean(value)

    return payload


def strategy_effect_signature(config: dict[str, Any]) -> str:
    return stable_hash(canonical_strategy_effect(config))


def strategy_effect_signature_from_path(path: str | Path) -> dict[str, Any]:
    cfg = read_json(path, {}) or {}
    canonical = canonical_strategy_effect(cfg)
    return {
        "config_path": str(path),
        "strategy_id": cfg.get("strategy_id"),
        "hypothesis_id": cfg.get("hypothesis_id") or cfg.get("strategy_id"),
        "family": cfg.get("strategy_family"),
        "strategy_effect_signature": stable_hash(canonical),
        "canonical_effect": canonical,
    }


__all__ = [
    "canonical_strategy_effect",
    "strategy_effect_signature",
    "strategy_effect_signature_from_path",
    "stable_hash",
    "stable_json",
    "read_json",
]
