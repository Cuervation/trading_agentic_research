from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.research.cooldown_governance import (
    cooldown_entry_status,
    hard_cooldown_families,
    soft_cooldown_families,
)


def test_legacy_cooldown_without_until_is_soft_not_rejected():
    cooldowns = {"cooldowns": {"paper_time_series_momentum": {"reason": "repeated_failed_hypotheses"}}}
    hyp = {"hypothesis_id": "H1", "family": "paper_time_series_momentum"}
    score = score_hypothesis_against_memory(hyp, {"family_summaries": {}}, cooldowns)
    assert score["decision"] == "review"
    assert score["in_soft_cooldown"] is True
    assert score["in_hard_cooldown"] is False


def test_future_dated_cooldown_is_hard_by_default():
    until = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    cooldowns = {"cooldowns": {"feature_space_regime": {"reason": "recent_failures", "cooldown_until": until}}}
    hyp = {"hypothesis_id": "H2", "family": "feature_space_regime"}
    score = score_hypothesis_against_memory(hyp, {"family_summaries": {}}, cooldowns)
    assert score["decision"] == "rejected"
    assert score["in_hard_cooldown"] is True


def test_explicit_hard_without_until_stays_hard():
    cooldowns = {"cooldowns": {"risk_management": {"reason": "manual_block", "severity": "hard"}}}
    assert hard_cooldown_families(cooldowns) == {"risk_management"}
    assert soft_cooldown_families(cooldowns) == set()


def test_status_classification():
    now = datetime.now(timezone.utc)
    assert cooldown_entry_status({"reason": "legacy"}, now=now) == "soft_active"
    assert cooldown_entry_status({"severity": "hard"}, now=now) == "hard_active"
    assert cooldown_entry_status({"severity": "soft"}, now=now) == "soft_active"
    assert cooldown_entry_status({"cooldown_until": (now - timedelta(days=1)).isoformat()}, now=now) == "expired"
    assert cooldown_entry_status({"cooldown_until": (now + timedelta(days=1)).isoformat()}, now=now) == "hard_active"
