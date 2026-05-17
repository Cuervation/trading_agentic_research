"""Audit the latest run folder and write audit.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.validation import audit_run_folder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the latest run.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--min-trades", type=int, default=10)
    return parser.parse_args()


def find_latest_run(runs_dir: Path) -> Path:
    candidates = [p for p in runs_dir.glob("EXP_*") if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run folders found in {runs_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def get_parent_run_id(state_dir: Path) -> str | None:
    parent_path = state_dir / "current_parent.json"
    if not parent_path.exists():
        return None
    payload = json.loads(parent_path.read_text(encoding="utf-8-sig"))
    run_id = payload.get("current_parent_run_id")
    return str(run_id) if run_id else None


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    state_dir = Path(args.state_dir)

    latest = find_latest_run(runs_dir)
    parent_run_id = get_parent_run_id(state_dir)
    parent_dir = (runs_dir / parent_run_id) if parent_run_id and parent_run_id != latest.name else None

    audit = audit_run_folder(latest, min_trades=args.min_trades, parent_run_dir=parent_dir)
    audit_path = latest / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")

    print(f"Audited latest run: {latest.name}")
    print(f"Decision: {audit['decision']}")
    print(f"Audit file: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
