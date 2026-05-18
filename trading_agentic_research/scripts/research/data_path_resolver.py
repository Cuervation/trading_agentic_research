"""Autonomous data-path resolver.

Prevents failures like: FileNotFoundError: .\\TU_WEEKLY.csv.
Resolution order:
1) real CLI paths
2) environment variables TRADING_WEEKLY_FILE / TRADING_DAILY_FOLDER
3) configs/local_data_paths.json (gitignored/local recommended)
4) configs/project_config.json data_paths
5) auto-discovery under repo root

Writes state/data_paths_resolved.json for audit.

Data contract note:
The backtester loader normalizes `signal_date` to `date`, so the resolver must
accept both. It also accepts common safe aliases for date/ticker/close to avoid
blocking valid feature stores before the loader/adapter can normalize them.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PLACEHOLDER_TOKENS = (
    "TU_WEEKLY",
    "TU_DAILY",
    "YOUR_WEEKLY",
    "YOUR_DAILY",
    "WEEKLY_FILE",
    "DAILY_FOLDER",
    "PATH_TO_WEEKLY",
    "PATH_TO_DAILY",
)

# Canonical contract required downstream by run_backtest.py/data_loader.py.
# The loader already handles signal_date -> date; the resolver should not reject
# files that are valid after that deterministic normalization.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "signal_date", "fecha", "datetime", "timestamp"),
    "ticker": ("ticker", "symbol", "asset", "instrument"),
    "close": ("close", "adj_close", "adj close", "close_price", "cierre"),
}
REQUIRED_CANONICAL_COLUMNS = ("date", "ticker", "close")


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
    blocked = {".git", "__pycache__", ".pytest_cache", "node_modules", "runs", "reports", ".venv", "venv"}
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


def _canonical_presence(header: list[str]) -> dict[str, str | None]:
    columns = {c.strip().lower(): c.strip() for c in header}
    presence: dict[str, str | None] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        match = None
        for alias in aliases:
            if alias.lower() in columns:
                match = columns[alias.lower()]
                break
        presence[canonical] = match
    return presence


def _missing_required_columns(path: Path) -> list[str]:
    presence = _canonical_presence(_header(path))
    return [canonical for canonical in REQUIRED_CANONICAL_COLUMNS if not presence.get(canonical)]


def _has_required_columns(path: Path) -> bool:
    return not _missing_required_columns(path)


def _score_weekly(path: Path) -> int:
    name = path.name.lower()
    score = 0
    if "weekly" in name or "week" in name or "semanal" in name:
        score += 60
    if "feature" in name or "master" in name or "store" in name:
        score += 25
    if "daily" in name or "diario" in name:
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
    # Daily masters may live in the repo root as sp500_feature_store_daily_master_*.csv.
    score += 30 * sum(1 for p in csvs[:10] if "daily_master" in p.name.lower())
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
    # Also score repo root itself, because daily master CSVs may be stored there.
    root = Path(repo_root)
    root_score = _score_daily_dir(root)
    if root_score > 40:
        scored.append((root_score, root))
    scored.sort(key=lambda x: x[0], reverse=True)
    return (scored[0][1] if scored else None, [str(p) for _, p in scored[:10]])


def _warn_placeholder(label: str, value: str | None, warnings: list[str]) -> None:
    if value and is_placeholder_path(value):
        warnings.append(f"Ignoring placeholder {label}: {value}")


def _try_source(
    *,
    value: str | None,
    root: Path,
    label: str,
    expected_dir: bool,
    warnings: list[str],
) -> Path | None:
    _warn_placeholder(label, value, warnings)
    p = _resolve(value, root)
    if not p:
        return None
    if expected_dir:
        if p.exists() and p.is_dir():
            return p
        warnings.append(f"{label} path does not exist or is not a directory: {value}")
        return None
    if p.exists() and p.is_file():
        return p
    warnings.append(f"{label} path does not exist or is not a file: {value}")
    return None


def resolve_data_paths(
    *,
    weekly_file: str | None,
    daily_folder: str | None,
    project_config: str | Path = "configs/project_config.json",
    local_data_paths: str | Path = "configs/local_data_paths.json",
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
    local_cfg = read_json(root / local_data_paths, {}) or {}
    local_paths = local_cfg.get("data_paths", local_cfg) if isinstance(local_cfg, dict) else {}

    weekly = _try_source(value=weekly_file, root=root, label="CLI weekly", expected_dir=False, warnings=warnings)
    if weekly:
        source.append("cli_weekly")
    if not weekly:
        weekly = _try_source(value=os.getenv("TRADING_WEEKLY_FILE"), root=root, label="env TRADING_WEEKLY_FILE", expected_dir=False, warnings=warnings)
        if weekly:
            source.append("env_weekly")
    if not weekly:
        weekly = _try_source(value=local_paths.get("weekly_file_path"), root=root, label="local_data_paths weekly", expected_dir=False, warnings=warnings)
        if weekly:
            source.append("local_config_weekly")
    if not weekly:
        weekly = _try_source(value=data_paths.get("weekly_file_path"), root=root, label="project_config weekly", expected_dir=False, warnings=warnings)
        if weekly:
            source.append("project_config_weekly")
    if not weekly:
        weekly, found = discover_weekly_file(root)
        candidates["weekly_files"] = found
        if weekly:
            source.append("auto_weekly")
            warnings.append(f"Auto-discovered weekly feature store: {weekly}")

    daily = _try_source(value=daily_folder, root=root, label="CLI daily folder", expected_dir=True, warnings=warnings)
    if daily:
        source.append("cli_daily")
    if not daily:
        daily = _try_source(value=os.getenv("TRADING_DAILY_FOLDER"), root=root, label="env TRADING_DAILY_FOLDER", expected_dir=True, warnings=warnings)
        if daily:
            source.append("env_daily")
    if not daily:
        daily = _try_source(value=local_paths.get("daily_folder_path"), root=root, label="local_data_paths daily", expected_dir=True, warnings=warnings)
        if daily:
            source.append("local_config_daily")
    if not daily:
        daily = _try_source(value=data_paths.get("daily_folder_path"), root=root, label="project_config daily", expected_dir=True, warnings=warnings)
        if daily:
            source.append("project_config_daily")
    if not daily:
        daily, found = discover_daily_folder(root)
        candidates["daily_folders"] = found
        if daily:
            source.append("auto_daily")
            warnings.append(f"Auto-discovered daily feature folder: {daily}")

    if not weekly or not weekly.exists():
        errors.append("Could not resolve weekly feature-store CSV.")
    else:
        missing = _missing_required_columns(weekly)
        if missing:
            errors.append(f"Resolved weekly CSV is missing required canonical columns {missing}: {weekly}")

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
