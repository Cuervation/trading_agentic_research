"""Autonomous data-path resolver.

Prevents failures like: FileNotFoundError: .\TU_WEEKLY.csv.
Resolution order:
1) real CLI paths
2) configs/project_config.json data_paths
3) auto-discovery under repo root

Writes state/data_paths_resolved.json for audit.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PLACEHOLDER_TOKENS = ("TU_WEEKLY", "TU_DAILY", "YOUR_WEEKLY", "YOUR_DAILY", "WEEKLY_FILE", "DAILY_FOLDER")


@dataclass
class DataPathResolution:
    weekly_file: str | None
    daily_folder: str | None
    can_run: bool
    source: str
    warnings: list[str]
    errors: list[str]
    candidates: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataPathResolutionError(RuntimeError):
    pass


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


def is_placeholder_path(value: str | Path | None) -> bool:
    if not value:
        return True
    text = str(value).strip().replace("\\", "/").upper()
    return not text or any(tok in text for tok in PLACEHOLDER_TOKENS)


def _resolve(value: str | Path | None, repo_root: str | Path) -> Path | None:
    if not value or is_placeholder_path(value):
        return None
    p = Path(value)
    return p if p.is_absolute() else Path(repo_root) / p


def _skip(path: Path) -> bool:
    blocked = {".git", "__pycache__", ".pytest_cache", "node_modules", "runs", "reports"}
    return bool({part.lower() for part in path.parts}.intersection(blocked))


def _header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            first = sample.splitlines()[0] if sample.splitlines() else ""
            delimiter = ";" if ";" in first else ","
            return [x.strip().lower() for x in next(csv.reader(f, delimiter=delimiter), [])]
    except Exception:
        return []


def _has_required_columns(path: Path) -> bool:
    return {"date", "ticker", "close"}.issubset(set(_header(path)))


def _score_weekly(path: Path) -> int:
    name = path.name.lower()
    score = 0
    if "weekly" in name or "week" in name:
        score += 60
    if "feature" in name or "master" in name:
        score += 25
    if "daily" in name:
        score -= 100
    if _has_required_columns(path):
        score += 40
    try:
        score += min(20, int(path.stat().st_size / 1_000_000))
    except OSError:
        pass
    return score


def _score_daily_dir(path: Path) -> int:
    if not path.is_dir() or _skip(path):
        return -9999
    csvs = [p for p in path.glob("*.csv") if p.is_file()]
    if not csvs:
        return -9999
    name = path.name.lower()
    score = min(50, len(csvs))
    if "daily" in name or "diario" in name:
        score += 60
    if "feature" in name or "store" in name or "data" in name:
        score += 20
    score += 25 * sum(1 for p in csvs[:3] if _has_required_columns(p))
    return score


def discover_weekly_file(repo_root: str | Path) -> tuple[Path | None, list[str]]:
    scored = []
    for p in Path(repo_root).rglob("*.csv"):
        if p.is_file() and not _skip(p):
            score = _score_weekly(p)
            if score > 40:
                scored.append((score, p))
    scored.sort(key=lambda x: (x[0], x[1].stat().st_size if x[1].exists() else 0), reverse=True)
    return (scored[0][1] if scored else None, [str(p) for _, p in scored[:10]])


def discover_daily_folder(repo_root: str | Path) -> tuple[Path | None, list[str]]:
    scored = []
    for p in Path(repo_root).rglob("*"):
        if p.is_dir():
            score = _score_daily_dir(p)
            if score > 40:
                scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return (scored[0][1] if scored else None, [str(p) for _, p in scored[:10]])


def resolve_data_paths(
    *,
    weekly_file: str | None,
    daily_folder: str | None,
    project_config: str | Path = "configs/project_config.json",
    repo_root: str | Path = ".",
    state_dir: str | Path = "state",
    persist: bool = True,
) -> DataPathResolution:
    root = Path(repo_root)
    warnings: list[str] = []
    errors: list[str] = []
    source: list[str] = []
    candidates = {"weekly_files": [], "daily_folders": []}

    cfg = read_json(root / project_config, {}) or {}
    data_paths = cfg.get("data_paths", {}) if isinstance(cfg, dict) else {}

    weekly = _resolve(weekly_file, root)
    daily = _resolve(daily_folder, root)

    if weekly_file and is_placeholder_path(weekly_file):
        warnings.append(f"Ignoring placeholder weekly path: {weekly_file}")
    if daily_folder and is_placeholder_path(daily_folder):
        warnings.append(f"Ignoring placeholder daily folder: {daily_folder}")

    if weekly and weekly.exists():
        source.append("cli_weekly")
    else:
        if weekly_file and weekly and not weekly.exists():
            warnings.append(f"CLI weekly path does not exist: {weekly_file}")
        weekly = _resolve(data_paths.get("weekly_file_path"), root)
        if weekly and weekly.exists():
            source.append("project_config_weekly")
        else:
            weekly, found = discover_weekly_file(root)
            candidates["weekly_files"] = found
            if weekly:
                source.append("auto_weekly")
                warnings.append(f"Auto-discovered weekly feature store: {weekly}")

    if daily and daily.exists() and daily.is_dir():
        source.append("cli_daily")
    else:
        if daily_folder and daily and not daily.exists():
            warnings.append(f"CLI daily folder does not exist: {daily_folder}")
        daily = _resolve(data_paths.get("daily_folder_path"), root)
        if daily and daily.exists() and daily.is_dir():
            source.append("project_config_daily")
        else:
            daily, found = discover_daily_folder(root)
            candidates["daily_folders"] = found
            if daily:
                source.append("auto_daily")
                warnings.append(f"Auto-discovered daily feature folder: {daily}")

    if not weekly or not weekly.exists():
        errors.append("Could not resolve weekly feature-store CSV.")
    if not daily or not daily.exists() or not daily.is_dir():
        errors.append("Could not resolve daily feature-store folder.")

    result = DataPathResolution(
        weekly_file=str(weekly) if weekly else None,
        daily_folder=str(daily) if daily else None,
        can_run=not errors,
        source="+".join(source) if source else "unresolved",
        warnings=warnings,
        errors=errors,
        candidates=candidates,
    )
    if persist:
        write_json(root / state_dir / "data_paths_resolved.json", result.to_dict())
    return result


def ensure_data_paths(**kwargs) -> DataPathResolution:
    result = resolve_data_paths(**kwargs)
    if not result.can_run:
        raise DataPathResolutionError("\n".join(["Data path preflight failed:", *result.errors, *result.warnings]))
    return result
