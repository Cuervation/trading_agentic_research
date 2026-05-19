"""Effective hypothesis filter v4.

Selector-level gate that prevents the autonomous loop from treating
"an unconsumed row in the hypothesis bank" as "valuable executable work".

v4 fixes the remaining diagnostic mismatch:
- choose_next_hypothesis was blocking duplicate override signatures;
- summarize_effective_hypotheses was not;
- ledger rows sometimes have family="", so family stall detection missed
  rejected families such as risk_management unless family could be inferred
  from the hypothesis_id.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.research.autonomous_hypothesis_factory import real_override_signature
from scripts.research.candidate_review_learning import (
    candidate_review_scope_reason,
    is_candidate_review_hypothesis_blocked,
)
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids
from scripts.research.semantic_branch_guard import semantic_branch_preflight
from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate, load_index, rebuild_strategy_effect_index
from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature, canonical_strategy_effect_payload

BAD_VALUES = {
    "duplicate_blocked",
    "duplicate_preflight_blocked",
    "duplicate_strategy_effect_signature",
    "metric_no_effect_blocked",
    "rejected_with_learning",
    "ignored_duplicate",
    "ignored_rejected",
}
GOOD_VALUES = {
    "new_champion",
    "promotion_candidate",
    "secondary_candidate",
    "defensive_secondary_candidate",
    "accepted_for_followup",
}


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _repeat_blocked_hypothesis_ids(history: list[dict[str, Any]], max_repeats_per_hypothesis: int = 1) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def infer_family_from_hypothesis_id(hypothesis_id: str | None) -> str:
    """Infer coarse family when historical rows did not persist family.

    This is intentionally conservative and only maps prefixes used by the
    current hypothesis generators. It improves family-stall diagnostics without
    changing persisted history.
    """
    hid = str(hypothesis_id or "")
    if hid.startswith("HYP_FSPACE_"):
        if "_EXIT_" in hid:
            return "feature_space_composite_exit"
        if "_CONF_" in hid:
            return "feature_space_composite_confirmation"
        if "_MKT_" in hid:
            return "feature_space_composite_market_filter"
        if "_TOPN_" in hid:
            return "feature_space_composite_concentration"
        return "feature_space"
    if hid.startswith("HYP_RISK_MANAGEMENT_"):
        return "risk_management"
    if hid.startswith("HYP_CROSS_SECTIONAL_MOMENTUM_"):
        return "cross_sectional_momentum"
    if hid.startswith("HYP_TACTICAL_ASSET_ALLOCATION_"):
        return "tactical_asset_allocation"
    if hid.startswith("HYP_QUALITY_MOMENTUM_"):
        return "quality_momentum"
    if hid.startswith("HYP_TIME_SERIES_MOMENTUM_") or "TSMOM" in hid:
        return "time_series_momentum"
    if hid.startswith("HYP_CAN_SLIM_"):
        return "can_slim"
    if hid.startswith("HYP_LIT_"):
        m = re.search(r"HYP_LIT_[^_]+_(PAPER_[A-Z0-9_]+?)_", hid)
        if m:
            return m.group(1).lower()
        return "literature"
    if hid.startswith("HYP_REVIEW_"):
        return "candidate_under_review_refinement"
    return ""


def normalize_family(family: str | None, hypothesis_id: str | None = None) -> str:
    fam = str(family or "")
    return fam or infer_family_from_hypothesis_id(str(hypothesis_id or ""))


def is_feature_space_family(family: str | None, hypothesis_id: str | None = None) -> bool:
    fam = normalize_family(family, hypothesis_id)
    hid = str(hypothesis_id or "")
    return fam.startswith("feature_space") or hid.startswith("HYP_FSPACE_")


def _ledger_value(row: dict[str, Any]) -> str:
    return str(row.get("value_delivered") or row.get("champion_action") or row.get("decision") or "")


def _is_good_value(value: str) -> bool:
    return bool(value in GOOD_VALUES or "champion" in value or "candidate" in value)


def _is_bad_value(value: str) -> bool:
    return bool(
        value in BAD_VALUES
        or "duplicate" in value
        or "rejected" in value
        or "blocked" in value
    )


def _family_events(*, state_dir: str | Path, family: str | None = None, feature_space_only: bool = False) -> list[dict[str, Any]]:
    rows = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    blocks = read_jsonl(Path(state_dir) / "pre_run_duplicate_blocks.jsonl")
    out: list[dict[str, Any]] = []

    target_family = str(family or "")

    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        fam = normalize_family(str(row.get("family") or ""), hid)
        if feature_space_only:
            include = is_feature_space_family(fam, hid)
        elif target_family:
            include = fam == target_family
        else:
            include = True
        if include:
            out.append(
                {
                    "source": "ledger",
                    "run_id": row.get("run_id"),
                    "hypothesis_id": hid,
                    "family": fam,
                    "value": _ledger_value(row),
                }
            )

    for row in blocks:
        hid = str(row.get("hypothesis_id") or "")
        fam = normalize_family(str(row.get("family") or ""), hid)
        if feature_space_only:
            include = is_feature_space_family(fam, hid)
        elif target_family:
            include = fam == target_family
        else:
            include = True
        if include:
            out.append(
                {
                    "source": "pre_run_block",
                    "run_id": row.get("run_id"),
                    "hypothesis_id": hid,
                    "family": fam,
                    "value": "duplicate_preflight_blocked",
                    "reason": row.get("reason"),
                }
            )
    return out


def feature_space_stall_status(
    *,
    state_dir: str | Path = "state",
    recent_window: int = 10,
    min_bad: int = 4,
) -> dict[str, Any]:
    events = _family_events(state_dir=state_dir, feature_space_only=True)
    consumed = read_jsonl(Path(state_dir) / "consumed_hypotheses.jsonl")
    consumed_feature_space = sum(
        1
        for row in consumed
        if is_feature_space_family(str(row.get("family") or ""), str(row.get("hypothesis_id") or ""))
    )

    recent = events[-recent_window:]
    bad = sum(1 for ev in recent if _is_bad_value(str(ev.get("value") or "")))
    good = sum(1 for ev in recent if _is_good_value(str(ev.get("value") or "")))
    stalled = bool(len(recent) >= min_bad and bad >= min_bad and good == 0)
    return {
        "stalled": stalled,
        "reason": f"feature_space_recent_bad:{bad}_good:{good}_window:{len(recent)}" if stalled else "feature_space_not_stalled",
        "recent_bad": bad,
        "recent_good": good,
        "recent_count": len(recent),
        "consumed_feature_space": consumed_feature_space,
        "recent_events": recent[-8:],
    }


def family_stall_status(
    *,
    state_dir: str | Path = "state",
    family: str | None,
    recent_window: int = 5,
    min_bad: int = 2,
) -> dict[str, Any]:
    fam = str(family or "")
    if not fam:
        return {"stalled": False, "reason": "missing_family", "family": fam}

    if fam.startswith("paper_") or fam == "literature":
        return {"stalled": False, "reason": "paper_family_advisory", "family": fam}

    events = _family_events(state_dir=state_dir, family=fam)
    recent = events[-recent_window:]
    bad = sum(1 for ev in recent if _is_bad_value(str(ev.get("value") or "")))
    good = sum(1 for ev in recent if _is_good_value(str(ev.get("value") or "")))
    stalled = bool(len(recent) >= min_bad and bad >= min_bad and good == 0)
    return {
        "stalled": stalled,
        "reason": f"family_recent_bad:{bad}_good:{good}_window:{len(recent)}" if stalled else "family_not_stalled",
        "family": fam,
        "recent_bad": bad,
        "recent_good": good,
        "recent_count": len(recent),
        "recent_events": recent[-5:],
    }



# SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5

def _deep_merge_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in (base or {}).items():
        if isinstance(value, dict):
            merged[key] = _deep_merge_dict(value, {})
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value

    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _resolve_parent_config_for_synthetic(
    *,
    state_dir: str | Path,
    repo_root: str | Path,
) -> Path | None:
    root = Path(repo_root)
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = root / state_path

    current_parent = read_json(state_path / "current_parent.json", {}) or {}

    candidates: list[Path] = []
    for value in (
        current_parent.get("current_parent_config_path"),
        "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json",
        "configs/baseline_momentum_trend_v1.json",
    ):
        if not value:
            continue
        p = Path(str(value))
        if not p.is_absolute():
            p = root / p
        candidates.append(p)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate
    return None


def _synthetic_strategy_config_from_hypothesis(
    *,
    hypothesis: dict[str, Any],
    state_dir: str | Path,
    repo_root: str | Path,
) -> dict[str, Any] | None:
    overrides = hypothesis.get("strategy_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return None

    parent_path = _resolve_parent_config_for_synthetic(state_dir=state_dir, repo_root=repo_root)
    if parent_path is None:
        return None

    parent_cfg = read_json(parent_path, {}) or {}
    if not isinstance(parent_cfg, dict) or not parent_cfg:
        return None

    generated = _deep_merge_dict(parent_cfg, overrides)
    generated["parent_strategy_id"] = str(parent_cfg.get("strategy_id"))
    if "strategy_id" not in overrides:
        generated["strategy_id"] = str(hypothesis.get("hypothesis_id"))
    generated.setdefault("strategy_family", parent_cfg.get("strategy_family") or hypothesis.get("family"))
    generated["hypothesis_id"] = str(hypothesis.get("hypothesis_id"))
    generated.setdefault("bibliography_basis", [])
    generated.setdefault("empirical_basis", [])
    return generated


def synthetic_duplicate_status(
    *,
    hypothesis: dict[str, Any],
    state_dir: str | Path,
    runs_dir: str | Path,
    strategy_registry_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    # Check duplicate strategy effect before a config file exists.
    generated = _synthetic_strategy_config_from_hypothesis(
        hypothesis=hypothesis,
        state_dir=state_dir,
        repo_root=repo_root,
    )
    if generated is None:
        return {"checked": False, "synthetic": True, "reason": "synthetic_config_unavailable"}

    sig = strategy_effect_signature(generated)
    index = load_index(state_dir)
    if not index.get("runs"):
        index = rebuild_strategy_effect_index(
            state_dir=state_dir,
            runs_dir=runs_dir,
            strategy_registry_path=strategy_registry_path,
            repo_root=repo_root,
        )

    sig_entry = (index.get("signatures") or {}).get(sig)
    if sig_entry and sig_entry.get("runs"):
        return {
            "checked": True,
            "synthetic": True,
            "blocked": True,
            "reason": "duplicate_strategy_effect_signature_synthetic_config",
            "duplicate_of_run_id": sig_entry.get("first_seen_run_id") or sig_entry.get("runs", [None])[0],
            "existing_runs": sig_entry.get("runs", []),
            "strategy_effect_signature": sig,
            "canonical_payload": canonical_strategy_effect_payload(generated),
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "family": hypothesis.get("family"),
        }

    return {
        "checked": True,
        "synthetic": True,
        "blocked": False,
        "reason": "synthetic_config_unique",
        "strategy_effect_signature": sig,
        "canonical_payload": canonical_strategy_effect_payload(generated),
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "family": hypothesis.get("family"),
    }


def _resolve_config_for_hypothesis(
    *,
    hypothesis: dict[str, Any],
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    repo_root: str | Path = ".",
) -> Path | None:
    root = Path(repo_root)
    hid = str(hypothesis.get("hypothesis_id") or "")
    if not hid:
        return None

    candidates = [
        root / "configs" / "generated" / f"{hid}.json",
        root / "configs" / f"{hid}.json",
    ]

    registry_path = Path(strategy_registry_path)
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    registry = read_json(registry_path, {}) or {}
    for row in registry.get("strategies", []) or []:
        cp = row.get("config_path")
        if not cp:
            continue
        p = Path(cp)
        if not p.is_absolute():
            p = root / p
        if not p.exists():
            continue
        cfg = read_json(p, {}) or {}
        if str(cfg.get("hypothesis_id") or "") == hid:
            candidates.append(p)

    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.exists():
            return p
    return None


def effective_hypothesis_status(
    *,
    hypothesis: dict[str, Any],
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    repo_root: str | Path = ".",
    check_exact_duplicate: bool = True,
    block_feature_space_stall: bool = True,
    block_family_stall: bool = True,
) -> dict[str, Any]:
    hid = str(hypothesis.get("hypothesis_id") or "")
    family = normalize_family(str(hypothesis.get("family") or ""), hid)

    semantic = semantic_branch_preflight(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hid,
        family=family,
    )
    if semantic.get("blocked"):
        return {
            "blocked": True,
            "reason": "semantic_branch_exhausted",
            "detail": semantic.get("reason"),
            "hypothesis_id": hid,
            "family": family,
            "semantic": semantic,
        }

    feature_stall = feature_space_stall_status(state_dir=state_dir)
    if block_feature_space_stall and is_feature_space_family(family, hid) and feature_stall.get("stalled"):
        return {
            "blocked": True,
            "reason": "feature_space_stalled_literature_mode",
            "detail": feature_stall.get("reason"),
            "hypothesis_id": hid,
            "family": family,
            "semantic": semantic,
            "feature_space_stall": feature_stall,
        }

    fam_stall = family_stall_status(state_dir=state_dir, family=family)
    if block_family_stall and not is_feature_space_family(family, hid) and fam_stall.get("stalled"):
        return {
            "blocked": True,
            "reason": "family_stalled_literature_mode",
            "detail": fam_stall.get("reason"),
            "hypothesis_id": hid,
            "family": family,
            "semantic": semantic,
            "family_stall": fam_stall,
            "feature_space_stall": feature_stall,
        }

    exact = {"checked": False}
    if check_exact_duplicate:
        cfg_path = _resolve_config_for_hypothesis(
            hypothesis=hypothesis,
            strategy_registry_path=strategy_registry_path,
            repo_root=repo_root,
        )
        if cfg_path is not None:
            exact = check_pre_run_duplicate(
                strategy_config_path=cfg_path,
                state_dir=state_dir,
                runs_dir=runs_dir,
                strategy_registry_path=strategy_registry_path,
                repo_root=repo_root,
                hypothesis_id=hid,
                family=family,
            )
            exact["checked"] = True
            exact["config_path"] = str(cfg_path)
            if exact.get("blocked"):
                return {
                    "blocked": True,
                    "reason": str(exact.get("reason") or "pre_run_duplicate"),
                    "detail": exact.get("duplicate_of_run_id"),
                    "hypothesis_id": hid,
                    "family": family,
                    "semantic": semantic,
                    "exact_duplicate": exact,
                    "feature_space_stall": feature_stall,
                    "family_stall": fam_stall,
                }
        else:
            exact = {"checked": False, "reason": "config_not_resolved"}

    return {
        "blocked": False,
        "reason": "effective",
        "hypothesis_id": hid,
        "family": family,
        "semantic": semantic,
        "exact_duplicate": exact,
        "feature_space_stall": feature_stall,
        "family_stall": fam_stall,
    }


def _blocked_override_signatures(hypothesis_bank: list[dict[str, Any]], blocked_ids: set[str]) -> set[str]:
    signatures: set[str] = set()
    for row in hypothesis_bank:
        hid = str(row.get("hypothesis_id") or "")
        overrides = row.get("strategy_overrides")
        if hid in blocked_ids and isinstance(overrides, dict) and overrides:
            signatures.add(real_override_signature(overrides))
    return signatures


def _selector_equivalent_block_reason(
    *,
    hypothesis: dict[str, Any],
    hypothesis_bank: list[dict[str, Any]],
    blocked_signatures: set[str],
    signature_block_ids: set[str],
    state_dir: Path,
    rejected_ids: set[str],
    accepted_ids: set[str],
    consumed_ids: set[str],
    repeat_blocked_ids: set[str],
    current_parent_hypothesis_id: str | None,
    learning_memory: dict[str, Any],
    cooldowns: dict[str, Any],
    strategy_registry_path: str | Path,
    runs_dir: str | Path,
    repo_root: str | Path,
) -> str | None:
    status = str(hypothesis.get("status", "candidate"))
    hid = str(hypothesis.get("hypothesis_id") or "")

    if status not in {"candidate", "seeded"}:
        return "non_candidate_status"
    if hid in rejected_ids:
        return "rejected"
    if current_parent_hypothesis_id and hid == current_parent_hypothesis_id:
        return "current_parent_hypothesis"
    if hid in consumed_ids:
        return "consumed"
    if hid in repeat_blocked_ids:
        return "repeat_blocked"
    if hid in accepted_ids:
        return "accepted_already"

    scope_reason = candidate_review_scope_reason(hypothesis, state_dir=state_dir)
    if scope_reason:
        return f"candidate_review_scope:{scope_reason}"
    if is_candidate_review_hypothesis_blocked(hypothesis, state_dir=state_dir):
        return "candidate_review_axis_exhausted"

    overrides = hypothesis.get("strategy_overrides")
    if isinstance(overrides, dict) and overrides and hid not in signature_block_ids:
        if real_override_signature(overrides) in blocked_signatures:
            return "duplicate_override_signature"

    effective = effective_hypothesis_status(
        hypothesis=hypothesis,
        state_dir=state_dir,
        runs_dir=runs_dir,
        strategy_registry_path=strategy_registry_path,
        repo_root=repo_root,
        check_exact_duplicate=False,
        block_feature_space_stall=True,
        block_family_stall=True,
    )
    if effective.get("blocked"):
        return str(effective.get("reason") or "effective_blocked")

    score = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)
    if score.get("decision") == "rejected":
        return "selector_memory_rejected"

    return None


def summarize_effective_hypotheses(
    *,
    hypothesis_bank: list[dict[str, Any]],
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    repo_root: str | Path = ".",
    limit: int = 500,
) -> dict[str, Any]:
    state_path = Path(state_dir)
    learning_memory = read_json(state_path / "learning_memory.json", {}) or {}
    cooldowns = read_json(state_path / "subspace_cooldowns.json", {}) or {}
    current_parent = read_json(state_path / "current_parent.json", {}) or {}
    batch_state = read_json(state_path / "batch_state.json", {}) or {}
    rejected_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "rejected_hypotheses.jsonl") if row.get("hypothesis_id")}
    accepted_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "accepted_hypotheses.jsonl") if row.get("hypothesis_id")}
    consumed_ids = consumed_hypothesis_ids(state_path)
    repeat_blocked_ids = _repeat_blocked_hypothesis_ids(batch_state.get("history", []) or [], 1)
    current_parent_hypothesis_id = str(
        current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id") or ""
    ) or None

    signature_block_ids = set(rejected_ids).union(consumed_ids).union(accepted_ids)
    blocked_signatures = _blocked_override_signatures(hypothesis_bank, signature_block_ids)

    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    executable: list[str] = []

    checked = 0
    for hypothesis in hypothesis_bank:
        if checked >= limit:
            break
        checked += 1
        hid = str(hypothesis.get("hypothesis_id") or "")
        reason = _selector_equivalent_block_reason(
            hypothesis=hypothesis,
            hypothesis_bank=hypothesis_bank,
            blocked_signatures=blocked_signatures,
            signature_block_ids=signature_block_ids,
            state_dir=state_path,
            rejected_ids=rejected_ids,
            accepted_ids=accepted_ids,
            consumed_ids=consumed_ids,
            repeat_blocked_ids=repeat_blocked_ids,
            current_parent_hypothesis_id=current_parent_hypothesis_id,
            learning_memory=learning_memory,
            cooldowns=cooldowns,
            strategy_registry_path=strategy_registry_path,
            runs_dir=runs_dir,
            repo_root=repo_root,
        )
        if reason:
            counts[reason] += 1
            examples.setdefault(reason, []).append(hid)
        else:
            executable.append(hid)

    feature_stall = feature_space_stall_status(state_dir=state_dir)
    blocked_counts = dict(counts)
    if executable:
        mode = "normal"
    elif (
        feature_stall.get("stalled")
        or blocked_counts.get("semantic_branch_exhausted")
        or blocked_counts.get("feature_space_stalled_literature_mode")
        or blocked_counts.get("family_stalled_literature_mode")
        or blocked_counts.get("duplicate_override_signature")
    ):
        mode = "literature_or_new_family"
    else:
        mode = "generate_more_hypotheses"

    return {
        "checked": checked,
        "executable_count": len(executable),
        "executable_sample": executable[:20],
        "blocked_counts": blocked_counts,
        "blocked_examples": {k: v[:10] for k, v in examples.items()},
        "feature_space_stall": feature_stall,
        "recommended_mode": mode,
        "selector_equivalent": True,
        "duplicate_override_signature_count": blocked_counts.get("duplicate_override_signature", 0),
    }
