"""Apply parent-lock hardening patch.

Copies replacement governance modules and patches run_research_batch_autonomous.py
so every autonomous launch re-enforces manual parent governance before resolving
parent_strategy_config.
"""
from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PATCH_ROOT = Path(__file__).resolve().parents[0] / ".." / "patch_files"


def copy_file(src_rel: str, dst_rel: str | None = None) -> None:
    dst_rel = dst_rel or src_rel
    src = PATCH_ROOT / src_rel
    dst = ROOT / dst_rel
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"copied {dst_rel}")


def patch_wrapper() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    text = path.read_text(encoding="utf-8")

    import_line = "from scripts.research.manual_parent_governance import enforce_manual_parent_governance\n"
    if import_line not in text:
        marker = "from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses\n"
        if marker not in text:
            raise RuntimeError("Could not find import insertion point in run_research_batch_autonomous.py")
        text = text.replace(marker, marker + import_line)

    text = text.replace("prefer_best_champion=True,", "prefer_best_champion=False,")

    marker = "    sync_strategy_registry(registry_path=args.strategy_registry, state_dir=args.state_dir, repo_root=ROOT)\n\n    parent_config = resolve_current_parent_config_path("
    if marker in text and "Manual parent governance:" not in text:
        insert = "    sync_strategy_registry(registry_path=args.strategy_registry, state_dir=args.state_dir, repo_root=ROOT)\n\n    governance = enforce_manual_parent_governance(\n        state_dir=args.state_dir,\n        strategy_registry_path=args.strategy_registry,\n        official_parent=None,\n        pending_parent_candidate=None,\n        runs_dir=args.runs_dir,\n        repo_root=ROOT,\n    )\n    if governance.get(\"status\") == \"ok\":\n        print(\n            f\"Manual parent governance: official_parent={governance.get('official_parent')} \"\n            f\"pending_parent_candidate={governance.get('pending_parent_candidate_run_id')}\"\n        )\n    elif governance.get(\"status\") == \"blocked\":\n        write_autonomy_blocker(\n            state_dir=args.state_dir,\n            reason=str(governance.get(\"reason\")),\n            errors=[str(governance)],\n            next_action=\"Fix parent governance state before continuing.\",\n            context=governance,\n        )\n        print(f\"Manual parent governance blocked launch: {governance}\")\n        return 7\n\n    parent_config = resolve_current_parent_config_path("
        text = text.replace(marker, insert)
    elif "Manual parent governance:" in text:
        print("wrapper already contains manual governance enforcement")
    else:
        raise RuntimeError("Could not find governance insertion point in run_research_batch_autonomous.py")

    path.write_text(text, encoding="utf-8")
    print("patched scripts/run_research_batch_autonomous.py")


def main() -> int:
    copy_file("scripts/research/parent_state.py")
    copy_file("scripts/research/manual_parent_governance.py")
    copy_file("scripts/research/candidate_under_review.py")
    patch_wrapper()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
