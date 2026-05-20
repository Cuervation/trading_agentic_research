"""Execute only safe research-expansion actions.

This executor never mutates the original feature CSV, never changes parent or
baseline governance, and only reports READY through eligibility checks performed
by the caller.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.data_path_resolver import resolve_data_paths
from scripts.research.feature_engineering_agent import build_feature_plan
from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses
from scripts.research.literature_template_expander import propose_literature_templates


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _persist_result(*, state_dir: str | Path, reports_dir: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    files = set(payload.get("files_changed") or [])
    files.update({"reports/research_expansion_executor.json", "state/research_expansion_executor.json"})
    payload["files_changed"] = sorted(files)
    write_json(Path(reports_dir) / "research_expansion_executor.json", payload)
    write_json(Path(state_dir) / "research_expansion_executor.json", payload)
    return payload


def _csv_header(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        delimiter = ";" if ";" in first and "," not in first else ","
        f.seek(0)
        return {str(x).strip() for x in next(csv.reader(f, delimiter=delimiter), [])}


def _next_action_from_priority(state_dir: str | Path) -> tuple[str, str]:
    priority = read_json(Path(state_dir) / "missing_feature_priority.json", {}) or {}
    top = (priority.get("priorities") or [{}])[0]
    if not top:
        return (
            "new_literature_family_required",
            "Add a genuinely new non-duplicate literature family/template; current features/templates are exhausted.",
        )

    feature = str(top.get("feature") or "unknown_feature")
    missing_external = set(top.get("external_requirements_missing") or [])
    if "sector_or_industry_classification" in missing_external:
        return (
            "missing_sector_classification_source",
            "Provide a ticker->sector/industry classification source to compute "
            f"`{feature}`; no sector/industry/GICS column exists in the active "
            "weekly/daily CSVs. Otherwise add a genuinely new non-duplicate literature family.",
        )

    return (
        "missing_feature_data_or_template",
        f"Implement missing feature `{feature}` only if data source is available; otherwise add a genuinely new non-duplicate literature family.",
    )


def _parent_config(state_dir: str | Path) -> str:
    parent = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    return str(parent.get("current_parent_config_path") or "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json")


def _update_local_weekly_path(expanded_csv: Path, *, state_dir: str | Path, project_config: str | Path) -> list[str]:
    local_cfg = ROOT / "configs/local_data_paths.json"
    current = read_json(local_cfg, {}) or {}
    data_paths = current.get("data_paths", current if isinstance(current, dict) else {})
    if not isinstance(data_paths, dict):
        data_paths = {}
    data_paths["weekly_file_path"] = str(expanded_csv.resolve()).replace("\\", "/")
    data_paths.setdefault("daily_folder_path", str(ROOT).replace("\\", "/"))
    current = {"data_paths": data_paths}
    write_json(local_cfg, current)
    resolve_data_paths(
        weekly_file=None,
        daily_folder=None,
        project_config=project_config,
        local_data_paths="configs/local_data_paths.json",
        repo_root=ROOT,
        state_dir=state_dir,
        persist=True,
    )
    return ["configs/local_data_paths.json", "state/data_paths_resolved.json"]


def _run_feature_engineering_if_safe(*, state_dir: str | Path, reports_dir: str | Path, project_config: str | Path) -> dict[str, Any]:
    plan = build_feature_plan(state_dir=state_dir, reports_dir=reports_dir, generate_candidate=True)
    safe_items = [
        item for item in plan.get("features_to_add", [])
        if item.get("known_recipe") is True and item.get("blocked") is False
    ]
    if not safe_items:
        blocked = plan.get("features_to_add", [])[:5]
        return {
            "action": "feature_engineering_skipped",
            "reason": "no_known_unblocked_feature_recipe",
            "blocked_features": blocked,
            "files_changed": ["reports/feature_engineering_plan.md", "reports/feature_engineering_plan.json"],
        }

    resolved = read_json(Path(state_dir) / "data_paths_resolved.json", {}) or {}
    source_csv = Path(str(resolved.get("weekly_file") or ""))
    if not source_csv.exists():
        return {"action": "feature_engineering_skipped", "reason": f"weekly_file_missing:{source_csv}", "files_changed": []}

    expanded_csv = ROOT / f"{source_csv.stem}_research_expanded.csv"
    cmd = [sys.executable, "scripts/generated/feature_engineering_candidate.py", "--input", str(source_csv), "--output", str(expanded_csv)]
    result = subprocess.run(cmd, cwd=ROOT, check=False, text=True, capture_output=True)
    if result.returncode != 0 or not expanded_csv.exists():
        return {
            "action": "feature_engineering_failed",
            "reason": "generated_candidate_failed",
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "files_changed": [],
        }

    required = {str(item.get("feature")) for item in safe_items}
    header = _csv_header(expanded_csv)
    missing = sorted(required.difference(header))
    if missing:
        return {"action": "feature_engineering_failed", "reason": f"expanded_csv_missing_features:{missing}", "files_changed": [str(expanded_csv)]}

    files = [str(expanded_csv), "scripts/generated/feature_engineering_candidate.py", *_update_local_weekly_path(expanded_csv, state_dir=state_dir, project_config=project_config)]
    return {"action": "feature_engineering_applied", "features": sorted(required), "output": str(expanded_csv), "files_changed": files}


def execute_research_expansion(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    paper_ideas: str | Path = "bibliography/paper_ideas.jsonl",
    project_config: str | Path = "configs/project_config.json",
    max_new: int = 8,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    files_changed: list[str] = []
    before = eligible_hypothesis_preflight(hypothesis_bank=hypothesis_bank, state_dir=state_dir)

    templates = propose_literature_templates(
        state_dir=state_dir,
        reports_dir=reports_dir,
        hypothesis_bank=hypothesis_bank,
        paper_ideas=paper_ideas,
        write=True,
        record_missing_tasks=True,
    )
    actions.append({"action": "literature_template_expander", "written": templates.get("written", [])})
    if templates.get("written"):
        files_changed.extend(["bibliography/hypothesis_bank.jsonl", "reports/literature_template_expansion.md", "state/literature_template_expansion.json"])

    # Eligibility is expensive. If no hypothesis rows were written, the bank
    # cannot have become eligible here, so reuse the already-validated result.
    after_templates = (
        eligible_hypothesis_preflight(hypothesis_bank=hypothesis_bank, state_dir=state_dir)
        if templates.get("written")
        else before
    )
    if after_templates.get("eligible"):
        return _persist_result(state_dir=state_dir, reports_dir=reports_dir, payload={
            "status": "READY_TO_RUN",
            "action_taken": "literature_template_expander",
            "eligibility_before": before,
            "eligibility_after": after_templates,
            "files_changed": sorted(set(files_changed)),
            "next_action": f"Run batch with {after_templates.get('hypothesis_id')}",
            "actions": actions,
        })

    feature_result = _run_feature_engineering_if_safe(state_dir=state_dir, reports_dir=reports_dir, project_config=project_config)
    actions.append(feature_result)
    files_changed.extend(feature_result.get("files_changed", []))

    if feature_result.get("action") == "feature_engineering_applied":
        mined = mine_literature_hypotheses(
            parent_strategy_config_path=_parent_config(state_dir),
            hypothesis_bank_path=hypothesis_bank,
            state_dir=state_dir,
            max_new=max_new,
            paper_ideas_path=paper_ideas,
        )
        actions.append({"action": "literature_hypothesis_miner_after_features", **mined})
        if mined.get("generated"):
            files_changed.append("bibliography/hypothesis_bank.jsonl")

    # Re-run selector only after a material action that can change eligibility.
    # Report-only planning must not pay for another full selector pass.
    material_change = bool(templates.get("written")) or feature_result.get("action") == "feature_engineering_applied"
    after = (
        eligible_hypothesis_preflight(hypothesis_bank=hypothesis_bank, state_dir=state_dir)
        if material_change
        else after_templates
    )
    if after.get("eligible"):
        status = "READY_TO_RUN"
        next_action = f"Run batch with {after.get('hypothesis_id')}"
    else:
        status = "NO_SAFE_ACTION"
        blocker_type, next_action = _next_action_from_priority(state_dir)

    payload = {
        "status": status,
        "blocker_type": blocker_type if status == "NO_SAFE_ACTION" else None,
        "action_taken": "research_expansion_executor",
        "eligibility_before": before,
        "eligibility_after": after,
        "files_changed": sorted(set(files_changed)),
        "next_action": next_action,
        "actions": actions,
    }
    return _persist_result(state_dir=state_dir, reports_dir=reports_dir, payload=payload)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--max-new", type=int, default=8)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = execute_research_expansion(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        project_config=args.project_config,
        max_new=args.max_new,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
