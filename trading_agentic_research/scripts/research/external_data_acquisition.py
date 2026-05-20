"""Acquire and validate safe external metadata used by research expansion.

This module is intentionally conservative:
- local curated CSVs win over network sources;
- Wikipedia is used only for S&P 500 constituent sector metadata;
- sectors are never invented;
- cached output is validated against the active weekly feature store before use.
"""
from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOCAL_CANDIDATES = [
    ROOT / "data" / "sp500_sector_metadata.csv",
    ROOT / "data" / "ticker_sector_map.csv",
    ROOT / "metadata" / "sp500_sector_metadata.csv",
]
CACHE_PATH = ROOT / "data" / "sp500_sector_metadata.csv"
WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
MIN_COVERAGE = 0.80


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


def _read_csv(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig", **kwargs)


def _weekly_tickers(weekly_file: str | Path) -> set[str]:
    df = _read_csv(weekly_file, usecols=["ticker"])
    return {str(x).strip().upper() for x in df["ticker"].dropna().unique() if str(x).strip()}


def _normalize_symbol(symbol: Any) -> str:
    raw = str(symbol).strip().upper()
    raw = raw.replace("/", "-").replace(" ", "")
    return raw


def normalize_to_dataset_symbol(symbol: Any, dataset_tickers: set[str]) -> str:
    raw = _normalize_symbol(symbol)
    candidates = [raw, raw.replace(".", "-"), raw.replace("-", ".")]
    for candidate in candidates:
        if candidate in dataset_tickers:
            return candidate
    return raw.replace(".", "-")


def _canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    lookup = {str(c).strip().lower().replace("_", " "): c for c in df.columns}
    ticker_col = lookup.get("ticker") or lookup.get("symbol")
    sector_col = lookup.get("sector") or lookup.get("gics sector")
    industry_col = (
        lookup.get("industry")
        or lookup.get("gics sub industry")
        or lookup.get("gics sub-industry")
        or lookup.get("sub industry")
    )
    missing = []
    if ticker_col is None:
        missing.append("ticker/symbol")
    if sector_col is None:
        missing.append("sector/GICS Sector")
    if industry_col is None:
        missing.append("industry/GICS Sub-Industry")
    if missing:
        raise ValueError(f"metadata missing required columns: {missing}")
    return df[[ticker_col, sector_col, industry_col]].rename(
        columns={ticker_col: "ticker", sector_col: "sector", industry_col: "industry"}
    )


def _load_local_metadata() -> tuple[pd.DataFrame | None, str | None, list[str]]:
    errors: list[str] = []
    for path in LOCAL_CANDIDATES:
        if not path.exists():
            continue
        try:
            return _canonicalize_columns(_read_csv(path)), str(path), errors
        except Exception as exc:  # keep looking; cache may be stale or malformed
            errors.append(f"{path}: {exc}")
    return None, None, errors


def _fetch_wikipedia_metadata() -> tuple[pd.DataFrame, str]:
    request = Request(
        WIKIPEDIA_SP500_URL,
        headers={"User-Agent": "trading-agentic-research/1.0 sector-metadata-validation"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    tables = pd.read_html(StringIO(html))
    for table in tables:
        try:
            return _canonicalize_columns(table), WIKIPEDIA_SP500_URL
        except Exception:
            continue
    raise ValueError("Wikipedia page did not contain Symbol/GICS Sector/GICS Sub-Industry table")


def validate_sector_metadata(
    metadata: pd.DataFrame,
    *,
    weekly_file: str | Path,
    source: str,
    reports_dir: str | Path = "reports",
    state_dir: str | Path = "state",
) -> dict[str, Any]:
    dataset_tickers = _weekly_tickers(weekly_file)
    out = _canonicalize_columns(metadata).copy()
    out["ticker"] = out["ticker"].map(lambda x: normalize_to_dataset_symbol(x, dataset_tickers))
    out["sector"] = out["sector"].astype(str).str.strip()
    out["industry"] = out["industry"].astype(str).str.strip()
    out = out[(out["ticker"] != "") & (out["sector"] != "")]
    duplicate_count = int(out["ticker"].duplicated().sum())
    out = out.drop_duplicates(subset=["ticker"], keep="first").copy()
    out["source"] = source
    out["fetched_at"] = now_iso()

    covered = sorted(dataset_tickers.intersection(set(out["ticker"])))
    missing = sorted(dataset_tickers.difference(set(out["ticker"])))
    coverage = (len(covered) / len(dataset_tickers)) if dataset_tickers else 0.0
    valid = bool(dataset_tickers) and coverage >= MIN_COVERAGE and not out["ticker"].duplicated().any()

    payload = {
        "status": "valid" if valid else "invalid",
        "source": source,
        "weekly_file": str(weekly_file),
        "cache_path": str(CACHE_PATH),
        "dataset_ticker_count": len(dataset_tickers),
        "metadata_ticker_count": int(out["ticker"].nunique()),
        "covered_ticker_count": len(covered),
        "coverage": coverage,
        "min_coverage": MIN_COVERAGE,
        "duplicates_removed": duplicate_count,
        "missing_tickers_sample": missing[:50],
        "validated_at": now_iso(),
    }

    if valid:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        out[["ticker", "sector", "industry", "source", "fetched_at"]].sort_values("ticker").to_csv(CACHE_PATH, index=False)

    reports = Path(reports_dir)
    state = Path(state_dir)
    reports.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    write_json(state / "sector_metadata_validation.json", payload)
    md = [
        "# Sector Metadata Validation",
        "",
        f"- Status: **{payload['status']}**",
        f"- Source: `{source}`",
        f"- Weekly file: `{weekly_file}`",
        f"- Cache path: `{CACHE_PATH}`",
        f"- Coverage: **{coverage:.2%}** ({len(covered)}/{len(dataset_tickers)})",
        f"- Duplicates removed: **{duplicate_count}**",
        "",
        "## Missing ticker sample",
        "",
        ", ".join(missing[:50]) or "-",
        "",
    ]
    (reports / "sector_metadata_validation.md").write_text("\n".join(md), encoding="utf-8")
    return payload


def acquire_sector_metadata(
    *,
    weekly_file: str | Path,
    reports_dir: str | Path = "reports",
    state_dir: str | Path = "state",
) -> dict[str, Any]:
    errors: list[str] = []
    local, local_source, local_errors = _load_local_metadata()
    errors.extend(local_errors)
    if local is not None and local_source:
        validation = validate_sector_metadata(local, weekly_file=weekly_file, source=local_source, reports_dir=reports_dir, state_dir=state_dir)
        validation["acquisition"] = "local_file"
        validation["errors"] = errors
        return validation

    try:
        wiki, source = _fetch_wikipedia_metadata()
        validation = validate_sector_metadata(wiki, weekly_file=weekly_file, source=source, reports_dir=reports_dir, state_dir=state_dir)
        validation["acquisition"] = "wikipedia"
        validation["errors"] = errors
        return validation
    except Exception as exc:
        errors.append(f"wikipedia:{exc}")
        payload = {
            "status": "blocked",
            "reason": "missing_sector_classification_source",
            "next_action": (
                "Add data/sp500_sector_metadata.csv with columns ticker, sector, industry "
                "or restore internet access for Wikipedia S&P 500 constituents."
            ),
            "weekly_file": str(weekly_file),
            "errors": errors,
            "validated_at": now_iso(),
        }
        write_json(Path(state_dir) / "sector_metadata_validation.json", payload)
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        (Path(reports_dir) / "sector_metadata_validation.md").write_text(
            "# Sector Metadata Validation\n\n"
            "- Status: **blocked**\n"
            "- Reason: `missing_sector_classification_source`\n\n"
            f"Next action: {payload['next_action']}\n\n"
            "Errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n",
            encoding="utf-8",
        )
        return payload


def cache_sector_metadata(*, weekly_file: str | Path, reports_dir: str | Path = "reports", state_dir: str | Path = "state") -> dict[str, Any]:
    return acquire_sector_metadata(weekly_file=weekly_file, reports_dir=reports_dir, state_dir=state_dir)


def _weekly_from_state(state_dir: str | Path) -> str | None:
    resolved = read_json(Path(state_dir) / "data_paths_resolved.json", {}) or {}
    weekly = resolved.get("weekly_file")
    return str(weekly) if weekly else None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Acquire validated external sector metadata for autonomous feature engineering.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--weekly-file-from-state", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    weekly = args.weekly_file
    if args.weekly_file_from_state:
        weekly = _weekly_from_state(args.state_dir)
    if not weekly:
        print(json.dumps({"status": "blocked", "reason": "missing_weekly_file"}, indent=2, ensure_ascii=False))
        return 2
    result = acquire_sector_metadata(weekly_file=weekly, reports_dir=args.reports_dir, state_dir=args.state_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("status") == "valid" else 3


if __name__ == "__main__":
    raise SystemExit(main())
