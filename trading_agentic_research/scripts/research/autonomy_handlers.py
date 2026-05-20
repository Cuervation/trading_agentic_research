"""Registry-based handlers for autonomous research blockers.

Handlers are intentionally conservative: READY_TO_RUN is only returned when the
selector reports an actually eligible hypothesis.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.data_path_resolver import resolve_data_paths
from scripts.research.external_data_acquisition import acquire_sector_metadata
from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses
from scripts.research.literature_template_expander import propose_literature_templates
from scripts.research.paper_searcher import generate_paper_ideas
from scripts.research.research_expansion_executor import execute_research_expansion
from scripts.research.research_expansion_planner import build_research_expansion_plan

VALID_STATUSES = {
    "READY_TO_RUN",
    "NO_SAFE_ACTION",
    "MANUAL_REVIEW_REQUIRED",
    "CANDIDATE_FOUND",
    "RESEARCH_EXHAUSTED",
}


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _latest_log(reports_dir: str | Path) -> dict[str, Any]:
    reports = Path(reports_dir)
    logs = sorted(reports.glob("overnight_run_*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    if not logs:
        return {"path": None, "content": None}
    p = logs[0]
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")[-12000:]}


@dataclass
class HandlerResult:
    status: str
    action_taken: str
    next_action: str
    eligibility_after: dict[str, Any]
    files_changed: list[str] = field(default_factory=list)
    safety_checks: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid handler status: {self.status}")
        if self.status == "READY_TO_RUN" and not self.eligibility_after.get("eligible"):
            raise ValueError("READY_TO_RUN requires eligibility_after.eligible=true")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _eligibility(args: Any) -> dict[str, Any]:
    return eligible_hypothesis_preflight(
        hypothesis_bank=args.hypothesis_bank,
        state_dir=args.state_dir,
        prefer_unseen=True,
        max_repeats_per_hypothesis=getattr(args, "max_repeats_per_hypothesis", 1),
    )


def _cached_eligibility(state: dict[str, Any], args: Any) -> dict[str, Any]:
    blocker = state.get("autonomy_blocker") if isinstance(state.get("autonomy_blocker"), dict) else {}
    context = blocker.get("context") if isinstance(blocker.get("context"), dict) else {}
    for key in ("final_eligibility", "eligibility_after", "eligibility"):
        value = context.get(key)
        if isinstance(value, dict) and "eligible" in value:
            return value
    return _eligibility(args)


def _safety(state: dict[str, Any]) -> dict[str, Any]:
    parent = state.get("current_parent") or {}
    candidate = state.get("candidate_under_review") or {}
    return {
        "parent_auto002_protected": parent.get("current_parent_run_id") == "AUTO_002",
        "parent_updates_manual": bool(parent.get("parent_updates_require_manual_approval", True)),
        "baseline_promotion_blocked": bool(parent.get("parent_promotion_blocked", True)),
        "candidate_under_review_consistent": candidate.get("status") in {"review_exhausted", "active", "disabled", None},
    }


def collect_state(*, state_dir: str | Path, runs_dir: str | Path, reports_dir: str | Path, hypothesis_bank: str | Path, paper_ideas: str | Path) -> dict[str, Any]:
    state = Path(state_dir)
    reports = Path(reports_dir)
    return {
        "autonomy_blocker": read_json(state / "autonomy_blocker.json", {}) or {},
        "batch_state": read_json(state / "batch_state.json", {}) or {},
        "research_expansion_plan": read_json(state / "research_expansion_plan.json", {}) or {},
        "missing_feature_priority": read_json(state / "missing_feature_priority.json", {}) or {},
        "current_parent": read_json(state / "current_parent.json", {}) or {},
        "candidate_under_review": read_json(state / "candidate_under_review.json", {}) or {},
        "generation_feedback": read_json(state / "generation_feedback.json", None) or read_jsonl(state / "generation_feedback.jsonl"),
        "missing_feature_tasks": read_jsonl(state / "missing_feature_tasks.jsonl"),
        "semantic_branch_exhaustion": read_json(state / "semantic_branch_exhaustion.json", {}) or {},
        "strategy_effect_index": read_json(state / "strategy_effect_index.json", {}) or {},
        "hypothesis_bank_path": str(hypothesis_bank),
        "paper_ideas_path": str(paper_ideas),
        "latest_log": _latest_log(reports),
        "recent_runs": sorted([str(p) for p in Path(runs_dir).glob("EXP_*")], reverse=True)[:10],
    }


def classify_blocker(state: dict[str, Any]) -> dict[str, Any]:
    blocker = state.get("autonomy_blocker") or {}
    reason = str(blocker.get("reason") or "")
    batch_state = state.get("batch_state") or {}
    stop_reason = str(batch_state.get("stop_reason") or "")
    text = f"{reason} {stop_reason}".lower()
    if reason == "missing_sector_classification_source":
        blocker_type = "missing_sector_classification_source"
    elif reason == "new_literature_family_required":
        blocker_type = "new_literature_family_required"
    elif reason in {"manual_review_required", "candidate_found"}:
        blocker_type = reason
    elif "policy" in text:
        blocker_type = "policy_blocked"
    elif "import" in text or "modulenotfound" in text:
        blocker_type = "import_error"
    elif "config" in text:
        blocker_type = "config_error"
    elif "state" in text and ("invalid" in text or "inconsisten" in text):
        blocker_type = "state_inconsistency"
    elif "external" in text and ("missing" in text or "source" in text):
        blocker_type = "missing_external_data"
    elif reason in {"research_space_exhausted", "no_eligible_hypotheses", "no_eligible_hypotheses_after_fallbacks"} or "no eligible hypotheses" in text:
        blocker_type = "research_space_exhausted"
    elif "zero" in text or "completed zero iterations" in text:
        blocker_type = "zero_iteration_batch"
    elif "duplicate" in text:
        blocker_type = "duplicate_loop"
    elif "data" in text or "path" in text:
        blocker_type = "data_path_error"
    elif "traceback" in text or "runtime" in text or "failed" in text:
        blocker_type = "runtime_error"
    elif "feature" in text:
        blocker_type = "feature_missing"
    elif "not convertible" in text or "not_convertible" in text:
        blocker_type = "paper_idea_not_convertible"
    elif "template" in text or "paper" in text:
        blocker_type = "template_missing"
    elif "governance" in text or "parent" in text or "baseline" in text:
        blocker_type = "governance_risk"
    else:
        blocker_type = "unknown"
    return {"blocker_type": blocker_type, "reason": reason or stop_reason or "unknown", "status": blocker.get("status", "blocked"), "raw": blocker}


def _status_from_eligibility(eligibility: dict[str, Any], fallback: str = "NO_SAFE_ACTION") -> str:
    return "READY_TO_RUN" if eligibility.get("eligible") else fallback


def _handler_research_space_exhausted(state: dict[str, Any], args: Any) -> HandlerResult:
    before = _cached_eligibility(state, args)
    plan = build_research_expansion_plan(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        final_eligibility=before,
    )
    executor = execute_research_expansion(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        project_config=getattr(args, "project_config", "configs/project_config.json"),
        max_new=getattr(args, "max_literature_hypotheses", 8),
    )
    after = executor.get("eligibility_after") if isinstance(executor.get("eligibility_after"), dict) else _eligibility(args)
    files_changed = ["reports/research_expansion_plan.md", "state/research_expansion_plan.json", *executor.get("files_changed", [])]
    if after.get("eligible"):
        status = "READY_TO_RUN"
        next_action = f"Run batch with eligible hypothesis {after.get('hypothesis_id')}"
    else:
        status = "NO_SAFE_ACTION"
        next_action = executor.get("next_action") or plan.get("next_action") or "Create a genuinely new non-duplicate research family/template."
    return HandlerResult(
        status=status,
        action_taken="research_expansion_planner_then_executor",
        next_action=next_action,
        eligibility_after=after,
        files_changed=files_changed,
        safety_checks=_safety(state),
        details={"eligibility_before": before, "plan_next_action": plan.get("next_action"), "executor": executor},
    )


def _parent_config(state_dir: str | Path) -> str:
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    return str(current.get("current_parent_config_path") or "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json")


def _handler_paper_searcher(state: dict[str, Any], args: Any) -> HandlerResult:
    before = _cached_eligibility(state, args)
    ideas = generate_paper_ideas(
        output=args.paper_ideas,
        online=bool(getattr(args, "online_paper_search", False)),
        limit=int(getattr(args, "max_paper_ideas", 5)),
    )
    mined = mine_literature_hypotheses(
        parent_strategy_config_path=_parent_config(args.state_dir),
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=int(getattr(args, "max_literature_hypotheses", 8)),
        paper_ideas_path=args.paper_ideas,
    )
    after = _eligibility(args) if mined.get("generated") else before
    files_changed = ["bibliography/paper_ideas.jsonl"] if ideas.get("rows_written") else []
    if mined.get("generated"):
        files_changed.append("bibliography/hypothesis_bank.jsonl")
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="paper_searcher_then_literature_miner",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else "Paper search/miner produced no eligible supported non-duplicate hypothesis; continue with template and feature-gap handlers.",
        eligibility_after=after,
        files_changed=files_changed,
        safety_checks=_safety(state),
        details={"paper_searcher": ideas, "literature_miner": mined},
    )


def _handler_literature_template_expander(state: dict[str, Any], args: Any) -> HandlerResult:
    before = _cached_eligibility(state, args)
    templates = propose_literature_templates(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        write=True,
        record_missing_tasks=True,
        max_new=int(getattr(args, "max_literature_hypotheses", 8)),
    )
    after = _eligibility(args) if templates.get("written") else before
    files_changed = ["reports/literature_template_expansion.md", "state/literature_template_expansion.json"]
    if templates.get("written"):
        files_changed.append("bibliography/hypothesis_bank.jsonl")
    if templates.get("missing_tasks_written"):
        files_changed.append("state/missing_feature_tasks.jsonl")
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="literature_template_expander_write_safe",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else "No supported non-duplicate template is writeable; continue with feature-gap/external-data analysis.",
        eligibility_after=after,
        files_changed=files_changed,
        safety_checks=_safety(state),
        details=templates,
    )


def _handler_feature_gap_analyzer(state: dict[str, Any], args: Any) -> HandlerResult:
    executor = execute_research_expansion(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        project_config=getattr(args, "project_config", "configs/project_config.json"),
        max_new=getattr(args, "max_literature_hypotheses", 8),
    )
    after = executor.get("eligibility_after") if isinstance(executor.get("eligibility_after"), dict) else _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="feature_gap_analyzer_executor",
        next_action=executor.get("next_action") or "No safe feature gap action remains.",
        eligibility_after=after,
        files_changed=executor.get("files_changed", []),
        safety_checks=_safety(state),
        details=executor,
    )


def _handler_external_data_acquisition(state: dict[str, Any], args: Any) -> HandlerResult:
    before = _cached_eligibility(state, args)
    resolved = read_json(Path(args.state_dir) / "data_paths_resolved.json", {}) or {}
    weekly = resolved.get("weekly_file")
    files_changed: list[str] = []
    details: dict[str, Any]
    if weekly:
        details = acquire_sector_metadata(weekly_file=weekly, reports_dir=args.reports_dir, state_dir=args.state_dir)
        files_changed.extend(["reports/sector_metadata_validation.md", "state/sector_metadata_validation.json"])
        if details.get("status") == "valid":
            files_changed.append("data/sp500_sector_metadata.csv")
    else:
        details = {"status": "blocked", "reason": "missing_weekly_file", "next_action": "Resolve active weekly_file before external data acquisition."}
    after = before
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="external_data_acquisition",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else details.get("next_action", "External data acquired/validated, but no eligible hypothesis exists yet."),
        eligibility_after=after,
        files_changed=files_changed,
        safety_checks=_safety(state),
        details=details,
    )


def _handler_novelty_checker(state: dict[str, Any], args: Any) -> HandlerResult:
    after = _eligibility(args)
    blocked_counts = ((after.get("effective_summary") or {}).get("blocked_counts") or {})
    next_action = "Run eligible non-duplicate hypothesis." if after.get("eligible") else (
        "Novelty check confirms no eligible unique signature remains; add a genuinely new causal mechanism, not an ID-only variant."
    )
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="novelty_checker_guard_only",
        next_action=next_action,
        eligibility_after=after,
        safety_checks=_safety(state),
        details={"blocked_counts": blocked_counts},
    )


def _handler_hypothesis_eligibility(state: dict[str, Any], args: Any) -> HandlerResult:
    after = _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="hypothesis_eligibility_validation",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else str(after.get("reason") or "No eligible hypotheses after all safe handlers."),
        eligibility_after=after,
        safety_checks=_safety(state),
        details={"effective_summary": after.get("effective_summary")},
    )


def _handler_policy_blocked(state: dict[str, Any], args: Any) -> HandlerResult:
    policy = read_json(getattr(args, "policy", "governance/research_policy.json"), {}) or {}
    max_allowed = int((policy.get("autonomous_controls", {}) or {}).get("max_runs_without_manual_review", 20) or 20)
    adjusted = min(int(getattr(args, "max_runs", max_allowed)), max_allowed)
    after = _eligibility(args)
    status = _status_from_eligibility(after)
    return HandlerResult(
        status=status,
        action_taken=f"adjusted_max_runs_to_{adjusted}",
        next_action=f"Retry with --max-runs {adjusted}" if after.get("eligible") else "Resolve no eligible hypotheses before retrying policy-adjusted run.",
        eligibility_after=after,
        safety_checks=_safety(state),
        details={"adjusted_max_runs": adjusted, "policy_max": max_allowed},
    )


def _handler_zero_iteration_batch(state: dict[str, Any], args: Any) -> HandlerResult:
    after = _eligibility(args)
    if after.get("eligible"):
        return HandlerResult("READY_TO_RUN", "validated_existing_eligible_work", f"Retry batch with {after.get('hypothesis_id')}", after, safety_checks=_safety(state))
    return _handler_research_space_exhausted(state, args)


def _handler_duplicate_loop(state: dict[str, Any], args: Any) -> HandlerResult:
    after = _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="validated_duplicate_guards_only",
        next_action="Generate a non-duplicate signature before rerun." if not after.get("eligible") else f"Run eligible non-duplicate {after.get('hypothesis_id')}",
        eligibility_after=after,
        safety_checks=_safety(state),
        details={"duplicate_override_signature_count": (after.get("effective_summary") or {}).get("duplicate_override_signature_count")},
    )


def _handler_runtime_error(state: dict[str, Any], args: Any) -> HandlerResult:
    after = _eligibility(args)
    content = str((state.get("latest_log") or {}).get("content") or "")
    return HandlerResult(
        status="MANUAL_REVIEW_REQUIRED",
        action_taken="parsed_latest_log_only",
        next_action="Inspect latest traceback; automatic source edits are disabled unless deterministic.",
        eligibility_after=after,
        safety_checks=_safety(state),
        details={"log_path": (state.get("latest_log") or {}).get("path"), "tail": content.splitlines()[-80:]},
    )


def _handler_data_path_error(state: dict[str, Any], args: Any) -> HandlerResult:
    resolved = resolve_data_paths(
        weekly_file=None,
        daily_folder=None,
        project_config=getattr(args, "project_config", "configs/project_config.json"),
        local_data_paths="configs/local_data_paths.json",
        repo_root=ROOT,
        state_dir=args.state_dir,
        persist=True,
    )
    after = _eligibility(args) if resolved.can_run else {"eligible": False, "reason": "data_path_resolution_failed"}
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="resolved_data_paths" if resolved.can_run else "data_path_resolution_failed",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else "Fix configs/local_data_paths.json or pass unambiguous --weekly-file/--daily-folder.",
        eligibility_after=after,
        files_changed=["state/data_paths_resolved.json"] if resolved.can_run else [],
        safety_checks=_safety(state),
        details=resolved.to_dict(),
    )


def _handler_feature_missing(state: dict[str, Any], args: Any) -> HandlerResult:
    executor = execute_research_expansion(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        project_config=getattr(args, "project_config", "configs/project_config.json"),
        max_new=getattr(args, "max_literature_hypotheses", 8),
    )
    after = _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="feature_expansion_executor",
        next_action=executor.get("next_action") or "No calculable feature action remains.",
        eligibility_after=after,
        files_changed=executor.get("files_changed", []),
        safety_checks=_safety(state),
        details=executor,
    )


def _handler_missing_sector_classification_source(state: dict[str, Any], args: Any) -> HandlerResult:
    executor = execute_research_expansion(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        project_config=getattr(args, "project_config", "configs/project_config.json"),
        max_new=getattr(args, "max_literature_hypotheses", 8),
    )
    after = executor.get("eligibility_after") if isinstance(executor.get("eligibility_after"), dict) else _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="external_sector_metadata_then_feature_expansion",
        next_action=executor.get("next_action") or "Provide data/sp500_sector_metadata.csv or restore internet access.",
        eligibility_after=after,
        files_changed=executor.get("files_changed", []),
        safety_checks=_safety(state),
        details=executor,
    )


def _handler_template_missing(state: dict[str, Any], args: Any) -> HandlerResult:
    templates = propose_literature_templates(state_dir=args.state_dir, reports_dir=args.reports_dir, hypothesis_bank=args.hypothesis_bank, paper_ideas=args.paper_ideas, write=True)
    after = _eligibility(args)
    return HandlerResult(
        status=_status_from_eligibility(after),
        action_taken="literature_template_expander_write_safe",
        next_action=f"Run batch with {after.get('hypothesis_id')}" if after.get("eligible") else "No supported non-duplicate template is writeable; add a new causal family.",
        eligibility_after=after,
        files_changed=["bibliography/hypothesis_bank.jsonl"] if templates.get("written") else [],
        safety_checks=_safety(state),
        details=templates,
    )


def _handler_governance_risk(state: dict[str, Any], args: Any) -> HandlerResult:
    return HandlerResult(
        status="MANUAL_REVIEW_REQUIRED",
        action_taken="stopped_for_governance",
        next_action="Manual review required; autonomous parent/baseline promotion is forbidden.",
        eligibility_after=_eligibility(args),
        safety_checks=_safety(state),
        details={"current_parent": state.get("current_parent"), "candidate_under_review": state.get("candidate_under_review")},
    )


def _handler_state_inconsistency(state: dict[str, Any], args: Any) -> HandlerResult:
    return HandlerResult(
        status="MANUAL_REVIEW_REQUIRED",
        action_taken="state_inconsistency_guard_only",
        next_action="Manual review required before mutating historical state; inspect state/autonomy_blocker.json and state/batch_state.json.",
        eligibility_after=_eligibility(args),
        safety_checks=_safety(state),
        details={"autonomy_blocker": state.get("autonomy_blocker"), "batch_state": state.get("batch_state")},
    )


def _handler_candidate_found(state: dict[str, Any], args: Any) -> HandlerResult:
    return HandlerResult(
        status="CANDIDATE_FOUND",
        action_taken="stopped_for_candidate_review",
        next_action="Review candidate manually; autonomous baseline promotion remains forbidden.",
        eligibility_after=_eligibility(args),
        safety_checks=_safety(state),
        details={"candidate_under_review": state.get("candidate_under_review")},
    )


HANDLERS: dict[str, Callable[[dict[str, Any], Any], HandlerResult]] = {
    "paper_searcher": _handler_paper_searcher,
    "literature_template_expander": _handler_literature_template_expander,
    "feature_gap_analyzer": _handler_feature_gap_analyzer,
    "external_data_acquisition": _handler_external_data_acquisition,
    "novelty_checker": _handler_novelty_checker,
    "hypothesis_eligibility": _handler_hypothesis_eligibility,
    "research_expansion_planner_executor": _handler_research_space_exhausted,
    "new_literature_family_required": _handler_feature_gap_analyzer,
    "research_space_exhausted": _handler_research_space_exhausted,
    "no_eligible_hypotheses": _handler_research_space_exhausted,
    "missing_external_data": _handler_external_data_acquisition,
    "policy_blocked": _handler_policy_blocked,
    "zero_iteration_batch": _handler_zero_iteration_batch,
    "duplicate_loop": _handler_duplicate_loop,
    "runtime_error": _handler_runtime_error,
    "import_error": _handler_runtime_error,
    "data_path_error": _handler_data_path_error,
    "config_error": _handler_data_path_error,
    "feature_missing": _handler_feature_missing,
    "missing_sector_classification_source": _handler_missing_sector_classification_source,
    "template_missing": _handler_template_missing,
    "paper_idea_not_convertible": _handler_template_missing,
    "governance_risk": _handler_governance_risk,
    "state_inconsistency": _handler_state_inconsistency,
    "candidate_found": _handler_candidate_found,
    "manual_review_required": _handler_governance_risk,
}


def choose_handler(classification: dict[str, Any]) -> str:
    return str(classification.get("blocker_type") or "unknown")


def run_handler(handler_name: str, state: dict[str, Any], args: Any) -> HandlerResult:
    handler = HANDLERS.get(handler_name)
    if handler is None:
        after = _eligibility(args)
        return HandlerResult("NO_SAFE_ACTION", "no_registered_handler", f"No registered handler for blocker `{handler_name}`.", after, safety_checks=_safety(state), details={"handler": handler_name})
    return handler(state, args)
