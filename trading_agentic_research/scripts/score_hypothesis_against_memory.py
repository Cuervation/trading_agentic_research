"""Score hypotheses against stored learning memory."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.cooldown_governance import cooldown_reason, is_hard_cooldown_active


def metric_no_effect_rejected(metric_deltas: dict, tolerance: float = 0.001, min_trade_delta: float = 1.0) -> dict:
    """Reject candidates whose measured deltas are effectively zero."""
    numeric_fields = ("cagr_delta_pct", "max_drawdown_delta_pct")
    numeric = []
    for key in numeric_fields:
        value = metric_deltas.get(key)
        if isinstance(value, int | float):
            numeric.append(float(value))

    trade_delta = metric_deltas.get("trade_count_delta")
    trade_delta_abs = abs(float(trade_delta)) if isinstance(trade_delta, int | float) else None

    no_effect_numeric = bool(numeric) and all(abs(value) <= tolerance for value in numeric)
    no_effect_trades = trade_delta_abs is None or trade_delta_abs < min_trade_delta
    no_effect = no_effect_numeric and no_effect_trades

    if not no_effect:
        return {"decision": "review", "reason": "metrics_changed", "can_move_parent": False}
    return {
        "decision": "rejected",
        "reason": "metric_no_effect",
        "flags": ["metric_no_effect"],
        "can_move_parent": False,
    }


def is_cooldown_active(cooldowns: dict, family: str, now: datetime | None = None) -> bool:
    """Backward-compatible wrapper: only hard active cooldowns block."""
    return is_hard_cooldown_active(cooldowns, family, now=now)


def score_hypothesis_against_memory(hypothesis: dict, learning_memory: dict, cooldowns: dict | None = None) -> dict:
    """Return a compact score without generating random variants."""
    family = hypothesis.get("family")
    cooldowns = cooldowns or {}
    in_cooldown = is_hard_cooldown_active(cooldowns, family)
    family_summary = learning_memory.get("family_summaries", {}).get(family, {}) if isinstance(learning_memory, dict) else {}

    score = {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "family": family,
        "in_cooldown": in_cooldown,
        "prior_rejections": int(family_summary.get("rejections", 0)),
        "prior_acceptances": int(family_summary.get("acceptances", 0)),
        "can_generate_candidate": not in_cooldown,
        "can_promote_baseline": False,
    }

    if in_cooldown:
        score["decision"] = "rejected"
        score["reason"] = cooldown_reason(cooldowns, family) or "hard_family_cooldown"
        return score

    metric_deltas = hypothesis.get("metric_deltas")
    if isinstance(metric_deltas, dict):
        no_op_result = metric_no_effect_rejected(metric_deltas)
        if no_op_result["decision"] == "rejected":
            score["decision"] = "rejected"
            score["reason"] = no_op_result["reason"]
            score["can_generate_candidate"] = False
            return score

    score["decision"] = "review"
    score["reason"] = "passes_initial_memory_checks"
    return score
