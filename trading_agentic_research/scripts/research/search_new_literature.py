from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomous import parse_common_args
from scripts.research.literature_searcher import search_new_literature


def main() -> int:
    parser = parse_common_args("Search public bibliography APIs for new research sources.")
    parser.add_argument("--max-results", type=int, default=5)
    args = parser.parse_args()
    result = search_new_literature(state_dir=args.state_dir, max_results=int(args.max_results))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
