"""Synchronize current_parent.json with champion_runs.json.

Run from repo root:
  python scripts/research/sync_parent_state.py --state-dir state --strategy-registry configs/strategy_registry.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.parent_state import sync_current_parent_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync current_parent.json from champion governance state.")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    parser.add_argument("--generated-configs-dir", default="configs/generated")
    parser.add_argument("--preserve-current-parent", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = sync_current_parent_state(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        prefer_best_champion=not bool(args.preserve_current_parent),
        repo_root=ROOT,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
