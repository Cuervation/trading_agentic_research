"""Helpers to keep current_parent/champion/config-path state synchronized.

Why this exists:
- champion_runs.json tracks best/promotion/secondary runs.
- current_parent.json is what batch generation should use as the parent.
- If these drift, the loop can think it is refining AUTO_002 while generating
  candidate configs from the old baseline config.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHAMPION_FILE = "champion_runs.json"
CURRENT_PARENT_FILE = "current_parent.json"


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
    names = []
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
    """Find the config JSON for a strategy/hypothesis id.

    Resolution order:
    1. strategy_registry row with matching strategy_id and existing config_path.
    2. strategy_registry config whose JSON has matching hypothesis_id.
    3. configs/generated/<hypothesis_id>.json or <strategy_id>.json.
    """
    root = Path(repo_root)
    registry = read_json(root / strategy_registry_path, {}) or {}

    # Direct registry strategy_id match.
    for row in registry.get("strategies", []) or []:
        if strategy_id and str(row.get("strategy_id")) == str(strategy_id) and row.get("config_path"):
            candidate = root / str(row["config_path"])
            if candidate.exists():
                return _norm(candidate.relative_to(root) if candidate.is_absolute() else row["config_path"])

    # Registry entry whose config has matching hypothesis_id.
    if hypothesis_id:
        for row in registry.get("strategies", []) or []:
            config_path = row.get("config_path")
            if not config_path:
                continue
            candidate = root / str(config_path)
            if not candidate.exists():
                continue
            cfg = read_json(candidate, {}) or {}
            if str(cfg.get("hypothesis_id", "")) == str(hypothesis_id):
                return _norm(config_path)

    # Conventional generated paths.
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


def sync_current_parent_state(
    *,
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    prefer_best_champion: bool = True,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    """Synchronize champion_runs.json and current_parent.json.

    By default, the current parent is reset to best_champion_run_id after a full
    rebuild. This is safer for this project because future hypotheses should
    refine the best robust champion, not the first historical promoted run.
    """
    root = Path(repo_root)
    state_path = root / state_dir
    champion_path = state_path / CHAMPION_FILE
    champion = read_json(champion_path, {}) or {}

    best_run_id = champion.get("best_champion_run_id")
    chosen_run_id = best_run_id if prefer_best_champion else (champion.get("current_parent_run_id") or best_run_id)
    snapshot = snapshot_by_run_id(champion, chosen_run_id) or snapshot_by_run_id(champion, best_run_id)

    if snapshot is None:
        # Nothing to sync yet. Keep current_parent.json readable but explicit.
        payload = {
            "current_parent_run_id": None,
            "best_champion_run_id": best_run_id,
            "current_parent_strategy_id": None,
            "current_parent_hypothesis_id": None,
            "current_parent_config_path": None,
            "source": "sync_current_parent_state:no_snapshot",
            "updated_at": now_iso(),
        }
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
    champion["updated_at"] = now_iso()
    write_json(champion_path, champion)

    payload = {
        "current_parent_run_id": snapshot.get("run_id"),
        "current_parent_strategy_id": strategy_id,
        "current_parent_hypothesis_id": hypothesis_id,
        "current_parent_config_path": config_path,
        "best_champion_run_id": champion.get("best_champion_run_id"),
        "baseline_candidate_run_id": champion.get("baseline_candidate_run_id"),
        "aggressive_champion_run_id": champion.get("aggressive_champion_run_id"),
        "source": "sync_current_parent_state",
        "updated_at": now_iso(),
    }
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
    """Return the effective parent config path for generation.

    Explicit CLI value wins. Otherwise use state/current_parent.json, then try to
    resolve by registry, then fallback to the original baseline.
    """
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
