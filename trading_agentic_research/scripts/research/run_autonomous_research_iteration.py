from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from scripts.research.autonomous import parse_common_args, run_iteration


def main() -> int:
    parser = parse_common_args("Run one bibliography-driven autonomous research iteration.")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--weekly-file", default=None)
    parser.add_argument("--daily-folder", default=None)
    parser.add_argument("--project-config", default="configs/project_config.json")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--parent-strategy-config", default=None)
    parser.add_argument("--generated-config-dir", default="configs/generated")
    args = parser.parse_args()
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
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
