from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from scripts.research.autonomous import parse_common_args, seed_literature_sources


def main() -> int:
    parser = parse_common_args("Initialize local bibliography seed.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    payload = seed_literature_sources(args.state_dir, overwrite=bool(args.overwrite))
    print(json.dumps({"sources": len(payload.get("sources", [])), "state_dir": args.state_dir}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
