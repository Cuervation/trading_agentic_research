"""Effective hypothesis filter v3.

Selector-level gate that prevents the autonomous loop from treating
"an unconsumed row in the hypothesis bank" as "valuable executable work".

v3 fixes the diagnostic contradiction where choose_next_hypothesis found no
eligible hypotheses but summarize_effective_hypotheses still reported many
"executable" rows. The summary now applies selector-equivalent filters:
consumed/rejected/accepted/repeat/candidate-review/memory-score/effective gate.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.research.candidate_review_learning import (
    candidate_review_scope_reason,
    is_candidate_review_hypothesis_blocked,
)
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids
from scripts.research.semantic_branch_guard import semantic_branch_preflight
from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate
from scripts.research.strategy_effect_signature import read_json

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


def is_feature_space_family(family: str | None, hypothesis_id: str | None = None) -> bool:
    fam = str(family or "")
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
        fam = str(row.get("family") or "")
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
        fam = str(row.get("family") or "")
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

    if fam.startswith("paper_"):
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
    family = str(hypothesis.get("family") or "")

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


def _selector_equivalent_block_reason(
    *,
    hypothesis: dict[str, Any],
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
    }
