"""Eligibility preflight for autonomous research batches."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.select_next_hypothesis import choose_next_hypothesis, load_hypothesis_bank, read_json, read_jsonl
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids


def _repeat_blocked_hypothesis_ids(history: list[dict[str, Any]], max_repeats_per_hypothesis: int) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def eligible_hypothesis_preflight(
    *,
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    prefer_unseen: bool = True,
    max_repeats_per_hypothesis: int = 1,
) -> dict[str, Any]:
    state_path = Path(state_dir)
    bank = load_hypothesis_bank(hypothesis_bank)
    learning = read_json(state_path / "learning_memory.json") if (state_path / "learning_memory.json").exists() else {}
    cooldowns = read_json(state_path / "subspace_cooldowns.json") if (state_path / "subspace_cooldowns.json").exists() else {}
    current_parent = read_json(state_path / "current_parent.json") if (state_path / "current_parent.json").exists() else {}
    parameter_effect_memory = load_parameter_effect_memory(state_path / "parameter_effect_memory.json")
    rejected_ids = {row.get("hypothesis_id") for row in read_jsonl(state_path / "rejected_hypotheses.jsonl")}
    accepted_ids = {row.get("hypothesis_id") for row in read_jsonl(state_path / "accepted_hypotheses.jsonl")}
    consumed_ids = consumed_hypothesis_ids(state_path)
    batch_state = read_json(state_path / "batch_state.json") if (state_path / "batch_state.json").exists() else {}
    repeat_blocked = _repeat_blocked_hypothesis_ids(batch_state.get("history", []) or [], max_repeats_per_hypothesis)

    try:
        hypothesis = choose_next_hypothesis(
            hypothesis_bank=bank,
            learning_memory=learning,
            cooldowns=cooldowns,
            rejected_ids={str(x) for x in rejected_ids if x}.union(repeat_blocked),
            accepted_ids={str(x) for x in accepted_ids if x},
            consumed_ids=consumed_ids,
            parameter_effect_memory=parameter_effect_memory,
            current_parent_hypothesis_id=str(
                current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id") or ""
            ) or None,
            prefer_unseen=prefer_unseen,
        )
        return {
            "eligible": True,
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "family": hypothesis.get("family"),
            "reason": "selector_found_eligible_hypothesis",
            "consumed_count": len(consumed_ids),
        }
    except Exception as exc:
        return {
            "eligible": False,
            "reason": str(exc),
            "bank_size": len(bank),
            "rejected_count": len({str(x) for x in rejected_ids if x}),
            "accepted_count": len({str(x) for x in accepted_ids if x}),
            "consumed_count": len(consumed_ids),
            "repeat_blocked_count": len(repeat_blocked),
        }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Check whether a research hypothesis is currently selectable.")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    args = p.parse_args()
    print(json.dumps(eligible_hypothesis_preflight(
        hypothesis_bank=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_repeats_per_hypothesis=args.max_repeats_per_hypothesis,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
