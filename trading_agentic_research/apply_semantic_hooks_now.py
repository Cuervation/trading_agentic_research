from pathlib import Path

root = Path.cwd()

pre = root / "scripts" / "research" / "pre_run_duplicate_guard.py"
eval_file = root / "scripts" / "evaluate_candidate.py"
factory = root / "scripts" / "research" / "feature_space_expansion_factory.py"

for p in [pre, eval_file, factory]:
    if not p.exists():
        raise FileNotFoundError(p)

# ============================================================
# 1) pre_run_duplicate_guard.py
# ============================================================
text = pre.read_text(encoding="utf-8-sig")

import_anchor = "from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature_from_path\n"
import_line = "from scripts.research.semantic_branch_guard import semantic_branch_preflight\n"

if import_line not in text:
    if import_anchor not in text:
        raise RuntimeError("No encontré import_anchor en pre_run_duplicate_guard.py")
    text = text.replace(import_anchor, import_anchor + import_line)

anchor = '    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")\n'

semantic_block = '''    # SEMANTIC_BRANCH_GUARD_DIRECT_PATCH
    semantic = semantic_branch_preflight(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id or info.get("hypothesis_id"),
        family=family or info.get("strategy_family"),
    )
    if semantic.get("blocked"):
        return {
            "blocked": True,
            "reason": semantic.get("reason") or "semantic_branch_exhausted",
            "duplicate_of_run_id": semantic.get("duplicate_of_run_id"),
            "semantic_branch": semantic,
            "candidate": info,
            "hypothesis_id": hypothesis_id,
            "family": family,
        }

    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
'''

if "SEMANTIC_BRANCH_GUARD_DIRECT_PATCH" not in text:
    if anchor not in text:
        raise RuntimeError("No encontré anchor de sig/cfg_hash en pre_run_duplicate_guard.py")
    text = text.replace(anchor, semantic_block)

pre.write_text(text, encoding="utf-8")


# ============================================================
# 2) evaluate_candidate.py
# ============================================================
text = eval_file.read_text(encoding="utf-8-sig")

import_anchor = "from scripts.research.candidate_review_learning import update_candidate_review_learning_from_run\n"
import_line = "from scripts.research.semantic_branch_guard import refresh_semantic_branch_state\n"

if import_line not in text:
    if import_anchor not in text:
        raise RuntimeError("No encontré import_anchor en evaluate_candidate.py")
    text = text.replace(import_anchor, import_anchor + import_line)

anchor = '''    candidate_review_learning = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
    )

'''

refresh_block = anchor + '''    # SEMANTIC_BRANCH_REFRESH_DIRECT_PATCH
    semantic_branch_state = refresh_semantic_branch_state(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
    )

'''

if "SEMANTIC_BRANCH_REFRESH_DIRECT_PATCH" not in text:
    if anchor not in text:
        raise RuntimeError("No encontré anchor de candidate_review_learning en evaluate_candidate.py")
    text = text.replace(anchor, refresh_block)

print_anchor = '    print("Baseline promotion: blocked (manual review required)")\n'
semantic_print = '''    print(f"Semantic branch exhausted: {sum(1 for b in (semantic_branch_state.get('branches') or {}).values() if b.get('status') == 'exhausted')}")
    print("Baseline promotion: blocked (manual review required)")
'''

if "Semantic branch exhausted:" not in text:
    if print_anchor not in text:
        raise RuntimeError("No encontré print_anchor en evaluate_candidate.py")
    text = text.replace(print_anchor, semantic_print)

eval_file.write_text(text, encoding="utf-8")


# ============================================================
# 3) feature_space_expansion_factory.py
# ============================================================
text = factory.read_text(encoding="utf-8-sig")

import_anchor = "from scripts.research.cooldown_governance import hard_active_cooldown_families\n"
import_line = "from scripts.research.semantic_branch_guard import is_semantic_branch_exhausted\n"

if import_line not in text:
    if import_anchor not in text:
        raise RuntimeError("No encontré import_anchor en feature_space_expansion_factory.py")
    text = text.replace(import_anchor, import_anchor + import_line)

anchor = '''        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        if hypothesis_id in ids:
'''

semantic_skip_block = '''        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        # SEMANTIC_BRANCH_SKIP_DIRECT_PATCH
        semantic = is_semantic_branch_exhausted(
            state_dir=state_dir,
            runs_dir="runs",
            hypothesis_id=hypothesis_id,
            family=effective_family,
        )
        if semantic.get("exhausted"):
            skipped.append({
                "field": spec.field,
                "reason": "semantic_branch_exhausted",
                "hypothesis_id": hypothesis_id,
                "layer": layer,
                "branch_key": semantic.get("branch_key"),
                "semantic_reason": semantic.get("reason"),
            })
            return
        if hypothesis_id in ids:
'''

if "SEMANTIC_BRANCH_SKIP_DIRECT_PATCH" not in text:
    if anchor not in text:
        raise RuntimeError("No encontré anchor de hypothesis_id en feature_space_expansion_factory.py")
    text = text.replace(anchor, semantic_skip_block)

factory.write_text(text, encoding="utf-8")

print("SEMANTIC_HOOKS_PATCHED_OK")
print(pre)
print(eval_file)
print(factory)
