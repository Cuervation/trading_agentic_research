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
    args = parser.parse_args()
    result = run_iteration(args.state_dir, args.parent_config)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
