"""Universal autonomy loop: observe -> classify -> handle -> validate -> retry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomy_handlers import collect_state, classify_blocker, choose_handler, run_handler
from scripts.research.autonomy_readiness import validate_autonomy_readiness

TERMINAL_STATUSES = {"READY_TO_RUN", "NO_SAFE_ACTION", "MANUAL_REVIEW_REQUIRED", "CANDIDATE_FOUND", "RESEARCH_EXHAUSTED"}


def _material_files_changed(files: list[str] | None) -> bool:
    if not files:
        return False
    material_prefixes = (
        "bibliography/",
        "configs/generated/",
        "configs/local_data_paths.json",
        "data/",
        "scripts/generated/",
    )
    material_exact = {"state/data_paths_resolved.json"}
    for item in files:
        path = str(item).replace("\\", "/")
        if path in material_exact or path.startswith(material_prefixes):
            return True
    return False


def orchestrate(
    *,
    state_dir: str | Path,
    runs_dir: str | Path,
    reports_dir: str | Path,
    hypothesis_bank: str | Path,
    paper_ideas: str | Path,
    args: Any,
    max_cycles: int = 5,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    last_signature: tuple[str, str, str] | None = None
    for cycle in range(1, max_cycles + 1):
        state = collect_state(state_dir=state_dir, runs_dir=runs_dir, reports_dir=reports_dir, hypothesis_bank=hypothesis_bank, paper_ideas=paper_ideas)
        classification = classify_blocker(state)
        handler_name = choose_handler(classification)
        handler_result = run_handler(handler_name, state, args)
        validation = validate_autonomy_readiness(
            state_dir=state_dir,
            runs_dir=runs_dir,
            reports_dir=reports_dir,
            hypothesis_bank=hypothesis_bank,
            final_eligibility=handler_result.eligibility_after,
        )
        item = {
            "cycle": cycle,
            "blocker_type": classification.get("blocker_type"),
            "reason": classification.get("reason"),
            "handler": handler_name,
            **handler_result.to_dict(),
            "validation_ok": validation.get("ok"),
            "validation_checks": validation.get("checks"),
        }
        history.append(item)
        signature = (str(item.get("blocker_type")), str(item.get("status")), str(item.get("next_action")))
        if item["status"] in {"READY_TO_RUN", "MANUAL_REVIEW_REQUIRED", "CANDIDATE_FOUND"}:
            return {"status": item["status"], "handler": handler_name, "history": history, "details": item}
        if item["status"] == "NO_SAFE_ACTION":
            material_change = _material_files_changed(item.get("files_changed") or [])
            has_registered_handler = bool(handler_name and handler_name != "unknown")
            source_action = "source" in str(item.get("next_action") or "").lower()
            if cycle < max_cycles and has_registered_handler and (material_change or source_action) and signature != last_signature:
                last_signature = signature
                continue
            return {"status": item["status"], "handler": handler_name, "history": history, "details": item}
        if signature == last_signature:
            return {"status": "NO_SAFE_ACTION", "handler": handler_name, "history": history, "details": {**item, "loop_guard": "same_handler_same_result"}}
        last_signature = signature
    return {"status": "NO_SAFE_ACTION", "handler": history[-1]["handler"] if history else None, "history": history, "details": history[-1] if history else {}}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--policy", default="governance/research_policy.json")
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--max-cycles", type=int, default=5)
    p.add_argument("--max-literature-hypotheses", type=int, default=8)
    p.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = orchestrate(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        args=args,
        max_cycles=int(args.max_cycles),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("status") in TERMINAL_STATUSES else 3


if __name__ == "__main__":
    raise SystemExit(main())
