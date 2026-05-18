"""Apply small in-place edits for manual parent governance.

Run from the repository root after extracting this patch:

    python .\tools\apply_manual_parent_governance_patch.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_wrapper() -> str:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    old = """prefer_best_champion=True,\n        repo_root=ROOT,"""
    new = """prefer_best_champion=bool(args.allow_parent_update),\n        allow_parent_promotion=bool(args.allow_parent_update),\n        repo_root=ROOT,"""
    ok = replace_once(path, old, new)
    return "patched" if ok else "already_patched_or_pattern_not_found"


def patch_candidate_under_review() -> str:
    path = ROOT / "scripts" / "research" / "candidate_under_review.py"
    text = path.read_text(encoding="utf-8-sig")
    replacement = r'''def _candidate_from_champion_state(state_dir: str | Path) -> str | None:
    """Return the strongest candidate that still requires manual review.

    Priority:
    1. pending_parent_candidate_run_id / best_champion_run_id when it differs
       from the official current_parent_run_id. This catches cases like EXP_054:
       a new best champion was found, but parent movement remains blocked.
    2. baseline_candidate_run_id when it differs from current parent.
    3. promotion_candidates sorted by robust score/order stored by governance.
    4. aggressive candidate only as a last resort.
    """
    champion = load_champion_state(state_dir)
    current_parent = champion.get("current_parent_run_id")

    for key in ("pending_parent_candidate_run_id", "best_champion_run_id", "baseline_candidate_run_id"):
        candidate = champion.get(key)
        if candidate and str(candidate) != str(current_parent):
            return str(candidate)

    for bucket in ("promotion_candidates", "secondary_candidates"):
        for row in champion.get(bucket, []) or []:
            candidate = row.get("run_id")
            if candidate and str(candidate) != str(current_parent):
                return str(candidate)

    aggressive = champion.get("aggressive_champion_run_id")
    if aggressive and str(aggressive) != str(current_parent):
        return str(aggressive)
    return None


'''
    pattern = r"def _candidate_from_champion_state\(state_dir: str \| Path\) -> str \| None:\n.*?\n\ndef refresh_candidate_under_review"
    new_text, count = re.subn(pattern, replacement + "def refresh_candidate_under_review", text, count=1, flags=re.S)
    if count == 0:
        return "already_patched_or_pattern_not_found"
    path.write_text(new_text, encoding="utf-8")
    return "patched"


def main() -> int:
    results = {
        "wrapper": patch_wrapper(),
        "candidate_under_review": patch_candidate_under_review(),
        "note": "parent_state.py is replaced by extracting this patch; run manual_parent_governance.py to repair state if needed.",
    }
    import json
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
