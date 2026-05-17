"""Audit whether autonomous research is learning or repeating itself."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def audit_learning_progress(runs_dir: str | Path = "runs", state_dir: str | Path = "state") -> dict:
    runs = [p for p in Path(runs_dir).glob("*_*") if p.is_dir() and (p.name.startswith("EXP_") or p.name.startswith("AUTO_"))]
    artifact_index = _read_json(Path(state_dir) / "artifact_hash_index.json", {"signatures": {}, "runs": {}})
    memory = _read_json(Path(state_dir) / "hypothesis_memory.json", {"events": []})
    cooldowns = _read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    champions = _read_json(Path(state_dir) / "champion_runs.json", {})
    duplicates = _read_json(Path(state_dir) / "duplicate_runs.json", {"duplicates": []})

    total = len(runs)
    unique = len(artifact_index.get("signatures", {}))
    events = memory.get("events", [])
    hypo_counts = Counter(e.get("hypothesis_id") for e in events if e.get("hypothesis_id"))
    value_by_run = {e.get("run_id"): e.get("value_delivered") for e in events if e.get("run_id")}
    return {
        "total_runs": total,
        "unique_artifact_signatures": unique,
        "duplicate_rate": (total - unique) / total if total else 0.0,
        "runs_with_audit_json": sum(1 for p in runs if (p / "audit.json").exists()),
        "runs_with_parent_run_id": sum(1 for p in runs if _read_json(p / "run_manifest.json", {}).get("parent_run_id")),
        "best_champion": champions.get("best_champion_run_id"),
        "secondary_candidates": champions.get("secondary_candidates", []),
        "axes_exhausted": sorted(k for k, v in cooldowns.get("axes", {}).items() if v.get("status") == "axis_exhausted"),
        "hypotheses_repeated": {k: v for k, v in hypo_counts.items() if v > 1},
        "duplicate_result": len(duplicates.get("duplicates", [])),
        "metric_no_effect": sum(1 for e in events if e.get("precheck_status") == "metric_no_effect"),
        "value_delivered_by_run": value_by_run,
        "recommended_next_actions": sorted(set(e.get("next_action") for e in events if e.get("next_action"))),
        "promoted_to_baseline_candidate_pending_review": [
            e.get("run_id") for e in events if e.get("promoted_to_baseline_candidate") and e.get("manual_review_required", True)
        ],
    }


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit autonomous learning progress.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    args = parser.parse_args()
    print(json.dumps(audit_learning_progress(args.runs_dir, args.state_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
