"""Governance helpers for autonomous research-loop safety."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_HASH_FILES = ("metrics.json", "trades.csv", "equity_curve.csv")
METADATA_CONFIG_KEYS = {
    "strategy_id",
    "strategy_version",
    "hypothesis_id",
    "parent_strategy_id",
    "strategy_family",
    "bibliography_basis",
    "empirical_basis",
    "changed_parameters",
    "claim",
    "causal_mechanism",
    "expected_effect",
    "falsification_rule",
    "notes",
    "generated_at",
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_json_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def artifact_hashes(run_dir: str | Path) -> dict[str, str]:
    path = Path(run_dir)
    return {name: sha256_file(path / name) for name in ARTIFACT_HASH_FILES if (path / name).exists()}


def artifacts_are_duplicate(left: dict[str, str], right: dict[str, str]) -> bool:
    return bool(left) and all(left.get(name) == right.get(name) for name in ARTIFACT_HASH_FILES)


def canonical_strategy_payload(config: dict) -> dict:
    return {k: v for k, v in config.items() if k not in METADATA_CONFIG_KEYS}


def changed_parameters_between(parent_config: dict, candidate_config: dict) -> list[str]:
    changes: list[str] = []
    _collect_changes(canonical_strategy_payload(parent_config), canonical_strategy_payload(candidate_config), (), changes)
    return changes


def has_real_strategy_change(parent_config: dict | None, candidate_config: dict) -> bool:
    if not parent_config:
        declared = candidate_config.get("changed_parameters")
        if isinstance(declared, list) and declared:
            return True
        return bool(canonical_strategy_payload(candidate_config))
    return bool(changed_parameters_between(parent_config, candidate_config))


def build_run_manifest(
    *,
    run_id: str,
    parent_run_id: str | None,
    strategy_config: dict,
    strategy_config_path: str | Path,
    project_config: dict,
    weekly_file: str | Path,
    daily_folder: str | Path,
    parent_strategy_config: dict | None = None,
) -> dict:
    changed_parameters = strategy_config.get("changed_parameters")
    if not isinstance(changed_parameters, list):
        changed_parameters = changed_parameters_between(parent_strategy_config, strategy_config) if parent_strategy_config else []

    return {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "strategy_id": str(strategy_config.get("strategy_id", "unknown_strategy")),
        "strategy_version": str(strategy_config.get("strategy_version", "1")),
        "strategy_config_path": str(strategy_config_path),
        "parent_strategy_id": strategy_config.get("parent_strategy_id"),
        "hypothesis_id": str(strategy_config.get("hypothesis_id", strategy_config.get("strategy_id", "unknown_hypothesis"))),
        "hypothesis_family": str(strategy_config.get("strategy_family", "unknown_family")),
        "bibliography_basis": strategy_config.get("bibliography_basis", []),
        "empirical_basis": strategy_config.get("empirical_basis", []),
        "changed_parameters": changed_parameters,
        "config_hash": sha256_file(strategy_config_path),
        "code_hash": hash_paths(["backtester", "scripts"]),
        "data_hash": hash_data_inputs(weekly_file=weekly_file, daily_folder=daily_folder),
        "initial_capital": float(project_config.get("initial_capital", 100000)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def hash_paths(paths: list[str | Path]) -> str:
    entries: list[dict] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        files = [path] if path.is_file() else sorted(p for p in path.rglob("*.py") if p.is_file())
        for f in files:
            entries.append({"path": f.as_posix(), "sha256": sha256_file(f)})
    return stable_json_hash(entries)


def hash_data_inputs(*, weekly_file: str | Path, daily_folder: str | Path) -> str:
    entries: list[dict] = []
    weekly = Path(weekly_file)
    if weekly.exists():
        entries.append(_file_fingerprint(weekly))
    folder = Path(daily_folder)
    if folder.exists():
        for f in sorted(folder.glob("*.csv")):
            entries.append(_file_fingerprint(f))
    return stable_json_hash(entries)


def _file_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": path.as_posix(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _collect_changes(left: Any, right: Any, prefix: tuple[str, ...], out: list[str]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            _collect_changes(left.get(key), right.get(key), prefix + (str(key),), out)
        return
    if left != right:
        out.append(".".join(prefix))
