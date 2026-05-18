"""Generate refinement hypotheses for the active candidate under review.

This is intentionally conservative: the official parent remains unchanged. The
factory only creates hypotheses that try to preserve the candidate's edge while
reducing drawdown, for example:
- slightly less concentration;
- safer exits;
- volatility/regime filters.
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomous_hypothesis_factory import real_override_signature, read_jsonl


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


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _existing_ids_and_sigs(bank_path: str | Path) -> tuple[set[str], set[str]]:
    rows = read_jsonl(bank_path)
    ids = {str(row.get("hypothesis_id")) for row in rows if row.get("hypothesis_id")}
    sigs = set()
    for row in rows:
        overrides = row.get("strategy_overrides")
        if isinstance(overrides, dict):
            sigs.add(real_override_signature(overrides))
    return ids, sigs


def _candidate_state(state_dir: str | Path) -> dict[str, Any]:
    return read_json(Path(state_dir) / "candidate_under_review.json", {}) or {}


def _base_override(candidate_cfg: dict[str, Any], hypothesis_id: str) -> dict[str, Any]:
    out = deepcopy(candidate_cfg)
    out["strategy_id"] = hypothesis_id
    out["hypothesis_id"] = hypothesis_id
    out["strategy_family"] = "candidate_under_review_drawdown_refinement"
    return out


def _candidate_top_n(candidate_cfg: dict[str, Any]) -> int | None:
    try:
        return int(candidate_cfg.get("entry_rule", {}).get("top_n"))
    except (TypeError, ValueError):
        return None


def _candidate_exit_threshold(candidate_cfg: dict[str, Any]) -> int | None:
    try:
        return int(candidate_cfg.get("exit_rule", {}).get("rank_threshold"))
    except (TypeError, ValueError):
        return None


def _make_hypothesis(
    *,
    hypothesis_id: str,
    family: str,
    claim: str,
    mechanism: str,
    candidate_run_id: str,
    candidate_hypothesis_id: str | None,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "claim": claim,
        "causal_mechanism": mechanism,
        "bibliography_basis": [
            {"source_id": "candidate_under_review_refinement", "title": "Refine high-CAGR candidate to reduce drawdown before promotion"}
        ],
        "empirical_basis": [
            {"run_id": candidate_run_id, "hypothesis_id": candidate_hypothesis_id, "reason": "Candidate under review has higher CAGR but worse drawdown; refine before promotion."}
        ],
        "features_required": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": family,
        "falsification_rule": "Reject if CAGR edge versus official parent disappears or max drawdown remains materially worse than candidate/parent trade-off.",
        "strategy_overrides": overrides,
    }


def build_candidate_review_hypotheses(
    *,
    state_dir: str | Path = "state",
    max_new: int = 8,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    repo_root: str | Path = ROOT,
) -> list[dict[str, Any]]:
    state = _candidate_state(state_dir)
    if state.get("status") != "active":
        return []
    config_path = state.get("strategy_config_path")
    p = Path(config_path or "")
    if not p.is_absolute():
        p = Path(repo_root) / p
    candidate_cfg = read_json(p, {}) or {}
    if not candidate_cfg:
        return []

    candidate_run_id = str(state.get("candidate_run_id") or "CANDIDATE")
    candidate_hypothesis_id = state.get("hypothesis_id") or candidate_cfg.get("hypothesis_id") or candidate_cfg.get("strategy_id")
    safe_run_id = candidate_run_id.replace("-", "_")

    ids, sigs = _existing_ids_and_sigs(hypothesis_bank_path)
    rows: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if len(rows) >= max_new:
            return
        hid = str(row.get("hypothesis_id"))
        if hid in ids:
            return
        sig = real_override_signature(row.get("strategy_overrides", {}))
        if sig in sigs:
            return
        ids.add(hid)
        sigs.add(sig)
        rows.append(row)

    top_n = _candidate_top_n(candidate_cfg)
    if top_n:
        for n in sorted({top_n + 1, top_n + 2, top_n + 3, max(1, top_n - 1)}):
            if n == top_n or n <= 0:
                continue
            hid = f"HYP_REVIEW_{safe_run_id}_TOPN_{n}_V1"
            overrides = _base_override(candidate_cfg, hid)
            overrides.setdefault("entry_rule", {})["top_n"] = int(n)
            add(_make_hypothesis(
                hypothesis_id=hid,
                family="candidate_under_review_drawdown_refinement",
                claim=f"Adjusting candidate {candidate_run_id} to top_n={n} may preserve high CAGR while reducing concentration drawdown.",
                mechanism="Slightly less/more concentration can smooth drawdowns while keeping the candidate's momentum signal.",
                candidate_run_id=candidate_run_id,
                candidate_hypothesis_id=candidate_hypothesis_id,
                overrides=overrides,
            ))

    threshold = _candidate_exit_threshold(candidate_cfg)
    if threshold:
        for t in sorted({max(1, threshold - 4), max(1, threshold - 2), threshold + 2}):
            if t == threshold:
                continue
            hid = f"HYP_REVIEW_{safe_run_id}_EXIT_{t}_V1"
            overrides = _base_override(candidate_cfg, hid)
            overrides.setdefault("exit_rule", {})["rank_threshold"] = int(t)
            add(_make_hypothesis(
                hypothesis_id=hid,
                family="candidate_under_review_exit_refinement",
                claim=f"Changing candidate {candidate_run_id} exit threshold to {t} may reduce drawdown without destroying CAGR.",
                mechanism="A safer exit can cut deteriorating positions earlier; a slightly wider exit can reduce churn if the candidate is overtrading.",
                candidate_run_id=candidate_run_id,
                candidate_hypothesis_id=candidate_hypothesis_id,
                overrides=overrides,
            ))

    # Add a conservative regime/volatility variant if relevant fields exist in data.
    for suffix, risk_key, value, claim in [
        ("TRAILING_18", "trailing_stop_pct", 18, "A moderate trailing stop can trim tail drawdown while retaining trend exposure."),
        ("TRAILING_22", "trailing_stop_pct", 22, "A wider trailing stop may reduce drawdown without excessive whipsaw."),
    ]:
        hid = f"HYP_REVIEW_{safe_run_id}_{suffix}_V1"
        overrides = _base_override(candidate_cfg, hid)
        overrides.setdefault("risk_management", {})[risk_key] = value
        add(_make_hypothesis(
            hypothesis_id=hid,
            family="candidate_under_review_drawdown_refinement",
            claim=f"{claim} Candidate={candidate_run_id}.",
            mechanism="Risk control is applied only to the candidate-under-review, not to the official parent.",
            candidate_run_id=candidate_run_id,
            candidate_hypothesis_id=candidate_hypothesis_id,
            overrides=overrides,
        ))

    return rows[:max_new]


def generate_candidate_review_hypotheses(
    *,
    state_dir: str | Path = "state",
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    max_new: int = 8,
    repo_root: str | Path = ROOT,
) -> dict[str, Any]:
    state = _candidate_state(state_dir)
    if state.get("status") != "active":
        return {"generated": 0, "reason": "no_active_candidate_under_review", "candidate_status": state.get("status")}
    rows = build_candidate_review_hypotheses(
        state_dir=state_dir,
        hypothesis_bank_path=hypothesis_bank_path,
        max_new=max_new,
        repo_root=repo_root,
    )
    append_jsonl(hypothesis_bank_path, rows)
    return {
        "generated": len(rows),
        "reason": "candidate_under_review_hypotheses_generated" if rows else "no_new_candidate_under_review_hypotheses",
        "candidate_run_id": state.get("candidate_run_id"),
        "hypotheses": [row.get("hypothesis_id") for row in rows],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Generate refinement hypotheses for the current candidate under review.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--max-new", type=int, default=8)
    p.add_argument("--repo-root", default=str(ROOT))
    args = p.parse_args()
    print(json.dumps(generate_candidate_review_hypotheses(
        state_dir=args.state_dir,
        hypothesis_bank_path=args.hypothesis_bank,
        max_new=args.max_new,
        repo_root=args.repo_root,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
