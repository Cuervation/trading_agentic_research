"""Plan feature engineering work from missing_feature_tasks.jsonl.

Safe by default: creates a plan plus a candidate script, but does not mutate the feature store.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KNOWN_FEATURE_RECIPES: dict[str, dict[str, Any]] = {
    "ret_26w_pct": {"source": "weekly close", "formula": "pct_change(26)*100", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "group by ticker; pct_change(26)*100"},
    "ret_52w_pct": {"source": "weekly close", "formula": "pct_change(52)*100", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "group by ticker; pct_change(52)*100"},
    "close_vs_sma20w_pct": {"source": "weekly close", "formula": "close/sma20 - 1", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "rolling mean 20"},
    "close_vs_sma52w_pct": {"source": "weekly close", "formula": "close/sma52 - 1", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "rolling mean 52"},
    "channel_r2": {"source": "weekly close", "formula": "rolling linear regression R^2", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "rolling 52w corr^2 on log close"},
    "atr_14w_pct": {"source": "weekly OHLC", "formula": "ATR14/close*100", "required_base_columns": ["ticker", "date", "high", "low", "close"], "implementation_hint": "true range rolling mean 14"},
    "spy_close_vs_sma50_pct": {"source": "SPY close", "formula": "SPY close/SMA50 - 1", "required_base_columns": ["ticker", "date", "close"], "implementation_hint": "compute on SPY and merge by date"},
}

GENERATED_SCRIPT = '''"""Generated candidate feature engineering script. Writes a new output CSV."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd


def add_supported_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = {"ticker", "date", "close"}.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["ticker", "date"])
    g = out.groupby("ticker", group_keys=False)
    if "ret_26w_pct" not in out.columns:
        out["ret_26w_pct"] = g["close"].pct_change(26) * 100
    if "ret_52w_pct" not in out.columns:
        out["ret_52w_pct"] = g["close"].pct_change(52) * 100
    if "close_vs_sma20w_pct" not in out.columns:
        sma20 = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
        out["close_vs_sma20w_pct"] = (out["close"] / sma20 - 1) * 100
    if "close_vs_sma52w_pct" not in out.columns:
        sma52 = g["close"].transform(lambda s: s.rolling(52, min_periods=52).mean())
        out["close_vs_sma52w_pct"] = (out["close"] / sma52 - 1) * 100
    if "channel_r2" not in out.columns:
        def rolling_r2(close: pd.Series, window: int = 52) -> pd.Series:
            y = np.log(close.astype(float).replace(0, np.nan))
            x = np.arange(window, dtype=float)
            def calc(arr):
                if np.isnan(arr).any(): return np.nan
                corr = np.corrcoef(x, arr)[0, 1]
                return float(corr*corr) if np.isfinite(corr) else np.nan
            return y.rolling(window, min_periods=window).apply(calc, raw=True)
        out["channel_r2"] = g["close"].transform(rolling_r2)
    if "atr_14w_pct" not in out.columns and {"high", "low", "close"}.issubset(out.columns):
        prev_close = g["close"].shift(1)
        tr = pd.concat([(out["high"]-out["low"]).abs(), (out["high"]-prev_close).abs(), (out["low"]-prev_close).abs()], axis=1).max(axis=1)
        out["atr_14w_pct"] = tr.groupby(out["ticker"]).transform(lambda s: s.rolling(14, min_periods=14).mean()) / out["close"] * 100
    if "spy_close_vs_sma50_pct" not in out.columns:
        spy = out[out["ticker"].astype(str).str.upper()=="SPY"][["date", "close"]].copy()
        if not spy.empty:
            spy = spy.sort_values("date")
            spy["spy_close_vs_sma50_pct"] = (spy["close"] / spy["close"].rolling(50, min_periods=50).mean() - 1) * 100
            out = out.merge(spy[["date", "spy_close_vs_sma50_pct"]], on="date", how="left")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = add_supported_features(pd.read_csv(args.input))
    out.to_csv(args.output, index=False)
    print({"input": args.input, "output": args.output, "rows": len(out), "columns": list(out.columns)})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''

GENERATED_TEST = '''import pandas as pd
from scripts.generated.feature_engineering_candidate import add_supported_features


def test_add_supported_features_basic():
    rows=[]
    for ticker in ["SPY", "AAA"]:
        for i in range(60):
            rows.append({"ticker": ticker, "date": f"2020-01-{(i%28)+1:02d}", "close": 100+i, "high": 101+i, "low": 99+i})
    out = add_supported_features(pd.DataFrame(rows))
    for col in ["ret_26w_pct", "ret_52w_pct", "close_vs_sma20w_pct", "close_vs_sma52w_pct", "channel_r2"]:
        assert col in out.columns
'''


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError: return default


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p=Path(path)
    if not p.exists(): return []
    rows=[]
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try: rows.append(json.loads(line))
            except json.JSONDecodeError: pass
    return rows


def write_json(path: str | Path, payload: Any) -> None:
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _header(path: str | Path | None) -> set[str]:
    if not path: return set()
    p=Path(path)
    if not p.exists() or not p.is_file(): return set()
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            first=f.readline(); delim=';' if ';' in first else ','; f.seek(0)
            return {x.strip() for x in next(csv.reader(f, delimiter=delim), [])}
    except Exception: return set()


def build_feature_plan(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports", generate_candidate: bool = True) -> dict[str, Any]:
    state=Path(state_dir); reports=Path(reports_dir)
    tasks=read_jsonl(state/"missing_feature_tasks.jsonl")
    resolved=read_json(state/"data_paths_resolved.json", {}) or {}
    existing_features=_header(resolved.get("weekly_file"))
    missing_counter: Counter[str]=Counter(); examples: dict[str, list[dict[str, Any]]]=defaultdict(list)
    for task in tasks:
        for feature in task.get("missing_features", []) or []:
            if feature in existing_features: continue
            missing_counter[str(feature)] += 1
            if len(examples[str(feature)]) < 3:
                examples[str(feature)].append({"source_id": task.get("source_id"), "paper_title": task.get("paper_title"), "claim": task.get("claim"), "candidate_suffix": task.get("candidate_suffix")})
    items=[]
    for feature,count in missing_counter.most_common():
        recipe=KNOWN_FEATURE_RECIPES.get(feature, {"source":"unknown","formula":"TBD","required_base_columns":[],"implementation_hint":"Define formula before implementation."})
        base=set(recipe.get("required_base_columns", [])); base_missing=sorted(base.difference(existing_features))
        items.append({"feature": feature, "request_count": count, "known_recipe": feature in KNOWN_FEATURE_RECIPES, "recipe": recipe, "base_columns_available": sorted(base.intersection(existing_features)), "base_columns_missing": base_missing, "blocked": bool(base_missing), "examples": examples.get(feature, [])})
    reports.mkdir(parents=True, exist_ok=True)
    payload={"generated_at": now_iso(), "task_count": len(tasks), "existing_weekly_feature_count": len(existing_features), "existing_weekly_features_sample": sorted(existing_features)[:50], "features_to_add": items, "candidate_script": "scripts/generated/feature_engineering_candidate.py" if generate_candidate else None, "candidate_test": "tests/generated/test_feature_engineering_candidate.py" if generate_candidate else None, "next_action": "Review generated candidate script, run tests, then regenerate feature store to a NEW output file."}
    write_json(reports/"feature_engineering_plan.json", payload)
    md=["# Feature Engineering Plan", "", f"Generated at: `{payload['generated_at']}`", f"Missing-feature tasks: **{payload['task_count']}**", "", "| feature | requests | known recipe | blocked | missing base columns |", "|---|---:|:---:|:---:|---|"]
    for item in items:
        md.append(f"| `{item['feature']}` | {item['request_count']} | {str(item['known_recipe']).lower()} | {str(item['blocked']).lower()} | {', '.join(item['base_columns_missing']) or '-'} |")
    md.extend(["", "## Next action", "", payload["next_action"], ""])
    (reports/"feature_engineering_plan.md").write_text("\n".join(md), encoding="utf-8")
    if generate_candidate:
        sp=Path("scripts/generated/feature_engineering_candidate.py"); tp=Path("tests/generated/test_feature_engineering_candidate.py")
        sp.parent.mkdir(parents=True, exist_ok=True); tp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(GENERATED_SCRIPT, encoding="utf-8"); tp.write_text(GENERATED_TEST, encoding="utf-8")
    return payload


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--state-dir", default="state"); p.add_argument("--reports-dir", default="reports"); p.add_argument("--no-generate-candidate", action="store_true")
    args=p.parse_args(); plan=build_feature_plan(state_dir=args.state_dir, reports_dir=args.reports_dir, generate_candidate=not args.no_generate_candidate)
    print(json.dumps({"task_count": plan["task_count"], "features_to_add": [item["feature"] for item in plan["features_to_add"]], "report": str(Path(args.reports_dir)/"feature_engineering_plan.md"), "candidate_script": plan.get("candidate_script")}, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
