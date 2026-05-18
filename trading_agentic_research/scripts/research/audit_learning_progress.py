"""Audit whether the research loop is delivering continuous learning value."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.artifact_index import iter_run_dirs, read_json
from scripts.research.champion_governance import load_champion_state
from scripts.research.research_ledger import read_ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit continuous learning progress.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--reports-dir", default="reports")
    return parser.parse_args()


def pct(part: int, total: int) -> float:
    return round(part / total * 100.0, 2) if total else 0.0


def main() -> int:
    args = parse_args()
    runs = iter_run_dirs(args.runs_dir)
    ledger = read_ledger(args.state_dir)
    index = read_json(Path(args.state_dir) / "artifact_hash_index.json", {}) or {}
    champion = load_champion_state(args.state_dir)

    run_count = len(runs)
    with_audit = sum(1 for p in runs if (p / "audit.json").exists())
    with_manifest = sum(1 for p in runs if (p / "run_manifest.json").exists())
    signatures = index.get("signatures", {}) or {}
    indexed_runs = index.get("runs", {}) or {}
    duplicate_runs = [row for row in indexed_runs.values() if row.get("is_duplicate")]
    value_counts = Counter(str(row.get("value_delivered")) for row in ledger)
    hypothesis_counts = Counter(str(row.get("hypothesis_id")) for row in ledger if row.get("hypothesis_id"))
    repeated_hypotheses = [(h, c) for h, c in hypothesis_counts.most_common() if c > 1]

    lines = [
        "# Learning Progress Audit",
        "",
        f"- Runs found: {run_count}",
        f"- Runs with audit.json: {with_audit}/{run_count} ({pct(with_audit, run_count)}%)",
        f"- Runs with run_manifest.json: {with_manifest}/{run_count} ({pct(with_manifest, run_count)}%)",
        f"- Indexed runs: {len(indexed_runs)}",
        f"- Unique artifact signatures: {len(signatures)}",
        f"- Duplicate runs: {len(duplicate_runs)} ({pct(len(duplicate_runs), len(indexed_runs))}%)",
        f"- Ledger events: {len(ledger)}",
        f"- Best champion: `{champion.get('best_champion_run_id')}`",
        f"- Current parent: `{champion.get('current_parent_run_id')}`",
        f"- Aggressive champion: `{champion.get('aggressive_champion_run_id')}`",
        f"- Promotion/baseline candidate: `{champion.get('baseline_candidate_run_id')}`",
        "",
        "## Value delivered",
        "",
    ]
    for key, count in sorted(value_counts.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Repeated hypotheses", ""])
    if repeated_hypotheses:
        for hyp, count in repeated_hypotheses[:25]:
            lines.append(f"- {hyp}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Recommendations", ""])
    if run_count and pct(with_audit, run_count) < 100:
        lines.append("- Make audit.json mandatory after each backtest.")
    if indexed_runs and pct(len(duplicate_runs), len(indexed_runs)) > 20:
        lines.append("- Duplicate rate is high; block artifact signatures before follow-up decisions.")
    if not ledger:
        lines.append("- Run rebuild_research_state_from_runs.py to create research_ledger.jsonl.")
    if not champion.get("best_champion_run_id"):
        lines.append("- Champion governance is empty; rebuild state from runs.")
    if not lines[-1].startswith("- ") or lines[-1] == "## Recommendations":
        lines.append("- Learning loop looks structurally healthy; continue with controlled experiments.")

    report = "\n".join(lines) + "\n"
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "learning_progress.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
