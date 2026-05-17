from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pathlib import Path

from scripts.research.autonomous import parse_common_args, run_iteration


def main() -> int:
    parser = parse_common_args("Run multiple autonomous research iterations.")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--stop-file", default=None)
    args = parser.parse_args()

    results = []
    for _ in range(int(args.max_iterations)):
        if args.stop_file and Path(args.stop_file).exists():
            break
        results.append(run_iteration(args.state_dir, args.parent_config))

    print(json.dumps({"iterations": len(results), "last": results[-1] if results else None}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
