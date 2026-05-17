"""Generate analysis.json and analysis.md for all EXP_* runs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_run import build_analysis, render_analysis_md


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze all run folders.")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--state-dir", default="state")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    state_dir = Path(args.state_dir)

    count = 0
    for run_dir in sorted(runs_dir.glob("EXP_*")):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        analysis = build_analysis(run_id, runs_dir, state_dir)
        (run_dir / "analysis.json").write_text(
            __import__("json").dumps(analysis, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "analysis.md").write_text(render_analysis_md(analysis), encoding="utf-8")
        count += 1

    print(f"Analyzed runs: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
