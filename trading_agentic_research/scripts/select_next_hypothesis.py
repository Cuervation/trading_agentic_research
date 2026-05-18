"""Select the next hypothesis to evaluate (non-random, memory-aware)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_hypotheses_from_bibliography import validate_candidate_basis
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.parameter_effect_memory import load_parameter_effect_memory, score_hypothesis_axis
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_hypothesis_bank(path: str | Path) -> list[dict]:
    hypotheses = read_jsonl(path)
    for h in hypotheses:
        validate_candidate_basis(h)
    return hypotheses


def rejected_hypothesis_ids(state_dir: str | Path) -> set[str]:
    rejected = read_jsonl(Path(state_dir) / "rejected_hypotheses.jsonl")
    return {str(row.get("hypothesis_id")) for row in rejected if row.get("hypothesis_id")}


def accepted_hypothesis_ids(state_dir: str | Path) -> set[str]:
    accepted = read_jsonl(Path(state_dir) / "accepted_hypotheses.jsonl")
    return {str(row.get("hypothesis_id")) for row in accepted if row.get("hypothesis_id")}


def choose_next_hypothesis(
    *,
    hypothesis_bank: list[dict],
    learning_memory: dict,
    cooldowns: dict,
    rejected_ids: set[str],
    accepted_ids: set[str],
    current_parent_hypothesis_id: str | None = None,
    parameter_effect_memory: dict | None = None,
    prefer_unseen: bool = True,
    consumed_ids: set[str] | None = None,
    allow_retry_consumed: bool = False,
) -> dict:
    """Choose the best next hypothesis with deterministic rules.

    Production autonomous runs must not execute the same exact hypothesis twice.
    When prefer_unseen is true, accepted ids are treated as consumed, not merely
    lower priority. This avoids repeated runs like TOPN_10 -> duplicate_result.
    """
    if consumed_ids is None:
        # Backward-compatible safety for callers that have not yet been patched
        # to pass consumed ids explicitly. Most autonomous runs use ./state.
        try:
            consumed_ids = consumed_hypothesis_ids(ROOT / "state")
        except Exception:
            consumed_ids = set()
    consumed_ids = {str(x) for x in (consumed_ids or set()) if x}
    rejected_ids = {str(x) for x in (rejected_ids or set()) if x}
    accepted_ids = {str(x) for x in (accepted_ids or set()) if x}

    candidates = []
    for hypothesis in hypothesis_bank:
        status = str(hypothesis.get("status", "candidate"))
        if status not in {"candidate", "seeded"}:
            continue

        hypothesis_id = str(hypothesis.get("hypothesis_id"))
        if hypothesis_id in rejected_ids:
            continue
        if current_parent_hypothesis_id and hypothesis_id == current_parent_hypothesis_id:
            continue
        if not allow_retry_consumed and hypothesis_id in consumed_ids:
            continue
        # Stronger than the old behavior: if it has already been accepted/run,
        # don't re-run it during unseen autonomous selection.
        if prefer_unseen and not allow_retry_consumed and hypothesis_id in accepted_ids:
            continue

        score = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)
        if score.get("decision") == "rejected":
            continue

        empirical_count = len(hypothesis.get("empirical_basis", []) or [])
        bibliographic_count = len(hypothesis.get("bibliography_basis", []) or [])
        axis_score = score_hypothesis_axis(hypothesis, parameter_effect_memory or {})
        is_unseen = hypothesis_id not in accepted_ids and hypothesis_id not in consumed_ids

        candidates.append(
            (
                0 if (prefer_unseen and is_unseen) else 1,
                -empirical_count,
                score.get("prior_rejections", 0),
                -score.get("prior_acceptances", 0),
                -axis_score,
                -bibliographic_count,
                hypothesis_id,
                hypothesis,
            )
        )

    if not candidates:
        raise ValueError("No eligible hypotheses found (all rejected/cooldown/invalid/consumed).")

    candidates.sort()
    return candidates[0][-1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Select the next hypothesis from the bank.")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--prefer-unseen", action="store_true")
    p.add_argument("--allow-retry-consumed", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir)

    learning_memory = read_json(state_dir / "learning_memory.json")
    cooldowns = read_json(state_dir / "subspace_cooldowns.json")
    current_parent = read_json(state_dir / "current_parent.json")
    parameter_effect_memory = load_parameter_effect_memory(state_dir / "parameter_effect_memory.json")

    bank = load_hypothesis_bank(args.hypothesis_bank)
    rejected_ids = rejected_hypothesis_ids(state_dir)
    accepted_ids = accepted_hypothesis_ids(state_dir)
    consumed_ids = consumed_hypothesis_ids(state_dir)

    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory=learning_memory,
        cooldowns=cooldowns,
        rejected_ids=rejected_ids,
        accepted_ids=accepted_ids,
        consumed_ids=consumed_ids,
        allow_retry_consumed=bool(args.allow_retry_consumed),
        parameter_effect_memory=parameter_effect_memory,
        current_parent_hypothesis_id=str(current_parent.get("current_parent_strategy_id")) if current_parent.get("current_parent_strategy_id") else None,
        prefer_unseen=bool(args.prefer_unseen),
    )

    print(json.dumps(selected, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
