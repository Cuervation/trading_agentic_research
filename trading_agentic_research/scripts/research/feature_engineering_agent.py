"""Plan feature engineering work from missing_feature_tasks.jsonl.

This agent is intentionally non-destructive. It does not mutate the feature store.
Instead, it converts missing literature-driven feature requests into an actionable
plan that a coder/executor can implement safely.
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
    "ret_26w_pct": {
        "source": "weekly close history",
        "formula": "close / close_lag_26w - 1",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "group by ticker, sort by date, pct_change(26) * 100",
    },
    "ret_52w_pct": {
        "source": "weekly close history",
        "formula": "close / close_lag_52w - 1",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "group by ticker, sort by date, pct_change(52) * 100",
    },
    "close_vs_sma20w_pct": {
        "source": "weekly close history",
        "formula": "close / sma(close, 20w) - 1",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "group by ticker rolling mean 20; (close/sma20 - 1) * 100",
    },
    "close_vs_sma52w_pct": {
        "source": "weekly close history",
        "formula": "close / sma(close, 52w) - 1",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "group by ticker rolling mean 52; (close/sma52 - 1) * 100",
    },
    "channel_r2": {
        "source": "weekly close history",
        "formula": "rolling linear regression R^2 over log(close)",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "group by ticker; rolling regression over 52 weeks; store r_squared",
    },
    "atr_14w_pct": {
        "source": "weekly OHLC history",
        "formula": "ATR(14 weeks) / close * 100",
        "required_base_columns": ["ticker", "date", "high", "low", "close"],
        "implementation_hint": "true range = max(high-low, abs(high-prev_close), abs(low-prev_close)); rolling mean 14 / close * 100",
    },
    "spy_close_vs_sma50_pct": {
        "source": "SPY daily/weekly close history",
        "formula": "SPY close / SMA50 - 1",
        "required_base_columns": ["ticker", "date", "close"],
        "implementation_hint": "filter SPY, compute SMA50, broadcast by date to rows as spy_close_vs_sma50_pct",
    },
}


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


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _header(path: str | Path | None) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists() or not p.is_file():
        return set()
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            first = f.readline()
            delim = ";" if ";" in first else ","
            f.seek(0)
            return {x.strip() for x in next(csv.reader(f, delimiter=delim), [])}
    except Exception:
        return set()


def build_feature_plan(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    state = Path(state_dir)
    tasks = read_jsonl(state / "missing_feature_tasks.jsonl")
    resolved = read_json(state / "data_paths_resolved.json", {}) or {}
    existing_features = _header(resolved.get("weekly_file"))

    missing_counter: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        for feature in task.get("missing_features", []) or []:
            if feature in existing_features:
                continue
            missing_counter[str(feature)] += 1
            if len(examples[str(feature)]) < 3:
                examples[str(feature)].append({
                    "source_id": task.get("source_id"),
                    "paper_title": task.get("paper_title"),
                    "claim": task.get("claim"),
                    "candidate_suffix": task.get("candidate_suffix"),
                })

    feature_items = []
    for feature, count in missing_counter.most_common():
        recipe = KNOWN_FEATURE_RECIPES.get(feature, {
            "source": "unknown",
            "formula": "TBD",
            "required_base_columns": [],
            "implementation_hint": "Define formula before implementation.",
        })
        base_columns = set(recipe.get("required_base_columns", []))
        base_available = sorted(base_columns.intersection(existing_features))
        base_missing = sorted(base_columns.difference(existing_features))
        feature_items.append({
            "feature": feature,
            "request_count": count,
            "known_recipe": feature in KNOWN_FEATURE_RECIPES,
            "recipe": recipe,
            "base_columns_available": base_available,
            "base_columns_missing": base_missing,
            "blocked": bool(base_missing),
            "examples": examples.get(feature, []),
        })

    payload = {
        "generated_at": now_iso(),
        "task_count": len(tasks),
        "existing_weekly_feature_count": len(existing_features),
        "existing_weekly_features_sample": sorted(existing_features)[:50],
        "features_to_add": feature_items,
        "next_action": "Implement unblocked known recipes first; re-run literature miner after regenerating feature store.",
    }

    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports / "feature_engineering_plan.json", payload)

    md_lines = [
        "# Feature Engineering Plan",
        "",
        f"Generated at: `{payload['generated_at']}`",
        f"Missing-feature tasks: **{payload['task_count']}**",
        "",
        "| feature | requests | known recipe | blocked | missing base columns |",
        "|---|---:|:---:|:---:|---|",
    ]
    for item in feature_items:
        md_lines.append(
            f"| `{item['feature']}` | {item['request_count']} | {str(item['known_recipe']).lower()} | {str(item['blocked']).lower()} | {', '.join(item['base_columns_missing']) or '-'} |"
        )
    md_lines.extend(["", "## Next action", "", payload["next_action"], ""])
    (reports / "feature_engineering_plan.md").write_text("\n".join(md_lines), encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    plan = build_feature_plan(state_dir=args.state_dir, reports_dir=args.reports_dir)
    print(json.dumps({
        "task_count": plan["task_count"],
        "features_to_add": [item["feature"] for item in plan["features_to_add"]],
        "report": str(Path(args.reports_dir) / "feature_engineering_plan.md"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
