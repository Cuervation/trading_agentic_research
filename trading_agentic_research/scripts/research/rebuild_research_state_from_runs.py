"""Rebuild autonomous research state from historical EXP_* and AUTO_* runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.artifact_index import rebuild_artifact_index_from_runs, write_json
from scripts.research.champion_governance import rebuild_champion_state_from_runs, run_metrics


def rebuild_research_state_from_runs(runs_dir: str | Path = "runs", state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict:
    runs_path = Path(runs_dir)
    state_path = Path(state_dir)
    report_path = Path(reports_dir) / "rebuilt_research_state.md"

    artifact_result = rebuild_artifact_index_from_runs(runs_path, state_path)
    champion_state = rebuild_champion_state_from_runs(runs_path, state_path)
    duplicates = artifact_result["duplicates"]
    run_dirs = sorted([p for p in runs_path.glob("*_*") if p.is_dir() and (p.name.startswith("EXP_") or p.name.startswith("AUTO_"))])

    memory_events = []
    hypotheses = {}
    axis_counts = defaultdict(Counter)
    for run_dir in run_dirs:
        manifest = _read_json(run_dir / "run_manifest.json", {})
        audit = _read_json(run_dir / "audit.json", {})
        duplicate = next((d for d in duplicates if d["run_id"] == run_dir.name), None)
        family = manifest.get("hypothesis_family", "unknown")
        axis = manifest.get("axis") or manifest.get("strategy_family") or family
        decision = "duplicate_result" if duplicate else audit.get("decision", "rebuilt")
        value = "duplicate_blocked" if duplicate else _value_from_run(run_dir.name, champion_state, decision)
        event = {
            "event_id": f"REBUILT_{len(memory_events) + 1:06d}",
            "run_id": run_dir.name,
            "hypothesis_id": manifest.get("hypothesis_id") or manifest.get("strategy_id"),
            "source_ids": [b.get("source_id") for b in manifest.get("bibliography_basis", []) if isinstance(b, dict)],
            "family": family,
            "axis": axis,
            "parent_run_id": manifest.get("parent_run_id"),
            "precheck_status": "duplicate_result" if duplicate else "unknown_rebuilt",
            "decision": decision,
            "value_delivered": value,
            "learned": _learning_sentence(decision, value, duplicate),
            "next_action": _next_action(value),
            "duplicate_of_run_id": duplicate.get("duplicate_of_run_id") if duplicate else None,
            "can_repeat": False if duplicate else value in {"new_champion", "secondary_candidate"},
            "execution_mode": "real",
            "backtest_real": True,
        }
        memory_events.append(event)
        axis_counts[f"{family}:{axis}"][event["precheck_status"]] += 1
        if event["hypothesis_id"]:
            hypotheses.setdefault(event["hypothesis_id"], {"hypothesis_id": event["hypothesis_id"], "source_ids": event["source_ids"], "family": family, "axis": axis})

    cooldowns = {"version": 1, "axes": {}, "axis_rejection_threshold": 3}
    for key, counts in axis_counts.items():
        if counts["duplicate_result"] >= 3:
            cooldowns["axes"][key] = {"status": "axis_exhausted", "reason": "three_duplicate_results", "duplicate_result": counts["duplicate_result"]}

    duplicate_payload = {"version": 1, "duplicates": duplicates}
    memory_payload = {"version": 1, "hypotheses": list(hypotheses.values()), "events": memory_events}
    write_json(state_path / "duplicate_runs.json", duplicate_payload)
    write_json(state_path / "hypothesis_memory.json", memory_payload)
    write_json(state_path / "axis_cooldowns.json", cooldowns)

    report = _build_report(run_dirs, artifact_result, champion_state, cooldowns)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "runs": len(run_dirs),
        "unique_artifact_signatures": len(artifact_result["index"].get("signatures", {})),
        "duplicates": len(duplicates),
        "best_champion_run_id": champion_state.get("best_champion_run_id"),
        "secondary_candidates": champion_state.get("secondary_candidates", []),
        "aggressive_champion_run_id": champion_state.get("aggressive_champion_run_id"),
        "report": str(report_path),
    }


def _value_from_run(run_id: str, champion_state: dict, decision: str) -> str:
    if run_id == champion_state.get("best_champion_run_id"):
        return "new_champion"
    if run_id in set(champion_state.get("secondary_candidates", [])):
        return "secondary_candidate"
    if decision in {"rejected", "metric_no_effect"}:
        return "rejected_with_learning"
    return "rejected_with_learning"


def _learning_sentence(decision: str, value: str, duplicate: dict | None) -> str:
    if duplicate:
        return f"Artifacts duplicate historical run {duplicate.get('duplicate_of_run_id')}; block repeat."
    if value == "new_champion":
        return "Run has the best balance of CAGR, drawdown and years versus SPY."
    if value == "secondary_candidate":
        return "Run improved at least one useful axis but did not beat the champion balance."
    return f"Run rebuilt from artifacts with decision={decision}; keep as learning evidence."


def _next_action(value: str) -> str:
    if value == "duplicate_blocked":
        return "change_axis_or_literature"
    if value == "new_champion":
        return "manual_review_candidate"
    if value == "secondary_candidate":
        return "refine_different_axis"
    return "search_or_mix_new_literature"


def _build_report(run_dirs: list[Path], artifact_result: dict, champion_state: dict, cooldowns: dict) -> str:
    duplicate_count = len(artifact_result["duplicates"])
    total = len(run_dirs)
    return "\n".join(
        [
            "# Rebuilt Research State",
            "",
            f"- Total runs: {total}",
            f"- Unique artifact signatures: {len(artifact_result['index'].get('signatures', {}))}",
            f"- Duplicate runs: {duplicate_count}",
            f"- Duplicate rate: {(duplicate_count / total * 100.0) if total else 0:.2f}%",
            f"- Recommended best_champion_run_id: {champion_state.get('best_champion_run_id')}",
            f"- Recommended secondary_candidates: {', '.join(champion_state.get('secondary_candidates', []))}",
            f"- Recommended aggressive_champion_run_id: {champion_state.get('aggressive_champion_run_id')}",
            f"- Axes exhausted: {', '.join(cooldowns.get('axes', {}).keys()) or 'none'}",
            "",
            "Baseline promotion remains manual-only.",
        ]
    )


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild research state from EXP_* and AUTO_* runs.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()
    result = rebuild_research_state_from_runs(args.runs_dir, args.state_dir, args.reports_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
