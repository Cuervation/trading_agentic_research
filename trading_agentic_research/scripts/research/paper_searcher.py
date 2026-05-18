"""Safe paper-idea searcher for autonomous research.

Default mode is offline and deterministic. Online mode is optional and best-effort.

This module DOES NOT send paper results directly to backtests. It only creates
bibliography/paper_ideas.jsonl. The literature miner must then convert supported
ideas into auditable hypothesis cards with feature checks and falsification rules.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OFFLINE_IDEAS: list[dict[str, Any]] = [
    {
        "source_id": "time_series_momentum_moskowitz_ooi_pedersen",
        "title": "Time Series Momentum",
        "query": "time series momentum trend following intermediate horizon",
        "claim_seed": "Trend persistence over intermediate horizons may be exploitable with robust risk controls.",
        "families": ["paper_time_series_momentum", "trend_following"],
        "required_features_hint": ["ret_52w_pct", "close"],
    },
    {
        "source_id": "multi_lookback_momentum_confirmation",
        "title": "Multi-lookback momentum confirmation",
        "query": "multi lookback momentum confirmation equity trend following",
        "claim_seed": "Combining or alternating momentum lookbacks may reduce late entries and improve robustness.",
        "families": ["paper_time_series_momentum"],
        "required_features_hint": ["ret_26w_pct", "ret_52w_pct", "close"],
    },
    {
        "source_id": "quality_momentum_trend_stability",
        "title": "Quality momentum and trend stability",
        "query": "quality momentum trend stability equity strategy",
        "claim_seed": "Momentum signals may improve when combined with trend quality or stability proxies.",
        "families": ["paper_quality_momentum"],
        "required_features_hint": ["channel_r2", "close"],
    },
    {
        "source_id": "low_volatility_momentum_drawdown_control",
        "title": "Low volatility anomaly and momentum crash control",
        "query": "low volatility anomaly momentum crash risk drawdown",
        "claim_seed": "Volatility-aware momentum may reduce drawdown at the cost of some CAGR.",
        "families": ["paper_low_vol_momentum", "risk_control_refinement"],
        "required_features_hint": ["atr_14w_pct", "ret_52w_pct", "close"],
    },
    {
        "source_id": "faber_tactical_asset_allocation_regime_filter",
        "title": "Tactical asset allocation / regime filter",
        "query": "tactical asset allocation trend filter SMA equity momentum",
        "claim_seed": "Market trend filters may reduce crash exposure, but overly strict gates can miss recoveries.",
        "families": ["paper_regime_filter"],
        "required_features_hint": ["spy_close_vs_sma50_pct", "close"],
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def idea_key(row: dict[str, Any]) -> str:
    return "|".join([
        str(row.get("source_id") or "").strip().lower(),
        str(row.get("title") or "").strip().lower(),
        str(row.get("year") or ""),
        str(row.get("query") or row.get("query_seed") or "").strip().lower(),
        str(row.get("claim_seed") or "").strip().lower()[:160],
    ])


def append_jsonl_unique(path: str | Path, rows: list[dict[str, Any]]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = read_jsonl(p)
    keys = {idea_key(row) for row in existing}
    written = 0
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            key = idea_key(row)
            if key in keys:
                continue
            keys.add(key)
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            written += 1
    return written


def _semantic_scholar_search(query: str, limit: int = 5, timeout: int = 10) -> list[dict[str, Any]]:
    encoded = urllib.parse.urlencode({"query": query, "limit": str(limit), "fields": "title,year,abstract,url,authors"})
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": "trading-agentic-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec: optional public scholarly API
        payload = json.loads(resp.read().decode("utf-8"))
    out = []
    for item in payload.get("data", []) or []:
        out.append({
            "source_id": "semantic_scholar",
            "title": item.get("title"),
            "year": item.get("year"),
            "url": item.get("url"),
            "abstract": item.get("abstract"),
            "authors": [a.get("name") for a in item.get("authors", []) if a.get("name")],
        })
    return out


def generate_paper_ideas(*, output: str | Path = "bibliography/paper_ideas.jsonl", online: bool = False, limit: int = 5) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for idea in DEFAULT_OFFLINE_IDEAS:
        row = dict(idea)
        row["mode"] = "offline_seed"
        row["created_at"] = now_iso()
        rows.append(row)
        if online:
            try:
                for result in _semantic_scholar_search(idea["query"], limit=limit):
                    result.update({
                        "mode": "online_semantic_scholar",
                        "query_seed": idea["query"],
                        "claim_seed": idea["claim_seed"],
                        "families": idea["families"],
                        "required_features_hint": idea.get("required_features_hint", []),
                        "created_at": now_iso(),
                    })
                    rows.append(result)
            except Exception as exc:
                rows.append({"mode": "online_search_error", "query_seed": idea["query"], "error": str(exc), "created_at": now_iso()})
    written = append_jsonl_unique(output, rows)
    return {"output": str(output), "rows_written": written, "candidate_rows": len(rows), "online": online}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--online", action="store_true")
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    print(json.dumps(generate_paper_ideas(output=args.output, online=args.online, limit=args.limit), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
