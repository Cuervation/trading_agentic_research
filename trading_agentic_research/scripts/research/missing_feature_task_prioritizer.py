"""Prioritize missing feature tasks that block literature-derived research.

This module is intentionally planning-only: it reads the backlog created by
literature_hypothesis_miner.py and writes an actionable feature priority report.
It does not mutate feature stores, parent state, runs, or hypothesis history.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import get_close_matches
from pathlib import Path
from typing import Any


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


def _header(path: str | Path | None) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists() or not p.is_file():
        return set()
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            first = f.readline()
            delimiter = ";" if ";" in first and first.count(";") > first.count(",") else ","
            f.seek(0)
            return {str(x).strip() for x in next(csv.reader(f, delimiter=delimiter), []) if str(x).strip()}
    except Exception:
        return set()


def _daily_header_from_resolved(resolved: dict[str, Any]) -> set[str]:
    folder = Path(str(resolved.get("daily_folder") or ""))
    if not folder.exists() or not folder.is_dir():
        return set()
    for candidate in sorted(folder.glob("*.csv")):
        return _header(candidate)
    return set()


def _semantic_exhausted_families(state_dir: str | Path) -> set[str]:
    semantic = read_json(Path(state_dir) / "semantic_branch_exhaustion.json", {}) or {}
    families: set[str] = set()
    for branch_key, payload in (semantic.get("branches", {}) or {}).items():
        if str(payload.get("status") or "").lower() == "exhausted" or payload.get("exhausted") is True:
            families.add(str(branch_key).split("/", 1)[0])
    return families


def _cooldown_info(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {}
    cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for family, detail in cooldowns.items():
        detail = detail if isinstance(detail, dict) else {"reason": str(detail)}
        out[str(family)] = {
            **detail,
            "hard": bool(detail.get("cooldown_until")),
        }
    return out


FEATURE_RECIPES: dict[str, dict[str, Any]] = {
    "ret_13w_pct": {
        "source": "weekly close",
        "formula": "group by ticker; pct_change(13) * 100",
        "base_columns": ["ticker", "close"],
        "cost": "low",
        "calculable_from": "weekly",
        "note": "ret_12w_pct already exists, but ret_13w_pct is a distinct template dependency.",
    },
    "realized_vol_13w_pct": {
        "source": "weekly close or weekly returns",
        "formula": "rolling 13-week std of weekly returns, annualization optional but must be documented",
        "base_columns": ["ticker", "close"],
        "cost": "low",
        "calculable_from": "weekly",
        "note": "volatility_12w_pct exists and can be used to validate scale/shape.",
    },
    "downside_vol_13w_pct": {
        "source": "weekly close or weekly returns",
        "formula": "rolling 13-week std using only negative weekly returns",
        "base_columns": ["ticker", "close"],
        "cost": "medium",
        "calculable_from": "weekly",
        "note": "Use the same return convention as realized_vol_13w_pct.",
    },
    "max_drawdown_26w_pct": {
        "source": "weekly close",
        "formula": "rolling 26-week max drawdown from rolling peak close",
        "base_columns": ["ticker", "close"],
        "cost": "low",
        "calculable_from": "weekly",
        "note": "drawdown_from_high_26w_pct exists as a near proxy; decide whether the exact max-drawdown definition is needed.",
    },
    "residual_ret_26w_pct": {
        "source": "weekly stock returns plus SPY/market return",
        "formula": "26-week stock return residualized against SPY return via rolling beta or simple market subtraction baseline",
        "base_columns": ["ticker", "close"],
        "cost": "medium",
        "calculable_from": "weekly",
        "note": "Can start with market-residual before sector residual; document the model.",
    },
    "ret_vs_sector_26w_pct": {
        "source": "weekly returns plus sector metadata",
        "formula": "stock ret_26w_pct minus sector aggregate ret_26w_pct",
        "base_columns": ["ticker", "close"],
        "cost": "high",
        "calculable_from": "weekly+metadata",
        "note": "Requires sector/industry mapping; none is assumed from price columns alone.",
    },
    "sector_ret_26w_pct": {
        "source": "weekly returns plus sector metadata",
        "formula": "sector-level 26-week return aggregate by sector/date",
        "base_columns": ["ticker", "close"],
        "cost": "high",
        "calculable_from": "weekly+metadata",
        "note": "Requires sector/industry mapping; pair with ret_vs_sector_26w_pct.",
    },
    "market_breadth_above_sma50_pct": {
        "source": "weekly or daily universe prices",
        "formula": "percentage of active universe above 50-day or 10-week SMA by date",
        "base_columns": ["ticker", "close"],
        "cost": "medium",
        "calculable_from": "weekly/daily",
        "note": "No external feature is needed if the weekly universe is representative, but membership survivorship must be documented.",
    },
    "atr_14w_pct": {
        "source": "weekly OHLC",
        "formula": "rolling 14-week average true range divided by close",
        "base_columns": ["ticker", "high", "low", "close"],
        "cost": "low",
        "calculable_from": "weekly/daily",
        "note": "This may already exist in newer feature stores; skip if present.",
    },
}


def _nearby_columns(feature: str, weekly: set[str], daily: set[str]) -> list[str]:
    existing = sorted(weekly.union(daily))
    matches = set(get_close_matches(feature, existing, n=8, cutoff=0.56))
    tokens = [part for part in feature.replace("_pct", "").split("_") if len(part) >= 3]
    for col in existing:
        lower = col.lower()
        if any(tok.lower() in lower for tok in tokens):
            matches.add(col)
        if len(matches) >= 12:
            break
    return sorted(matches)[:12]


def _base_columns_available(recipe: dict[str, Any], weekly: set[str], daily: set[str]) -> tuple[list[str], list[str]]:
    base = [str(x) for x in recipe.get("base_columns", [])]
    existing = weekly.union(daily)
    present = [col for col in base if col in existing]
    missing = [col for col in base if col not in existing]
    return present, missing


def _priority(score: int, unlocks: int, cost: str) -> str:
    if score >= 11 or (unlocks >= 4 and cost in {"low", "medium"}):
        return "high"
    if score >= 7:
        return "medium"
    return "low"


def prioritize_missing_feature_tasks(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    paper_ideas: str | Path = "bibliography/paper_ideas.jsonl",
) -> dict[str, Any]:
    state = Path(state_dir)
    reports = Path(reports_dir)
    tasks = read_jsonl(state / "missing_feature_tasks.jsonl")
    ideas = read_jsonl(paper_ideas)
    resolved = read_json(state / "data_paths_resolved.json", {}) or {}
    weekly_features = _header(resolved.get("weekly_file"))
    daily_features = _daily_header_from_resolved(resolved)
    exhausted_families = _semantic_exhausted_families(state)
    cooldowns = _cooldown_info(state)

    idea_by_source = {str(row.get("source_id") or ""): row for row in ideas}
    grouped: dict[str, dict[str, Any]] = {}
    already_available: list[str] = []

    for task in tasks:
        missing_features = [str(x) for x in task.get("missing_features", []) or []]
        for feature in missing_features:
            if feature in weekly_features:
                already_available.append(feature)
                continue
            item = grouped.setdefault(
                feature,
                {
                    "feature": feature,
                    "tasks": [],
                    "source_ids": set(),
                    "paper_titles": set(),
                    "families": set(),
                    "axes": set(),
                    "candidate_suffixes": set(),
                },
            )
            item["tasks"].append(task)
            if task.get("source_id"):
                item["source_ids"].add(str(task.get("source_id")))
            if task.get("paper_title"):
                item["paper_titles"].add(str(task.get("paper_title")))
            if task.get("family"):
                item["families"].add(str(task.get("family")))
            if task.get("axis"):
                item["axes"].add(str(task.get("axis")))
            if task.get("candidate_suffix"):
                item["candidate_suffixes"].add(str(task.get("candidate_suffix")))

    items: list[dict[str, Any]] = []
    for feature, raw in grouped.items():
        source_ids = sorted(raw["source_ids"])
        families = sorted(raw["families"])
        recipe = dict(FEATURE_RECIPES.get(feature, {
            "source": "unknown",
            "formula": "Define feature before implementation.",
            "base_columns": [],
            "cost": "medium",
            "calculable_from": "unknown",
            "note": "No canned recipe yet; add one before implementing.",
        }))
        present_base, missing_base = _base_columns_available(recipe, weekly_features, daily_features)
        near = _nearby_columns(feature, weekly_features, daily_features)
        hard_cooldown_families = [fam for fam in families if cooldowns.get(fam, {}).get("hard")]
        advisory_cooldown_families = [fam for fam in families if fam in cooldowns and fam not in hard_cooldown_families]
        sem_exhausted = [fam for fam in families if fam in exhausted_families]
        opens_non_exhausted = any(fam not in exhausted_families for fam in families) or not families

        unlock_count = len(source_ids)
        score = 0
        score += min(6, unlock_count * 2)
        score += 3 if not missing_base and recipe.get("calculable_from") in {"weekly", "weekly/daily"} else 0
        score += 2 if near else 0
        score += {"low": 3, "medium": 2, "high": 0}.get(str(recipe.get("cost")), 1)
        score += 2 if opens_non_exhausted else 0
        score -= 2 if hard_cooldown_families else 0
        score -= 1 if sem_exhausted and not opens_non_exhausted else 0

        example_tasks = raw["tasks"][:5]
        items.append({
            "feature": feature,
            "priority": _priority(score, unlock_count, str(recipe.get("cost"))),
            "score": score,
            "paper_ideas_unlocked": unlock_count,
            "source_ids": source_ids,
            "paper_titles": sorted(raw["paper_titles"]),
            "families": families,
            "axes": sorted(raw["axes"]),
            "candidate_suffixes": sorted(raw["candidate_suffixes"]),
            "recipe": recipe,
            "base_columns_available": present_base,
            "base_columns_missing": missing_base,
            "nearby_existing_columns": near,
            "calculable_from_current_data": not missing_base and recipe.get("calculable_from") != "unknown",
            "implementation_cost": recipe.get("cost"),
            "opens_non_exhausted_family": opens_non_exhausted,
            "semantic_exhausted_families": sem_exhausted,
            "hard_cooldown_families": hard_cooldown_families,
            "advisory_cooldown_families": advisory_cooldown_families,
            "example_tasks": [
                {
                    "source_id": task.get("source_id"),
                    "paper_title": task.get("paper_title"),
                    "candidate_suffix": task.get("candidate_suffix"),
                    "family": task.get("family"),
                    "claim": task.get("claim"),
                    "paper_idea_hint": idea_by_source.get(str(task.get("source_id") or ""), {}).get("required_features_hint"),
                }
                for task in example_tasks
            ],
        })

    items.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item["priority"], 9), -int(item["score"]), item["feature"]))

    payload = {
        "generated_at": now_iso(),
        "state_dir": str(state),
        "reports_dir": str(reports),
        "task_count": len(tasks),
        "missing_feature_count": len(items),
        "already_available_task_features": sorted(set(already_available)),
        "weekly_feature_count": len(weekly_features),
        "daily_feature_count": len(daily_features),
        "priorities": items,
        "next_action": "Implement the highest-priority feature(s) in the feature store or add supported templates that use existing proxy columns; then rerun literature mining before any backtest.",
    }

    reports.mkdir(parents=True, exist_ok=True)
    write_json(state / "missing_feature_priority.json", payload)
    write_json(reports / "missing_feature_priority.json", payload)
    _write_markdown_report(reports / "missing_feature_priority.md", payload)
    return payload


def _write_markdown_report(path: str | Path, payload: dict[str, Any]) -> None:
    rows = payload.get("priorities", []) or []
    lines = [
        "# Missing Feature Priority",
        "",
        "Actionable backlog for converting paper ideas into real hypotheses. This report is planning-only; it does not mutate feature stores or hypothesis history.",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Missing-feature tasks read: **{payload.get('task_count', 0)}**",
        f"- Distinct missing features: **{payload.get('missing_feature_count', 0)}**",
        "",
        "## Priority table",
        "",
        "| priority | feature | score | papers unlocked | cost | calculable now | nearby/current columns |",
        "|---|---|---:|---:|---|:---:|---|",
    ]
    for item in rows:
        near = ", ".join(f"`{x}`" for x in (item.get("nearby_existing_columns") or [])[:5]) or "-"
        lines.append(
            "| {priority} | `{feature}` | {score} | {unlocks} | {cost} | {calc} | {near} |".format(
                priority=item.get("priority"),
                feature=item.get("feature"),
                score=item.get("score"),
                unlocks=item.get("paper_ideas_unlocked"),
                cost=item.get("implementation_cost"),
                calc="yes" if item.get("calculable_from_current_data") else "no",
                near=near,
            )
        )

    lines.extend(["", "## Details", ""])
    for item in rows[:12]:
        recipe = item.get("recipe", {}) or {}
        lines.extend([
            f"### `{item.get('feature')}` — {item.get('priority')} priority",
            "",
            f"- Unlocks: **{item.get('paper_ideas_unlocked')}** paper idea(s): {', '.join(item.get('source_ids') or []) or '-'}",
            f"- Formula: {recipe.get('formula')}",
            f"- Base columns available: {', '.join(item.get('base_columns_available') or []) or '-'}",
            f"- Base columns missing: {', '.join(item.get('base_columns_missing') or []) or '-'}",
            f"- Families: {', '.join(item.get('families') or []) or '-'}",
            f"- Nearby columns: {', '.join(item.get('nearby_existing_columns') or []) or '-'}",
            f"- Note: {recipe.get('note')}",
            "",
        ])

    lines.extend([
        "## Suggested command",
        "",
        "```powershell",
        "python .\\scripts\\research\\missing_feature_task_prioritizer.py `",
        "  --state-dir .\\state `",
        "  --reports-dir .\\reports `",
        "  --paper-ideas .\\bibliography\\paper_ideas.jsonl",
        "```",
        "",
        "Next: implement the highest-priority feature or use an existing proxy template; then rerun literature mining before launching backtests.",
        "",
    ])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Prioritize missing feature tasks blocking literature hypotheses.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    args = p.parse_args()
    result = prioritize_missing_feature_tasks(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        paper_ideas=args.paper_ideas,
    )
    print(json.dumps({
        "task_count": result.get("task_count"),
        "missing_feature_count": result.get("missing_feature_count"),
        "top_features": [item.get("feature") for item in (result.get("priorities") or [])[:5]],
        "report": str(Path(args.reports_dir) / "missing_feature_priority.md"),
        "state": str(Path(args.state_dir) / "missing_feature_priority.json"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
