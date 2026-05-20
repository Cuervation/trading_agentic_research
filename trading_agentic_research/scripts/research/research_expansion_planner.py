"""Write an actionable research expansion plan when no hypothesis is executable.

Planning-only module: it reads eligibility/feedback/state and writes reports.
It never launches backtests, moves parents, promotes baselines, or consumes
hypotheses.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.literature_hypothesis_miner import available_weekly_features, ideas_from_paper_ideas
from scripts.research.literature_template_expander import propose_literature_templates
from scripts.research.missing_feature_task_prioritizer import prioritize_missing_feature_tasks


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            continue
    return rows


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def current_parent(state_dir: str | Path) -> dict[str, Any]:
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    return {
        "run_id": current.get("current_parent_run_id"),
        "hypothesis_id": current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id"),
        "config_path": current.get("current_parent_config_path"),
        "parent_promotion_blocked": current.get("parent_promotion_blocked"),
        "parent_updates_require_manual_approval": current.get("parent_updates_require_manual_approval"),
    }


def feedback_summary(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "generation_feedback.json", {}) or {}
    events = payload.get("events", []) or []
    latest: dict[str, dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    recent = []
    for event in events:
        phase = str(event.get("phase") or "unknown")
        latest[phase] = event
        result = event.get("generation_result") if isinstance(event.get("generation_result"), dict) else {}
        for key in ("missing_feature_tasks_seen", "skipped_family_cooldown", "skipped_duplicate_signature", "ideas_seen", "supported_seen"):
            totals[key] += as_int(result.get(key))
    for event in events[-12:]:
        result = event.get("generation_result") if isinstance(event.get("generation_result"), dict) else {}
        recent.append({
            "phase": event.get("phase"),
            "generated": event.get("generated"),
            "eligible_after_generation": event.get("eligible_after_generation"),
            "reason": event.get("reason"),
            "warning": event.get("warning"),
            "missing_feature_tasks_seen": result.get("missing_feature_tasks_seen"),
            "skipped_family_cooldown": result.get("skipped_family_cooldown"),
            "skipped_duplicate_signature": result.get("skipped_duplicate_signature"),
            "rows_written": result.get("rows_written"),
            "ideas_seen": result.get("ideas_seen"),
            "supported_seen": result.get("supported_seen"),
        })
    latest_compact = {}
    for phase, event in latest.items():
        result = event.get("generation_result") if isinstance(event.get("generation_result"), dict) else {}
        latest_compact[phase] = {
            "generated": event.get("generated"),
            "eligible_after_generation": event.get("eligible_after_generation"),
            "reason": event.get("reason"),
            "warning": event.get("warning"),
            "missing_feature_tasks_seen": result.get("missing_feature_tasks_seen"),
            "skipped_family_cooldown": result.get("skipped_family_cooldown"),
            "skipped_duplicate_signature": result.get("skipped_duplicate_signature"),
            "rows_written": result.get("rows_written"),
            "ideas_seen": result.get("ideas_seen"),
            "supported_seen": result.get("supported_seen"),
        }
    return {
        "event_count": len(events),
        "updated_at": payload.get("updated_at"),
        "recent_events": recent,
        "latest_by_phase": latest_compact,
        "totals": dict(totals),
    }


def semantic_summary(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "semantic_branch_exhaustion.json", {}) or {}
    branches = payload.get("branches", {}) if isinstance(payload, dict) else {}
    exhausted = []
    for key, detail in branches.items():
        status = str(detail.get("status") or ("exhausted" if detail.get("exhausted") else "active"))
        if status != "exhausted":
            continue
        exhausted.append({
            "branch_key": key,
            "family": str(key).split("/", 1)[0],
            "reason": detail.get("reason"),
            "event_count": len(detail.get("events", []) or []),
        })
    exhausted.sort(key=lambda x: (x["family"], x["branch_key"]))
    return {
        "branch_count": len(branches),
        "exhausted_branch_count": len(exhausted),
        "exhausted_branches": exhausted,
        "exhausted_families": sorted({row["family"] for row in exhausted}),
    }


def cooldown_summary(state_dir: str | Path, exhausted_families: set[str]) -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {}
    cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
    rows = []
    for family, detail in cooldowns.items():
        detail = detail if isinstance(detail, dict) else {"reason": str(detail)}
        rows.append({
            "family": str(family),
            "reason": detail.get("reason"),
            "failure_threshold": detail.get("failure_threshold"),
            "cooldown_until": detail.get("cooldown_until"),
            "hard": bool(detail.get("cooldown_until")),
            "only_cooldown": str(family) not in exhausted_families,
            "semantic_exhausted": str(family) in exhausted_families,
        })
    rows.sort(key=lambda x: (not x["only_cooldown"], x["family"]))
    return {
        "count": len(rows),
        "families": rows,
        "cooldown_only_families": [row["family"] for row in rows if row["only_cooldown"]],
        "hard_cooldown_families": [row["family"] for row in rows if row["hard"]],
    }


def bank_summary(hypothesis_bank: str | Path) -> dict[str, Any]:
    rows = read_jsonl(hypothesis_bank)
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    by_source: dict[str, list[str]] = defaultdict(list)
    feature_counter: Counter[str] = Counter()
    for row in rows:
        family = str(row.get("family") or "unknown")
        by_family[family][str(row.get("status") or "candidate")] += 1
        for feature in row.get("features_required", []) or []:
            feature_counter[str(feature)] += 1
        for basis in row.get("bibliography_basis", []) or []:
            source_id = str(basis.get("source_id") or "")
            if source_id:
                by_source[source_id].append(str(row.get("hypothesis_id") or ""))
    families = [{"family": family, "total": sum(counter.values()), "statuses": dict(counter)} for family, counter in by_family.items()]
    families.sort(key=lambda x: (-x["total"], x["family"]))
    return {
        "row_count": len(rows),
        "family_count": len(families),
        "families": families,
        "top_required_features": feature_counter.most_common(20),
        "generated_by_source": {k: v[:20] for k, v in by_source.items()},
    }


def missing_summary(state_dir: str | Path) -> dict[str, Any]:
    tasks = read_jsonl(Path(state_dir) / "missing_feature_tasks.jsonl")
    feature_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        source_id = str(task.get("source_id") or "unknown")
        by_source[source_id].append(task)
        if task.get("family"):
            family_counts[str(task.get("family"))] += 1
        for feature in task.get("missing_features", []) or []:
            feature = str(feature)
            feature_counts[feature] += 1
            by_feature[feature].append(task)
    return {
        "task_count": len(tasks),
        "feature_counts": feature_counts.most_common(),
        "family_counts": family_counts.most_common(),
        "by_source": {k: v[:10] for k, v in by_source.items()},
        "by_feature": {k: v[:10] for k, v in by_feature.items()},
    }


def strategy_effect_summary(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "strategy_effect_index.json", {}) or {}
    signatures = payload.get("signatures", {}) if isinstance(payload, dict) else {}
    duplicates = []
    for sig, detail in signatures.items():
        runs = detail.get("runs", []) or []
        if len(runs) <= 1:
            continue
        canonical = detail.get("canonical_payload", {}) or {}
        duplicates.append({
            "signature": str(sig)[:12],
            "run_count": len(runs),
            "runs": runs[:8],
            "ranking": canonical.get("ranking"),
            "entry_rule": canonical.get("entry_rule"),
            "exit_rule": canonical.get("exit_rule"),
        })
    duplicates.sort(key=lambda x: (-x["run_count"], x["signature"]))
    blocked = payload.get("blocked_attempts", []) if isinstance(payload, dict) else []
    return {
        "signature_count": len(signatures),
        "duplicate_signature_count": len(duplicates),
        "top_duplicate_signatures": duplicates[:10],
        "blocked_attempt_count": len(blocked) if isinstance(blocked, list) else 0,
    }


def paper_ideas_summary(
    *,
    paper_ideas: str | Path,
    generated_by_source: dict[str, list[str]],
    missing: dict[str, Any],
    state_dir: str | Path,
    cooldown_families: set[str],
    exhausted_families: set[str],
) -> dict[str, Any]:
    rows = read_jsonl(paper_ideas)
    features = available_weekly_features(state_dir)
    missing_by_source = missing.get("by_source", {}) or {}
    variants_by_source: dict[str, list[Any]] = defaultdict(list)
    for idea in ideas_from_paper_ideas(paper_ideas):
        variants_by_source[str(idea.source_id)].append(idea)

    items = []
    not_converted = []
    for row in rows:
        source_id = str(row.get("source_id") or row.get("title") or "unknown")
        variants = variants_by_source.get(source_id, [])
        families = sorted({str(x) for x in row.get("families", []) or []}.union({idea.family for idea in variants}))
        missing_features = sorted({feature for idea in variants for feature in set(idea.required_features).difference(features)})
        generated = generated_by_source.get(source_id, []) or []
        family_blockers = sorted(set(families).intersection(cooldown_families.union(exhausted_families)))
        reasons = []
        if missing_features:
            reasons.append("missing_required_features")
        if family_blockers:
            reasons.append("family_cooldown_or_exhausted")
        if generated:
            reasons.append("converted_but_currently_not_executable")
        if missing_by_source.get(source_id):
            reasons.append("missing_feature_task_exists")
        if variants and not generated and not missing_features:
            reasons.append("supported_template_not_materialized")
        item = {
            "source_id": source_id,
            "title": row.get("title"),
            "families": families,
            "required_features_hint": row.get("required_features_hint", []),
            "variant_count": len(variants),
            "missing_features": missing_features,
            "generated_hypotheses": generated[:10],
            "missing_task_count": len(missing_by_source.get(source_id, []) or []),
            "blocker_reasons": reasons,
        }
        items.append(item)
        if reasons and (missing_features or family_blockers or not generated):
            not_converted.append(item)
    not_converted.sort(key=lambda x: (-len(x["missing_features"]), -x["missing_task_count"], x["source_id"]))
    return {"paper_idea_count": len(rows), "items": items, "not_converted_or_not_executable": not_converted}


def why_no_executable(final: dict[str, Any], feedback: dict[str, Any]) -> list[str]:
    if final.get("eligible"):
        return [
            "Selector found executable work: "
            f"{final.get('hypothesis_id')} ({final.get('family')}). "
            "Run the autonomous wrapper before doing more expansion work."
        ]
    effective = final.get("effective_summary", {}) if isinstance(final.get("effective_summary"), dict) else {}
    blocked_counts = final.get("blocked_counts") or effective.get("blocked_counts") or {}
    bullets = []
    if final.get("reason"):
        bullets.append(str(final.get("reason")))
    if effective.get("executable_count") is not None:
        bullets.append(f"Selector-equivalent executable_count={effective.get('executable_count')}.")
    if blocked_counts:
        top = sorted(blocked_counts.items(), key=lambda kv: -as_int(kv[1]))[:6]
        bullets.append("Top blockers: " + ", ".join(f"{k}={v}" for k, v in top) + ".")
    feature_stall = effective.get("feature_space_stall", {}) if isinstance(effective.get("feature_space_stall"), dict) else {}
    if feature_stall.get("stalled"):
        bullets.append(f"Feature-space stall is active: {feature_stall.get('reason')}.")
    latest = feedback.get("latest_by_phase", {}) or {}
    if (latest.get("literature_after_paper_search") or latest.get("literature_miner") or {}).get("reason") == "no_supported_literature_hypotheses":
        bullets.append("Literature mining produced no supported executable hypotheses.")
    if (latest.get("feature_space_expansion") or {}).get("reason") == "no_new_feature_space_hypotheses":
        bullets.append("Feature-space expansion produced no new rows; current combinations are exhausted or duplicate.")
    return bullets


def possible_hypotheses(parent: dict[str, Any], priority: dict[str, Any], template_expansion: dict[str, Any]) -> list[dict[str, Any]]:
    parent_run_id = str(parent.get("run_id") or "PARENT")
    out = []
    for item in (priority.get("priorities") or [])[:8]:
        for suffix in (item.get("candidate_suffixes") or [])[:5]:
            out.append({
                "hypothesis_id": f"HYP_LIT_{parent_run_id}_{suffix}",
                "unblocked_by": item.get("feature"),
                "source": "missing_feature_task",
                "priority": item.get("priority"),
                "families": item.get("families"),
            })
    for proposal in (template_expansion.get("proposals") or [])[:8]:
        out.append({
            "hypothesis_id": proposal.get("hypothesis_id"),
            "unblocked_by": "existing_feature_template",
            "source": "literature_template_expander",
            "priority": "high",
            "families": [proposal.get("family")],
        })
    return out[:30]


def suggested_commands(parent: dict[str, Any]) -> list[dict[str, str]]:
    parent_config = parent.get("config_path") or "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
    return [
        {
            "label": "Refresh missing-feature priority report",
            "command": "python .\\scripts\\research\\missing_feature_task_prioritizer.py `\n  --state-dir .\\state `\n  --reports-dir .\\reports `\n  --paper-ideas .\\bibliography\\paper_ideas.jsonl",
        },
        {
            "label": "Dry-run supported literature templates using current features",
            "command": "python .\\scripts\\research\\literature_template_expander.py `\n  --state-dir .\\state `\n  --reports-dir .\\reports `\n  --hypothesis-bank .\\bibliography\\hypothesis_bank.jsonl `\n  --paper-ideas .\\bibliography\\paper_ideas.jsonl `\n  --no-record-missing-tasks",
        },
        {
            "label": "After adding features/templates, rerun literature miner before backtests",
            "command": f"python .\\scripts\\research\\literature_hypothesis_miner.py `\n  --parent-strategy-config .\\{parent_config} `\n  --hypothesis-bank .\\bibliography\\hypothesis_bank.jsonl `\n  --state-dir .\\state `\n  --paper-ideas .\\bibliography\\paper_ideas.jsonl",
        },
        {
            "label": "Then rerun autonomous research wrapper",
            "command": "python .\\scripts\\run_research_batch_autonomous.py `\n  --max-runs 5 `\n  --max-recovery-cycles 2 `\n  --project-config .\\configs\\project_config.json `\n  --state-dir .\\state `\n  --runs-dir .\\runs `\n  --reports-dir .\\reports",
        },
    ]


def build_research_expansion_plan(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    paper_ideas: str | Path = "bibliography/paper_ideas.jsonl",
    final_eligibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = Path(state_dir)
    reports = Path(reports_dir)
    state.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    parent = current_parent(state)
    final = final_eligibility or eligible_hypothesis_preflight(hypothesis_bank=hypothesis_bank, state_dir=state)
    feedback = feedback_summary(state)
    semantic = semantic_summary(state)
    cooldowns = cooldown_summary(state, set(semantic["exhausted_families"]))
    bank = bank_summary(hypothesis_bank)
    missing = missing_summary(state)
    strategy_effect = strategy_effect_summary(state)
    priority = {"task_count": missing["task_count"], "priorities": []}
    if missing["task_count"]:
        priority = prioritize_missing_feature_tasks(state_dir=state, reports_dir=reports, paper_ideas=paper_ideas)
    templates = propose_literature_templates(
        state_dir=state,
        reports_dir=None,
        hypothesis_bank=hypothesis_bank,
        paper_ideas=paper_ideas,
        write=False,
        record_missing_tasks=False,
    )
    paper = paper_ideas_summary(
        paper_ideas=paper_ideas,
        generated_by_source=bank["generated_by_source"],
        missing=missing,
        state_dir=state,
        cooldown_families={row["family"] for row in cooldowns["families"]},
        exhausted_families=set(semantic["exhausted_families"]),
    )

    high_features = [item for item in priority.get("priorities", []) if item.get("priority") == "high"]
    possible = possible_hypotheses(parent, priority, templates)
    high_actions = [
        f"Add or intentionally proxy `{item.get('feature')}`: unlocks {item.get('paper_ideas_unlocked')} paper idea(s), cost={item.get('implementation_cost')}, calculable_now={item.get('calculable_from_current_data')}."
        for item in high_features[:4]
    ]
    high_actions += [
        f"Review supported template `{proposal.get('hypothesis_id')}` ({proposal.get('family')}) before writing it to the bank."
        for proposal in (templates.get("proposals") or [])[:3]
    ]
    if not high_actions:
        high_actions = ["Create a genuinely new family/template before backtesting again; current space is exhausted."]

    if final.get("eligible"):
        next_action = f"Run autonomous wrapper on eligible hypothesis `{final.get('hypothesis_id')}`"
    else:
        next_action = (
            f"Implement/proxy top missing feature `{high_features[0].get('feature')}`"
            if high_features
            else "Review supported template proposals or add a genuinely new literature family"
        )
    payload = {
        "version": 1,
        "generated_at": now_iso(),
        "parent": parent,
        "final_eligibility": final,
        "why_no_executable": why_no_executable(final, feedback),
        "generation_feedback": feedback,
        "families": {"semantic_exhaustion": semantic, "cooldowns": cooldowns, "hypothesis_bank": {k: v for k, v in bank.items() if k != "generated_by_source"}},
        "paper_ideas": paper,
        "missing_features": missing,
        "missing_feature_priority": priority,
        "literature_template_expansion": {"available_feature_count": templates.get("available_feature_count"), "proposals": templates.get("proposals", []), "blocked": templates.get("blocked", [])},
        "strategy_effect_index": strategy_effect,
        "possible_new_hypotheses_if_unblocked": possible,
        "priority_actions": {
            "high": high_actions,
            "medium": ["Do not write duplicate-signature templates; unsupported ideas must become missing-feature tasks, not fake hypotheses."],
            "low": ["Broaden paper search only after feature/template blockers are addressed; adding papers alone already failed to produce executable hypotheses."],
        },
        "suggested_commands": suggested_commands(parent),
        "next_action": next_action,
        "outputs": {
            "report": str(reports / "research_expansion_plan.md"),
            "state": str(state / "research_expansion_plan.json"),
            "missing_feature_priority_report": str(reports / "missing_feature_priority.md") if missing["task_count"] else None,
        },
    }
    write_json(state / "research_expansion_plan.json", payload)
    write_json(reports / "research_expansion_plan.json", payload)
    write_markdown(reports / "research_expansion_plan.md", payload)
    return payload


def write_markdown(path: str | Path, payload: dict[str, Any]) -> None:
    final = payload["final_eligibility"]
    effective = final.get("effective_summary", {}) if isinstance(final.get("effective_summary"), dict) else {}
    blocked_counts = final.get("blocked_counts") or effective.get("blocked_counts") or {}
    feature_stall = effective.get("feature_space_stall", {}) if isinstance(effective.get("feature_space_stall"), dict) else {}
    semantic = payload["families"]["semantic_exhaustion"]
    cooldowns = payload["families"]["cooldowns"]
    paper = payload["paper_ideas"]
    priority = payload["missing_feature_priority"]
    templates = payload["literature_template_expansion"]
    strategy_effect = payload["strategy_effect_index"]

    if final.get("eligible"):
        lead = "Current result: **executable research work is available; run the autonomous wrapper before expanding capabilities further.**"
        why_heading = "## Current executable work"
    else:
        lead = "Current result: **research is exhausted under the current hypothesis space; do not launch backtests until a new feature/template/family creates executable work.**"
        why_heading = "## Why no hypotheses are executable"

    lines = [
        "# Research Expansion Plan",
        "",
        lead,
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Parent stays locked: `{payload['parent'].get('run_id')}` / `{payload['parent'].get('hypothesis_id')}`",
        f"- Recommended mode: `{final.get('recommended_mode') or effective.get('recommended_mode')}`",
        f"- Eligible: `{final.get('eligible')}`",
        f"- Executable count: `{effective.get('executable_count')}`",
        f"- Feature-space stall: `{feature_stall.get('stalled')}` ({feature_stall.get('reason')})",
        "",
        why_heading,
        "",
    ]
    lines += [f"- {bullet}" for bullet in payload.get("why_no_executable", [])]
    lines += ["", "### Blocker counts", "", "| blocker | count |", "|---|---:|"]
    lines += [f"| `{reason}` | {count} |" for reason, count in sorted(blocked_counts.items(), key=lambda kv: -as_int(kv[1]))] or ["| - | 0 |"]

    lines += ["", "## Exhausted and cooldown families", "", "### Semantically exhausted branches", "", "| family | branch | reason | events |", "|---|---|---|---:|"]
    rows = semantic.get("exhausted_branches") or []
    lines += [f"| `{row['family']}` | `{row['branch_key']}` | {row.get('reason') or '-'} | {row.get('event_count')} |" for row in rows[:25]] or ["| - | - | - | 0 |"]
    lines += ["", "### Families only in cooldown/advisory block", "", "| family | hard cooldown | reason |", "|---|:---:|---|"]
    cooldown_only = [row for row in cooldowns.get("families", []) if row.get("only_cooldown")]
    lines += [f"| `{row['family']}` | {'yes' if row.get('hard') else 'no'} | {row.get('reason') or '-'} |" for row in cooldown_only[:40]] or ["| - | - | - |"]

    lines += ["", "## Paper ideas that did not become executable work", "", f"Paper ideas read: **{paper.get('paper_idea_count', 0)}**", "", "| source | title | blockers | missing features | generated hypotheses |", "|---|---|---|---|---:|"]
    for item in (paper.get("not_converted_or_not_executable") or [])[:18]:
        lines.append(
            f"| `{item.get('source_id')}` | {str(item.get('title') or '-').replace('|', '/')} | {', '.join(item.get('blocker_reasons') or []) or '-'} | {', '.join('`'+x+'`' for x in item.get('missing_features', [])) or '-'} | {len(item.get('generated_hypotheses') or [])} |"
        )

    lines += ["", "## Missing feature priorities", "", "| priority | feature | papers unlocked | cost | calculable now | nearby/current columns |", "|---|---|---:|---|:---:|---|"]
    for item in (priority.get("priorities") or [])[:12]:
        near = ", ".join(f"`{x}`" for x in (item.get("nearby_existing_columns") or [])[:5]) or "-"
        lines.append(f"| {item.get('priority')} | `{item.get('feature')}` | {item.get('paper_ideas_unlocked')} | {item.get('implementation_cost')} | {'yes' if item.get('calculable_from_current_data') else 'no'} | {near} |")
    if not priority.get("priorities"):
        lines.append("| - | - | 0 | - | - | - |")

    lines += ["", "## Supported literature templates using existing features", "", "These are proposals only. They are not written to the hypothesis bank by this planner.", "", "| hypothesis | family | required features |", "|---|---|---|"]
    proposals = templates.get("proposals") or []
    lines += [f"| `{p.get('hypothesis_id')}` | `{p.get('family')}` | {', '.join('`'+x+'`' for x in p.get('features_required', []))} |" for p in proposals[:12]] or ["| - | - | - |"]

    lines += ["", "## Hypotheses that should become possible after expansion", "", "| hypothesis | unlocked by | source | priority |", "|---|---|---|---|"]
    possible = payload.get("possible_new_hypotheses_if_unblocked") or []
    lines += [f"| `{row.get('hypothesis_id')}` | `{row.get('unblocked_by')}` | {row.get('source')} | {row.get('priority')} |" for row in possible] or ["| - | - | - | - |"]

    lines += ["", "## Duplicate pressure", "", f"- Duplicate strategy-effect signatures: **{strategy_effect.get('duplicate_signature_count', 0)}**", f"- Pre-run blocked attempts indexed: **{strategy_effect.get('blocked_attempt_count', 0)}**", "", "| signature | runs | ranking | entry | exit |", "|---|---:|---|---|---|"]
    lines += [f"| `{row.get('signature')}` | {row.get('run_count')} | `{row.get('ranking')}` | `{row.get('entry_rule')}` | `{row.get('exit_rule')}` |" for row in (strategy_effect.get("top_duplicate_signatures") or [])[:8]] or ["| - | 0 | - | - | - |"]

    lines += ["", "## Priority actions", "", "### High", ""]
    lines += [f"- {x}" for x in payload["priority_actions"]["high"]]
    lines += ["", "### Medium", ""]
    lines += [f"- {x}" for x in payload["priority_actions"]["medium"]]
    lines += ["", "### Low", ""]
    lines += [f"- {x}" for x in payload["priority_actions"]["low"]]
    lines += ["", "## Suggested commands", ""]
    for cmd in payload["suggested_commands"]:
        lines += [f"### {cmd['label']}", "", "```powershell", cmd["command"], "```", ""]
    lines += ["## Guardrail", "", "Do **not** rerun old `HYP_FSPACE` variants, do **not** override duplicate signatures, and do **not** move `AUTO_002`/`current_parent` as part of expansion planning.", ""]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Write a research expansion plan when no hypotheses are executable.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--final-eligibility-json", default=None)
    args = p.parse_args()
    final = read_json(args.final_eligibility_json, None) if args.final_eligibility_json else None
    result = build_research_expansion_plan(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        hypothesis_bank=args.hypothesis_bank,
        paper_ideas=args.paper_ideas,
        final_eligibility=final,
    )
    print(json.dumps({
        "report": result["outputs"]["report"],
        "state": result["outputs"]["state"],
        "next_action": result["next_action"],
        "high_priority": result["priority_actions"]["high"][:3],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
