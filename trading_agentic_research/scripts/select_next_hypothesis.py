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
    prefer_unseen: bool = True,
) -> dict:
    """Choose the best next hypothesis with deterministic rules (no random)."""

    candidates = []
    for hypothesis in hypothesis_bank:
        status = str(hypothesis.get("status", "candidate"))
        if status not in {"candidate", "seeded"}:
            continue

        hypothesis_id = str(hypothesis.get("hypothesis_id"))
        if hypothesis_id in rejected_ids:
            continue

        score = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)
        if score.get("decision") == "rejected":
            continue

        empirical_count = len(hypothesis.get("empirical_basis", []) or [])
        bibliographic_count = len(hypothesis.get("bibliography_basis", []) or [])

        is_unseen = hypothesis_id not in accepted_ids

        candidates.append(
            (
                # Prefer unseen hypotheses first, if enabled.
                0 if (prefer_unseen and is_unseen) else 1,
                # Prefer hypotheses with empirical basis.
                -empirical_count,
                # Prefer fewer prior rejections in this family.
                score.get("prior_rejections", 0),
                # Prefer more prior acceptances.
                -score.get("prior_acceptances", 0),
                # Prefer stronger bibliographic grounding.
                -bibliographic_count,
                # Stable tie-break.
                hypothesis_id,
                hypothesis,
            )
        )

    if not candidates:
        raise ValueError("No eligible hypotheses found (all rejected/cooldown/invalid).")

    candidates.sort()
    return candidates[0][-1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Select the next hypothesis from the bank.")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--prefer-unseen", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir)

    learning_memory = read_json(state_dir / "learning_memory.json")
    cooldowns = read_json(state_dir / "subspace_cooldowns.json")

    bank = load_hypothesis_bank(args.hypothesis_bank)
    rejected_ids = rejected_hypothesis_ids(state_dir)
    accepted_ids = accepted_hypothesis_ids(state_dir)

    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory=learning_memory,
        cooldowns=cooldowns,
        rejected_ids=rejected_ids,
        accepted_ids=accepted_ids,
        prefer_unseen=bool(args.prefer_unseen),
    )

    print(json.dumps(selected, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
