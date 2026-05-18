from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pathlib import Path

from scripts.research.autonomous import parse_common_args, run_iteration


def iteration_summary(result: dict) -> dict:
    hypothesis = result.get("hypothesis") or {}
    precheck = result.get("precheck") or {}
    evaluation = result.get("evaluation") or {}
    decision = result.get("coordinator_decision") or {}
    execution = result.get("execution") or {}
    return {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "source_ids": hypothesis.get("source_ids", []),
        "precheck_status": precheck.get("status"),
        "run_id": evaluation.get("run_id") or execution.get("run_id"),
        "decision": evaluation.get("champion_decision") or evaluation.get("decision") or decision.get("decision"),
        "reason": decision.get("reason") or evaluation.get("rejection_reason"),
        "next_action": evaluation.get("next_action") or decision.get("decision"),
    }


def main() -> int:
    parser = parse_common_args("Run multiple autonomous research iterations.")
    parser.add_argument("--max-iterations", type=int, default=10, help="0 means run until stop-file exists or interrupted.")
    parser.add_argument("--stop-file", default=None)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--weekly-file", default=None)
    parser.add_argument("--daily-folder", default=None)
    parser.add_argument("--project-config", default="configs/project_config.json")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--parent-strategy-config", default=None)
    parser.add_argument("--generated-config-dir", default="configs/generated")
    args = parser.parse_args()

    results = []
    iteration = 0
    while True:
        if args.stop_file and Path(args.stop_file).exists():
            break
        if int(args.max_iterations) > 0 and iteration >= int(args.max_iterations):
            break
        result = run_iteration(
            args.state_dir,
            args.parent_config,
            mock=bool(args.mock),
            weekly_file=args.weekly_file,
            daily_folder=args.daily_folder,
            project_config=args.project_config,
            runs_dir=args.runs_dir,
            parent_run_id=args.parent_run_id,
            parent_strategy_config=args.parent_strategy_config,
            generated_config_dir=args.generated_config_dir,
        )
        iteration += 1
        results.append(result)
        summary = iteration_summary(result)
        print(json.dumps(summary, ensure_ascii=False, default=str))

    print(json.dumps({"iterations": len(results), "last": results[-1] if results else None}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
