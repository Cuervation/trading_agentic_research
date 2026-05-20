"""Universal autonomy loop: observe -> classify -> handle -> validate -> retry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomy_handlers import collect_state, classify_blocker, run_handler
from scripts.research.autonomy_readiness import validate_autonomy_readiness
from scripts.research.autonomy_recovery_policy import get_recovery_policy

TERMINAL_STATUSES = {"READY_TO_RUN", "NO_SAFE_ACTION", "MANUAL_REVIEW_REQUIRED", "CANDIDATE_FOUND", "RESEARCH_EXHAUSTED"}


def _material_files_changed(files: list[str] | None) -> bool:
    if not files:
        return False
    material_prefixes = (
        "bibliography/",
        "configs/generated/",
        "configs/local_data_paths.json",
        "data/",
        "runs/",
        "scripts/generated/",
    )
    material_exact = {
        "state/artifact_hash_index.json",
        "state/data_paths_resolved.json",
        "state/semantic_branch_exhaustion.json",
        "state/strategy_effect_index.json",
        "state/research_ledger.jsonl",
    }
    for item in files:
        path = str(item).replace("\\", "/")
        if path in material_exact or path.startswith(material_prefixes):
            return True
    return False


def _no_safe_specificity(item: dict[str, Any]) -> int:
    """Prefer actionable NO_SAFE_ACTION details over a generic final eligibility pass."""
    score = 0
    next_action = str(item.get("next_action") or "").lower()
    nested = item.get("details") if isinstance(item.get("details"), dict) else {}
    executor = nested.get("executor") if isinstance(nested.get("executor"), dict) else {}
    if executor.get("blocker_type") or nested.get("blocker_type"):
        score += 5
    if any(token in next_action for token in ("new non-duplicate", "source", "feature", "template", "external data")):
        score += 3
    if "no eligible hypotheses found" in next_action:
        score -= 3
    if item.get("handler") == "hypothesis_eligibility":
        score -= 1
    return score


def orchestrate(
    *,
    state_dir: str | Path,
    runs_dir: str | Path,
    reports_dir: str | Path,
    hypothesis_bank: str | Path,
    paper_ideas: str | Path,
    args: Any,
    max_cycles: int = 5,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    attempts: dict[tuple[str, str], int] = {}
    repeated_blockers: dict[tuple[str, str], int] = {}
    last_item: dict[str, Any] = {}
    best_no_safe_item: dict[str, Any] = {}
    last_no_material_blocker: str | None = None

    for cycle in range(1, max_cycles + 1):
        state = collect_state(state_dir=state_dir, runs_dir=runs_dir, reports_dir=reports_dir, hypothesis_bank=hypothesis_bank, paper_ideas=paper_ideas)
        classification = classify_blocker(state)
        blocker_type = str(classification.get("blocker_type") or "unknown_blocker")
        policy = get_recovery_policy(blocker_type)
        handlers = list(policy.get("handlers_ordered") or [])
        max_attempts = int(policy.get("max_attempts") or 1)
        material_this_cycle = False
        ran_handler = False
        exhausted_handlers: list[str] = []

        if not handlers:
            handlers = ["hypothesis_eligibility"]

        if (
            last_no_material_blocker == blocker_type
            and all(attempts.get((blocker_type, handler), 0) >= 1 for handler in handlers)
        ):
            return {
                "status": "NO_SAFE_ACTION",
                "handler": (best_no_safe_item or last_item).get("handler") if (best_no_safe_item or last_item) else None,
                "history": history,
                "details": {
                    **(best_no_safe_item or last_item or {}),
                    "loop_guard": "same_blocker_reobserved_after_all_handlers_without_material_mutation",
                    "repeat_count": 2,
                    "terminal_only_if": policy.get("terminal_only_if"),
                },
            }

        for handler_name in handlers:
            key = (blocker_type, handler_name)
            if attempts.get(key, 0) >= max_attempts:
                exhausted_handlers.append(handler_name)
                continue
            attempts[key] = attempts.get(key, 0) + 1
            ran_handler = True

            state_before = state
            before_type = blocker_type
            handler_result = run_handler(handler_name, state_before, args)
            validation = validate_autonomy_readiness(
                state_dir=state_dir,
                runs_dir=runs_dir,
                reports_dir=reports_dir,
                hypothesis_bank=hypothesis_bank,
                final_eligibility=handler_result.eligibility_after,
            )
            state_after = collect_state(state_dir=state_dir, runs_dir=runs_dir, reports_dir=reports_dir, hypothesis_bank=hypothesis_bank, paper_ideas=paper_ideas)
            classification_after = classify_blocker(state_after)
            after_type = str(classification_after.get("blocker_type") or "unknown_blocker")
            blocker_changed = after_type != before_type
            material_change = _material_files_changed(handler_result.files_changed) or blocker_changed
            material_this_cycle = material_this_cycle or material_change

            item = {
                "cycle": cycle,
                "attempt": attempts[key],
                "blocker_type": blocker_type,
                "reason": classification.get("reason"),
                "handler": handler_name,
                "policy": policy,
                **handler_result.to_dict(),
                "material_mutation": material_change,
                "blocker_changed_to": after_type if blocker_changed else None,
                "validation_ok": validation.get("ok"),
                "validation_checks": validation.get("checks"),
            }
            history.append(item)
            last_item = item
            if item.get("status") == "NO_SAFE_ACTION" and (
                not best_no_safe_item or _no_safe_specificity(item) >= _no_safe_specificity(best_no_safe_item)
            ):
                best_no_safe_item = item

            if item["status"] in {"READY_TO_RUN", "MANUAL_REVIEW_REQUIRED", "CANDIDATE_FOUND"}:
                return {"status": item["status"], "handler": handler_name, "history": history, "details": item}

            if blocker_changed:
                # Re-observe before choosing the next policy.  This is what lets a
                # generic blocker become a specific external-data/governance/etc.
                break

            state = state_after

        if not ran_handler:
            return {
                "status": "NO_SAFE_ACTION",
                "handler": (best_no_safe_item or last_item).get("handler") if (best_no_safe_item or last_item) else None,
                "history": history,
                "details": {
                    **(best_no_safe_item or last_item or {}),
                    "loop_guard": "all_policy_handlers_exhausted",
                    "exhausted_handlers": exhausted_handlers,
                    "terminal_only_if": policy.get("terminal_only_if"),
                },
            }

        next_action = str((last_item or {}).get("next_action") or "")
        repeat_key = (blocker_type, next_action)
        repeated_blockers[repeat_key] = repeated_blockers.get(repeat_key, 0) + 1
        remaining_safe_handlers = any(
            attempts.get((blocker_type, handler), 0) < max_attempts
            for handler in handlers
        )

        if material_this_cycle and cycle < max_cycles:
            last_no_material_blocker = None
            continue
        if not material_this_cycle:
            last_no_material_blocker = blocker_type

        if not remaining_safe_handlers or repeated_blockers[repeat_key] >= 2:
            return {
                "status": "NO_SAFE_ACTION",
                "handler": (best_no_safe_item or last_item).get("handler") if (best_no_safe_item or last_item) else None,
                "history": history,
                "details": {
                    **(best_no_safe_item or last_item or {}),
                    "loop_guard": "safe_handlers_exhausted_or_repeated_blocker",
                    "remaining_safe_handlers": remaining_safe_handlers,
                    "repeat_count": repeated_blockers[repeat_key],
                    "terminal_only_if": policy.get("terminal_only_if"),
                },
            }

    return {
        "status": "NO_SAFE_ACTION",
        "handler": (best_no_safe_item or last_item).get("handler") if (best_no_safe_item or last_item) else None,
        "history": history,
        "details": {
            **(best_no_safe_item or last_item or {}),
            "loop_guard": "max_cycles_exhausted",
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--policy", default="governance/research_policy.json")
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--max-cycles", type=int, default=5)
    p.add_argument("--max-literature-hypotheses", type=int, default=8)
    p.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = orchestrate(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        args=args,
        max_cycles=int(args.max_cycles),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("status") in TERMINAL_STATUSES else 3


if __name__ == "__main__":
    raise SystemExit(main())
