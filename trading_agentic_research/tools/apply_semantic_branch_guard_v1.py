from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def copy_payload(repo: Path, package_root: Path) -> None:
    payload = package_root / "payload"
    for src in payload.rglob("*"):
        if not src.is_file():
            continue
        dst = repo / src.relative_to(payload)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def patch_pre_run_duplicate_guard(repo: Path) -> None:
    path = repo / "scripts" / "research" / "pre_run_duplicate_guard.py"
    text = read(path)
    import_line = "from scripts.research.semantic_branch_guard import check_semantic_branch_block, record_semantic_pre_run_block\n"
    if import_line not in text:
        anchor = "from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature_from_path\n"
        if anchor not in text:
            raise RuntimeError("pre_run_duplicate_guard.py import anchor not found")
        text = text.replace(anchor, anchor + import_line)

    marker = "# SEMANTIC_BRANCH_GUARD_V1"
    if marker not in text:
        anchor = '    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")\n'
        block = '''    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
    # SEMANTIC_BRANCH_GUARD_V1
    semantic = check_semantic_branch_block(
        hypothesis_id=hypothesis_id or info.get("hypothesis_id"),
        family=family or info.get("strategy_family"),
        state_dir=state_dir,
        runs_dir=runs_dir,
        refresh=True,
    )
    if semantic.get("blocked"):
        record_semantic_pre_run_block(
            state_dir=state_dir,
            run_id=run_id,
            hypothesis_id=hypothesis_id or info.get("hypothesis_id"),
            family=family or info.get("strategy_family"),
            branch=str(semantic.get("branch")),
            reason=str(semantic.get("reason")),
        )
        examples = (semantic.get("details") or {}).get("recent_events") or []
        duplicate_of = None
        for event in reversed(examples):
            if event.get("duplicate_of_run_id"):
                duplicate_of = event.get("duplicate_of_run_id")
                break
            if event.get("run_id"):
                duplicate_of = event.get("run_id")
        return {
            "blocked": True,
            "reason": "semantic_branch_exhausted",
            "duplicate_of_run_id": duplicate_of,
            "existing_runs": [e.get("run_id") for e in examples if e.get("run_id")],
            "candidate": info,
            "hypothesis_id": hypothesis_id,
            "family": family,
            "semantic_branch": semantic,
        }
'''
        if anchor not in text:
            raise RuntimeError("pre_run_duplicate_guard.py signature anchor not found")
        text = text.replace(anchor, block)

    # Make blocked-run summary more honest for semantic branch blocks.
    old = '    (run_dir/"summary.md").write_text(f"# Pre-run duplicate blocked\\n\\nDuplicate of: `{dup}`\\n\\nReason: `{guard_result.get(\'reason\')}`\\n", encoding="utf-8")\n'
    new = '''    if guard_result.get("reason") == "semantic_branch_exhausted":
        summary = (
            "# Pre-run semantic branch blocked\\n\\n"
            f"Branch: `{(guard_result.get('semantic_branch') or {}).get('branch')}`\\n\\n"
            f"Reason: `{(guard_result.get('semantic_branch') or {}).get('reason')}`\\n\\n"
            f"Reference run: `{dup}`\\n"
        )
    else:
        summary = f"# Pre-run duplicate blocked\\n\\nDuplicate of: `{dup}`\\n\\nReason: `{guard_result.get('reason')}`\\n"
    (run_dir/"summary.md").write_text(summary, encoding="utf-8")
'''
    if old in text:
        text = text.replace(old, new)

    write(path, text)


def patch_evaluate_candidate(repo: Path) -> None:
    path = repo / "scripts" / "evaluate_candidate.py"
    text = read(path)
    import_line = "from scripts.research.semantic_branch_guard import refresh_semantic_branch_exhaustion\n"
    if import_line not in text:
        anchor = "from scripts.research.candidate_review_learning import update_candidate_review_learning_from_run\n"
        if anchor not in text:
            raise RuntimeError("evaluate_candidate.py import anchor not found")
        text = text.replace(anchor, anchor + import_line)

    marker = "SEMANTIC_BRANCH_GUARD_V1_REFRESH"
    if marker not in text:
        anchor = '''    candidate_review_learning = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
    )
'''
        block = anchor + '''
    # SEMANTIC_BRANCH_GUARD_V1_REFRESH
    semantic_branch_state = refresh_semantic_branch_exhaustion(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
    )
'''
        if anchor not in text:
            raise RuntimeError("evaluate_candidate.py candidate_review anchor not found")
        text = text.replace(anchor, block)

    if 'print(f"Semantic branch exhausted: {sum(1 for b in semantic_branch_state.get(\'branches\', {}).values() if b.get(\'status\') == \'exhausted\')}")' not in text:
        anchor = '    print(f"Candidate-review learning: {candidate_review_learning.get(\'reason\') or candidate_review_learning.get(\'exhausted_axes\') or candidate_review_learning.get(\'updated\')}")\n'
        insert = anchor + '    print(f"Semantic branch exhausted: {sum(1 for b in semantic_branch_state.get(\'branches\', {}).values() if b.get(\'status\') == \'exhausted\')}")\n'
        if anchor not in text:
            raise RuntimeError("evaluate_candidate.py print anchor not found")
        text = text.replace(anchor, insert)

    write(path, text)


def patch_feature_space_factory(repo: Path) -> None:
    path = repo / "scripts" / "research" / "feature_space_expansion_factory.py"
    text = read(path)
    import_line = "from scripts.research.semantic_branch_guard import refresh_semantic_branch_exhaustion, semantic_branch_status\n"
    if import_line not in text:
        anchor = "from scripts.research.cooldown_governance import hard_active_cooldown_families\n"
        if anchor not in text:
            raise RuntimeError("feature_space_expansion_factory.py import anchor not found")
        text = text.replace(anchor, anchor + import_line)

    marker = "SEMANTIC_BRANCH_GUARD_V1_GENERATOR_REFRESH"
    if marker not in text:
        anchor = "    skipped: list[dict[str, Any]] = []\n    layers: list[str] = []\n"
        block = "    skipped: list[dict[str, Any]] = []\n    layers: list[str] = []\n    # SEMANTIC_BRANCH_GUARD_V1_GENERATOR_REFRESH\n    refresh_semantic_branch_exhaustion(state_dir=state_dir, runs_dir=Path(state_dir).parent / 'runs')\n"
        if anchor not in text:
            raise RuntimeError("feature_space_expansion_factory.py rows/layers anchor not found")
        text = text.replace(anchor, block)

    marker = "SEMANTIC_BRANCH_GUARD_V1_GENERATOR_SKIP"
    if marker not in text:
        anchor = '        if hypothesis_id in ids:\n            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id, "layer": layer})\n            return\n'
        block = '''        # SEMANTIC_BRANCH_GUARD_V1_GENERATOR_SKIP
        branch_guard = semantic_branch_status(
            hypothesis_id=hypothesis_id,
            family=effective_family,
            state_dir=state_dir,
        )
        if branch_guard.get("blocked"):
            skipped.append({
                "field": spec.field,
                "reason": "semantic_branch_exhausted",
                "branch": branch_guard.get("branch"),
                "branch_reason": branch_guard.get("reason"),
                "hypothesis_id": hypothesis_id,
                "layer": layer,
            })
            return
        if hypothesis_id in ids:
            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id, "layer": layer})
            return
'''
        if anchor not in text:
            raise RuntimeError("feature_space_expansion_factory.py id_exists anchor not found")
        text = text.replace(anchor, block)

    write(path, text)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", default=".")
    p.add_argument("--package-root", default=None)
    args = p.parse_args()
    repo = Path(args.repo_root).resolve()
    package = Path(args.package_root).resolve() if args.package_root else Path(__file__).resolve().parents[1]
    copy_payload(repo, package)
    patch_pre_run_duplicate_guard(repo)
    patch_evaluate_candidate(repo)
    patch_feature_space_factory(repo)
    print("Semantic branch guard v1 applied.")
    return 0


if __name__ == "__main__":
    import argparse
    raise SystemExit(main())
