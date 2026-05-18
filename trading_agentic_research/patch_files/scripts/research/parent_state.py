"""Helpers to keep current_parent/champion/config-path state synchronized.

Manual-parent governance note
-----------------------------
This project separates:
- official current parent: the run future baseline comparisons must use;
- best/new champion: a discovered result that may be better;
- pending parent candidate: a candidate that needs manual review before parent movement.

Therefore sync_current_parent_state() must never silently move current_parent to
best_champion_run_id when state/parent_governance_lock.json requires manual
approval. This prevents autonomous batches from branching from an unapproved
candidate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHAMPION_FILE = "champion_runs.json"
CURRENT_PARENT_FILE = "current_parent.json"
PARENT_LOCK_FILE = "parent_governance_lock.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _norm(path: str | Path) -> str:
    return str(Path(path).as_posix())


def _candidate_paths(
    *,
    strategy_id: str | None,
    hypothesis_id: str | None,
    generated_configs_dir: str | Path = "configs/generated",
) -> list[Path]:
    names: list[str] = []
    for value in (hypothesis_id, strategy_id):
        if value and str(value) not in names:
            names.append(str(value))
    paths: list[Path] = []
    for name in names:
        paths.append(Path(generated_configs_dir) / f"{name}.json")
        paths.append(Path("configs") / f"{name}.json")
    return paths


def resolve_strategy_config_path(
    *,
    strategy_id: str | None,
    hypothesis_id: str | None,
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    repo_root: str | Path = ".",
) -> str | None:
    """Find the config JSON for a strategy/hypothesis id."""
    root = Path(repo_root)
    registry_path = Path(strategy_registry_path)
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    registry = read_json(registry_path, {}) or {}

    for row in registry.get("strategies", []) or []:
        if strategy_id and str(row.get("strategy_id")) == str(strategy_id) and row.get("config_path"):
            candidate = Path(row["config_path"])
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists():
                try:
                    return _norm(candidate.relative_to(root))
                except ValueError:
                    return _norm(candidate)

    if hypothesis_id:
        for row in registry.get("strategies", []) or []:
            config_path = row.get("config_path")
            if not config_path:
                continue
            candidate = Path(config_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            if not candidate.exists():
                continue
            cfg = read_json(candidate, {}) or {}
            if str(cfg.get("hypothesis_id", "")) == str(hypothesis_id):
                try:
                    return _norm(candidate.relative_to(root))
                except ValueError:
                    return _norm(candidate)

    for candidate in _candidate_paths(
        strategy_id=strategy_id,
        hypothesis_id=hypothesis_id,
        generated_configs_dir=root / generated_configs_dir,
    ):
        if candidate.exists():
            try:
                return _norm(candidate.relative_to(root))
            except ValueError:
                return _norm(candidate)
    return None


def snapshot_by_run_id(champion_state: dict[str, Any], run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    buckets = (
        "champion_runs",
        "promotion_candidates",
        "secondary_candidates",
        "defensive_secondary_candidates",
    )
    for bucket in buckets:
        for row in champion_state.get(bucket, []) or []:
            if str(row.get("run_id")) == str(run_id):
                return row
    return None


def _load_parent_lock(state_path: Path) -> dict[str, Any]:
    lock = read_json(state_path / PARENT_LOCK_FILE, {}) or {}
    if lock.get("parent_updates_require_manual_approval") is True:
        return lock
    return {}


def _pending_parent_candidate(champion: dict[str, Any], official_parent: str | None) -> str | None:
    explicit = champion.get("pending_parent_candidate_run_id")
    if explicit and str(explicit) != str(official_parent):
        return str(explicit)
    best = champion.get("best_champion_run_id")
    if best and str(best) != str(official_parent):
        return str(best)
    baseline = champion.get("baseline_candidate_run_id")
    if baseline and str(baseline) != str(official_parent):
        return str(baseline)
    candidates = champion.get("promotion_candidates", []) or []
    for row in candidates:
        rid = row.get("run_id")
        if rid and str(rid) != str(official_parent):
            return str(rid)
    return None


def _payload_from_snapshot(
    *,
    champion: dict[str, Any],
    snapshot: dict[str, Any] | None,
    config_path: str | None,
    source: str,
    pending_parent_candidate_run_id: str | None,
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "current_parent_run_id": None,
            "best_champion_run_id": champion.get("best_champion_run_id"),
            "current_parent_strategy_id": None,
            "current_parent_hypothesis_id": None,
            "current_parent_config_path": None,
            "pending_parent_candidate_run_id": pending_parent_candidate_run_id,
            "source": source,
            "updated_at": now_iso(),
        }
    strategy_id = snapshot.get("strategy_id")
    hypothesis_id = snapshot.get("hypothesis_id") or strategy_id
    return {
        "current_parent_run_id": snapshot.get("run_id"),
        "current_parent_strategy_id": strategy_id,
        "current_parent_hypothesis_id": hypothesis_id,
        "current_parent_config_path": config_path,
        "best_champion_run_id": champion.get("best_champion_run_id"),
        "baseline_candidate_run_id": champion.get("baseline_candidate_run_id"),
        "aggressive_champion_run_id": champion.get("aggressive_champion_run_id"),
        "pending_parent_candidate_run_id": pending_parent_candidate_run_id,
        "parent_updates_require_manual_approval": True,
        "source": source,
        "updated_at": now_iso(),
    }


def sync_current_parent_state(
    *,
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    prefer_best_champion: bool = True,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    """Synchronize champion_runs.json and current_parent.json safely.

    If state/parent_governance_lock.json exists and requires manual approval,
    the official parent from that lock wins even when prefer_best_champion=True.
    New champions remain pending candidates instead of becoming the current
    parent implicitly.
    """
    root = Path(repo_root)
    state_path = root / state_dir
    champion_path = state_path / CHAMPION_FILE
    champion = read_json(champion_path, {}) or {}
    lock = _load_parent_lock(state_path)

    locked_official_parent = lock.get("official_parent_run_id") or champion.get("official_parent_run_id")
    best_run_id = champion.get("best_champion_run_id")

    if locked_official_parent:
        chosen_run_id = str(locked_official_parent)
        source = "sync_current_parent_state:manual_parent_lock"
    else:
        chosen_run_id = best_run_id if prefer_best_champion else (champion.get("current_parent_run_id") or best_run_id)
        source = "sync_current_parent_state"

    pending = _pending_parent_candidate(champion, str(chosen_run_id) if chosen_run_id else None)
    snapshot = snapshot_by_run_id(champion, chosen_run_id) or snapshot_by_run_id(champion, best_run_id)

    if snapshot is None:
        payload = _payload_from_snapshot(
            champion=champion,
            snapshot=None,
            config_path=None,
            source=f"{source}:no_snapshot",
            pending_parent_candidate_run_id=pending,
        )
        write_json(state_path / CURRENT_PARENT_FILE, payload)
        return payload

    strategy_id = snapshot.get("strategy_id")
    hypothesis_id = snapshot.get("hypothesis_id") or strategy_id
    config_path = resolve_strategy_config_path(
        strategy_id=strategy_id,
        hypothesis_id=hypothesis_id,
        strategy_registry_path=strategy_registry_path,
        generated_configs_dir=generated_configs_dir,
        repo_root=root,
    )

    champion["current_parent_run_id"] = snapshot.get("run_id")
    champion["current_parent_strategy_id"] = strategy_id
    champion["current_parent_hypothesis_id"] = hypothesis_id
    champion["current_parent_config_path"] = config_path
    if locked_official_parent:
        champion["official_parent_run_id"] = str(locked_official_parent)
        champion["parent_updates_require_manual_approval"] = True
    champion["pending_parent_candidate_run_id"] = pending
    champion["updated_at"] = now_iso()
    write_json(champion_path, champion)

    payload = _payload_from_snapshot(
        champion=champion,
        snapshot=snapshot,
        config_path=config_path,
        source=source,
        pending_parent_candidate_run_id=pending,
    )
    write_json(state_path / CURRENT_PARENT_FILE, payload)
    return payload


def resolve_current_parent_config_path(
    *,
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    explicit_parent_strategy_config: str | None = None,
    fallback: str = "configs/baseline_momentum_trend_v1.json",
    repo_root: str | Path = ".",
) -> str:
    """Return the official parent config path for generation/comparison."""
    root = Path(repo_root)
    if explicit_parent_strategy_config:
        return str(explicit_parent_strategy_config)

    current = read_json(root / state_dir / CURRENT_PARENT_FILE, {}) or {}
    state_path = current.get("current_parent_config_path")
    if state_path and (root / str(state_path)).exists():
        return str(state_path)

    resolved = resolve_strategy_config_path(
        strategy_id=current.get("current_parent_strategy_id"),
        hypothesis_id=current.get("current_parent_hypothesis_id"),
        strategy_registry_path=strategy_registry_path,
        generated_configs_dir=generated_configs_dir,
        repo_root=root,
    )
    if resolved and (root / resolved).exists():
        return resolved

    return fallback


__all__ = [
    "resolve_strategy_config_path",
    "resolve_current_parent_config_path",
    "sync_current_parent_state",
    "snapshot_by_run_id",
]
