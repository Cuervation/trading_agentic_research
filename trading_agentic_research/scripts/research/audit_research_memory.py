from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from scripts.research.autonomous import audit_memory, parse_common_args


def main() -> int:
    parser = parse_common_args("Audit autonomous research memory.")
    args = parser.parse_args()
    print(json.dumps(audit_memory(args.state_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
