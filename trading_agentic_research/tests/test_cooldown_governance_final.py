from datetime import datetime, timedelta, timezone

from scripts.research.cooldown_governance import hard_active_cooldown_family_names, is_hard_cooldown_active, is_soft_cooldown
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory


def test_legacy_without_until_is_soft_not_hard():
    payload = {"cooldowns": {"paper_time_series_momentum": {"reason": "repeated_failed_hypotheses", "failure_threshold": 3}}}
    assert is_soft_cooldown(payload, "paper_time_series_momentum")
    assert not is_hard_cooldown_active(payload, "paper_time_series_momentum")
    assert "paper_time_series_momentum" not in hard_active_cooldown_family_names(payload)


def test_future_dated_cooldown_is_hard_active():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    payload = {"cooldowns": {"feature_space_regime": {"reason": "manual_guardrail", "cooldown_until": future}}}
    assert is_hard_cooldown_active(payload, "feature_space_regime")
    assert "feature_space_regime" in hard_active_cooldown_family_names(payload)


def test_explicit_soft_with_future_date_does_not_block():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    payload = {"cooldowns": {"paper_quality_momentum": {"mode": "soft", "reason": "advisory", "cooldown_until": future}}}
    assert is_soft_cooldown(payload, "paper_quality_momentum")
    assert not is_hard_cooldown_active(payload, "paper_quality_momentum")


def test_score_allows_soft_cooldown_family():
    payload = {"cooldowns": {"feature_space_composite_confirmation": {"mode": "soft", "reason": "repeated_failed_hypotheses"}}}
    hypothesis = {"hypothesis_id": "HYP_X", "family": "feature_space_composite_confirmation"}
    result = score_hypothesis_against_memory(hypothesis, {}, payload)
    assert result["decision"] == "review"
    assert result["can_generate_candidate"] is True


def test_score_rejects_hard_cooldown_family():
    payload = {"cooldowns": {"feature_space_composite_confirmation": {"mode": "hard", "reason": "manual_guardrail"}}}
    hypothesis = {"hypothesis_id": "HYP_X", "family": "feature_space_composite_confirmation"}
    result = score_hypothesis_against_memory(hypothesis, {}, payload)
    assert result["decision"] == "rejected"
    assert result["can_generate_candidate"] is False
