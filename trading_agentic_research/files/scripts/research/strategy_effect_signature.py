"Canonical strategy signatures for autonomous research preflight."
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

METADATA_KEYS = {
    "strategy_id", "strategy_version", "hypothesis_id", "parent_strategy_id",
    "parent_hypothesis_id", "strategy_family", "bibliography_basis",
    "empirical_basis", "changed_parameters", "claim", "causal_mechanism",
    "expected_effect", "falsification_rule", "notes", "generated_at",
    "created_at", "updated_at", "autonomy_reason",
}

BEHAVIOR_KEYS = {
    "ranking", "ranking_column", "entry_rule", "exit_rule", "market_filter",
    "risk_filters", "risk_management", "benchmark_ticker", "max_positions",
    "rebalance", "rebalance_rule", "position_sizing", "portfolio",
    "universe_filter",
}


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in METADATA_KEYS}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    return obj


def canonical_strategy_payload(config: dict[str, Any]) -> dict[str, Any]:
    cleaned = _clean(config or {})
    behavior = {key: cleaned[key] for key in sorted(cleaned) if key in BEHAVIOR_KEYS}
    if "ranking" not in behavior and "ranking_column" in behavior:
        behavior["ranking"] = {"field": behavior.pop("ranking_column"), "order": "desc"}
    return behavior


def strategy_effect_signature(config: dict[str, Any]) -> str:
    return stable_hash(canonical_strategy_payload(config or {}))


def strategy_effect_summary(config: dict[str, Any]) -> dict[str, Any]:
    payload = canonical_strategy_payload(config or {})
    ranking = payload.get("ranking") if isinstance(payload.get("ranking"), dict) else {}
    return {
        "signature": stable_hash(payload),
        "payload": payload,
        "ranking_field": ranking.get("field") or payload.get("ranking_column"),
        "top_n": (payload.get("entry_rule") or {}).get("top_n") if isinstance(payload.get("entry_rule"), dict) else None,
        "exit_rank_threshold": (payload.get("exit_rule") or {}).get("rank_threshold") if isinstance(payload.get("exit_rule"), dict) else None,
        "market_filter": payload.get("market_filter"),
        "risk_filters": payload.get("risk_filters"),
        "risk_management": payload.get("risk_management"),
    }


def classify_strategy_branch(config: dict[str, Any], hypothesis_id: str | None = None) -> str:
    payload = canonical_strategy_payload(config or {})
    ranking = payload.get("ranking") if isinstance(payload.get("ranking"), dict) else {}
    field = str(ranking.get("field") or payload.get("ranking_column") or "unknown")
    hid = str(hypothesis_id or config.get("hypothesis_id") or config.get("strategy_id") or "").upper()

    risk_filters = payload.get("risk_filters") if isinstance(payload.get("risk_filters"), dict) else {}
    entry_rule = payload.get("entry_rule") if isinstance(payload.get("entry_rule"), dict) else {}
    exit_rule = payload.get("exit_rule") if isinstance(payload.get("exit_rule"), dict) else {}
    risk_management = payload.get("risk_management") if isinstance(payload.get("risk_management"), dict) else {}

    if "MKT" in hid or "market_filter" in payload:
        layer = "market_filter"
    elif "CONF" in hid or bool(risk_filters.get("conditions")):
        layer = "confirmation"
    elif "TOPN" in hid or entry_rule.get("top_n") is not None:
        layer = "topn"
    elif "EXIT" in hid or exit_rule.get("rank_threshold") is not None:
        layer = "exit"
    elif risk_management.get("trailing_stop_pct"):
        layer = "risk_management"
    else:
        layer = "ranking"

    return f"feature_space:{field}:{layer}"
