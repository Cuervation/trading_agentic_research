"""Generate a compact autonomy quality report from state/reports."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows

def build_report(state_dir: str | Path = "state", reports_dir: str | Path = "reports", last_n: int = 40) -> str:
    ledger = read_jsonl(Path(state_dir) / "research_ledger.jsonl")[-last_n:]
    guard = read_jsonl(Path(state_dir) / "pre_run_guard_events.jsonl")[-last_n:]
    values = Counter(str(r.get("value_delivered") or r.get("decision") or "unknown") for r in ledger)
    guard_reasons = Counter(str(r.get("reason") or "unknown").split(":")[0] for r in guard)
    lines = ["# Autonomy Quality Report", "", f"- Ledger rows analyzed: {len(ledger)}", f"- Pre-run guard blocks analyzed: {len(guard)}", "", "## Value delivered"]
    lines += [f"- {k}: {v}" for k, v in values.most_common()] or ["- none"]
    lines += ["", "## Pre-run guard blocks"]
    lines += [f"- {k}: {v}" for k, v in guard_reasons.most_common()] or ["- none"]
    lines += ["", "## Reading", "- A high duplicate_blocked count means generation/selection is too close to prior experiments.", "- Pre-run guard blocks are good when they replace expensive duplicate backtests.", "- Repeated SPY fallback warnings should be treated as a data-quality issue before market-filter research."]
    return "\n".join(lines) + "\n"

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--last-n", type=int, default=40)
    args = p.parse_args()
    report = build_report(args.state_dir, args.reports_dir, args.last_n)
    out = Path(args.reports_dir) / "autonomy_quality_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Output: {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
