"""Effective hypothesis filter.

Selector-level gate that prevents the autonomous loop from treating
"an unconsumed row in the hypothesis bank" as "valuable executable work".
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

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


def is_feature_space_family(family: str | None, hypothesis_id: str | None = None) -> bool:
    fam = str(family or "")
    hid = str(hypothesis_id or "")
    return fam.startswith("feature_space") or hid.startswith("HYP_FSPACE_")


def _ledger_value(row: dict[str, Any]) -> str:
    return str(row.get("value_delivered") or row.get("champion_action") or row.get("decision") or "")


def feature_space_stall_status(
    *,
    state_dir: str | Path = "state",
    recent_window: int = 10,
    min_bad: int = 4,
) -> dict[str, Any]:
    rows = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    consumed = read_jsonl(Path(state_dir) / "consumed_hypotheses.jsonl")
    blocks = read_jsonl(Path(state_dir) / "pre_run_duplicate_blocks.jsonl")

    events: list[dict[str, Any]] = []
    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        fam = str(row.get("family") or "")
        if is_feature_space_family(fam, hid):
            events.append(
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
        if is_feature_space_family(fam, hid):
            events.append(
                {
                    "source": "pre_run_block",
                    "run_id": row.get("run_id"),
                    "hypothesis_id": hid,
                    "family": fam,
                    "value": "duplicate_preflight_blocked",
                    "reason": row.get("reason"),
                }
            )

    consumed_feature_space = sum(
        1
        for row in consumed
        if is_feature_space_family(str(row.get("family") or ""), str(row.get("hypothesis_id") or ""))
    )

    recent = events[-recent_window:]
    bad = 0
    good = 0
    for ev in recent:
        value = str(ev.get("value") or "")
        if value in GOOD_VALUES or "champion" in value or "candidate" in value:
            good += 1
        if (
            value in BAD_VALUES
            or "duplicate" in value
            or "rejected" in value
            or "blocked" in value
        ):
            bad += 1

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

    stall = feature_space_stall_status(state_dir=state_dir)
    if block_feature_space_stall and is_feature_space_family(family, hid) and stall.get("stalled"):
        return {
            "blocked": True,
            "reason": "feature_space_stalled_literature_mode",
            "detail": stall.get("reason"),
            "hypothesis_id": hid,
            "family": family,
            "semantic": semantic,
            "feature_space_stall": stall,
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
                    "feature_space_stall": stall,
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
        "feature_space_stall": stall,
    }


def summarize_effective_hypotheses(
    *,
    hypothesis_bank: list[dict[str, Any]],
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    repo_root: str | Path = ".",
    limit: int = 200,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    executable: list[str] = []

    checked = 0
    for hypothesis in hypothesis_bank:
        if checked >= limit:
            break
        status = str(hypothesis.get("status", "candidate"))
        if status not in {"candidate", "seeded"}:
            continue
        checked += 1
        result = effective_hypothesis_status(
            hypothesis=hypothesis,
            state_dir=state_dir,
            runs_dir=runs_dir,
            strategy_registry_path=strategy_registry_path,
            repo_root=repo_root,
            check_exact_duplicate=False,
        )
        reason = str(result.get("reason") or "unknown")
        if result.get("blocked"):
            counts[reason] += 1
            examples.setdefault(reason, []).append(str(hypothesis.get("hypothesis_id") or ""))
        else:
            executable.append(str(hypothesis.get("hypothesis_id") or ""))

    stall = feature_space_stall_status(state_dir=state_dir)
    if executable:
        mode = "normal"
    elif stall.get("stalled"):
        mode = "literature_or_new_family"
    elif counts.get("semantic_branch_exhausted") or counts.get("feature_space_stalled_literature_mode"):
        mode = "literature_or_new_family"
    else:
        mode = "generate_more_hypotheses"

    return {
        "checked": checked,
        "executable_count": len(executable),
        "executable_sample": executable[:20],
        "blocked_counts": dict(counts),
        "blocked_examples": {k: v[:10] for k, v in examples.items()},
        "feature_space_stall": stall,
        "recommended_mode": mode,
    }
