"""Canonical strategy-effect signatures for autonomous research."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any

METADATA_KEYS = {
    "strategy_id","strategy_version","hypothesis_id","parent_strategy_id","parent_hypothesis_id",
    "strategy_family","bibliography_basis","empirical_basis","changed_parameters","claim",
    "causal_mechanism","expected_effect","falsification_rule","notes","generated_at","created_at",
    "updated_at","autonomy_reason","required_spy_comparison","features_required","axis","status",
}
REAL_STRATEGY_KEYS = {
    "ranking","ranking_column","entry_rule","exit_rule","market_filter","risk_filters",
    "risk_management","benchmark_ticker","position_sizing","rebalance","universe_filter","max_positions",
}

def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in sorted(obj.items()) if k not in METADATA_KEYS}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj

def canonical_strategy_effect_payload(strategy_config: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in sorted(REAL_STRATEGY_KEYS):
        if key in strategy_config:
            payload[key] = _normalize(strategy_config[key])
    if "ranking_column" in strategy_config and "ranking" not in payload:
        payload["ranking"] = {"field": strategy_config.get("ranking_column"), "order": "desc"}
    return _normalize(payload)

def stable_json_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def strategy_effect_signature(strategy_config: dict[str, Any]) -> str:
    return stable_json_hash(canonical_strategy_effect_payload(strategy_config))

def strategy_effect_signature_from_path(path: str | Path) -> dict[str, Any]:
    cfg = read_json(path, {}) or {}
    return {
        "strategy_effect_signature": strategy_effect_signature(cfg),
        "canonical_payload": canonical_strategy_effect_payload(cfg),
        "config_hash": sha256_file(path),
        "strategy_id": cfg.get("strategy_id"),
        "hypothesis_id": cfg.get("hypothesis_id") or cfg.get("strategy_id"),
        "strategy_family": cfg.get("strategy_family"),
        "config_path": str(path),
    }
