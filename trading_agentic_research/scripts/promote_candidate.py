"""Manual-only baseline promotion for audited promoted candidates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def promote_candidate_to_baseline(
    *,
    state_dir: str | Path,
    runs_dir: str | Path,
    run_id: str,
    confirm_manual_review: bool,
) -> dict:
    if not confirm_manual_review:
        raise ValueError("Manual review confirmation is required to promote a baseline.")

    run_dir = Path(runs_dir) / run_id
    audit_path = run_dir / "audit.json"
    manifest_path = run_dir / "run_manifest.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"Missing audit.json: {audit_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing run_manifest.json: {manifest_path}")

    audit = read_json(audit_path)
    if audit.get("decision") != "promoted_candidate":
        raise ValueError(f"Only promoted_candidate can be manually promoted, got: {audit.get('decision')}")
    if audit.get("blocking_issues"):
        raise ValueError("Cannot promote candidate with blocking issues.")

    manifest = read_json(manifest_path)
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    baseline_path = state_path / "current_baseline.json"
    previous = read_json(baseline_path) if baseline_path.exists() else {}

    payload = {
        "baseline_run_id": run_id,
        "baseline_strategy_id": manifest.get("strategy_id"),
        "baseline_hypothesis_id": manifest.get("hypothesis_id"),
        "previous_baseline_run_id": previous.get("baseline_run_id") or previous.get("current_baseline_run_id"),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by": "manual_review",
        "source": "scripts/promote_candidate.py",
    }
    baseline_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manually promote an audited candidate to baseline.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--confirm-manual-review", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = promote_candidate_to_baseline(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        run_id=args.run_id,
        confirm_manual_review=bool(args.confirm_manual_review),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
