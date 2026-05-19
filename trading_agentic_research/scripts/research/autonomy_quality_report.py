"""Autonomy quality report for research batches."""
from __future__ import annotations
import csv, json
from collections import Counter
from pathlib import Path
from typing import Any

def _read_json(path: str | Path, default: Any=None) -> Any:
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError: return default

def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p=Path(path)
    if not p.exists(): return []
    out=[]
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try: out.append(json.loads(line))
            except json.JSONDecodeError: pass
    return out

def build_autonomy_quality_report(*, state_dir: str | Path="state", reports_dir: str | Path="reports", runs_dir: str | Path="runs", last_n: int=30) -> dict[str, Any]:
    ledger=_read_jsonl(Path(state_dir)/"research_ledger.jsonl")
    pre=_read_jsonl(Path(state_dir)/"pre_run_duplicate_blocks.jsonl")
    branches=_read_json(Path(state_dir)/"branch_exhaustion.json", {"branches":{}}) or {"branches":{}}
    idx=_read_json(Path(state_dir)/"strategy_effect_index.json", {}) or {}
    batch=_read_json(Path(state_dir)/"batch_state.json", {}) or {}
    recent=ledger[-last_n:]
    values=Counter(str(r.get("value_delivered") or "unknown") for r in recent)
    flags=Counter()
    for r in recent:
        for f in r.get("flags", []) or []: flags[str(f)] += 1
    exhausted=[k for k,v in (branches.get("branches") or {}).items() if v.get("status")=="exhausted"]
    rec=[]
    if values.get("duplicate_blocked",0) and not pre: rec.append("Duplicates are still discovered after backtest; verify pre_run_duplicate_guard is active.")
    if values.get("duplicate_blocked",0) >= 3: rec.append("Duplicate storm detected; tighten strategy-effect/branch guards.")
    if values.get("rejected_with_learning",0) >= 8: rec.append("Many rejections; shift generator to new families or mark exhausted branches.")
    if "max_recovery_cycles_reached" in str(batch.get("stop_reason")): rec.append("Recovery generated selectable hypotheses but quality stayed weak; tighten selector.")
    return {"last_n":last_n,"ledger_events":len(ledger),"recent_value_counts":dict(values),"recent_flags":dict(flags),"pre_run_duplicate_blocks":len(pre),"strategy_effect_signatures":len(idx.get("signatures",{}) or {}),"strategy_effect_runs_indexed":len(idx.get("runs",{}) or {}),"exhausted_branches":exhausted,"batch_status":batch.get("status"),"batch_stop_reason":batch.get("stop_reason"),"batch_completed":batch.get("completed"),"recommendations":rec}

def write_autonomy_quality_report(*, state_dir: str | Path="state", reports_dir: str | Path="reports", runs_dir: str | Path="runs", last_n: int=30) -> dict[str, Any]:
    report=build_autonomy_quality_report(state_dir=state_dir, reports_dir=reports_dir, runs_dir=runs_dir, last_n=last_n)
    out=Path(reports_dir); out.mkdir(parents=True, exist_ok=True)
    (out/"autonomy_quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines=["# Autonomy Quality Report","",f"- Batch status: `{report.get('batch_status')}`",f"- Stop reason: `{report.get('batch_stop_reason')}`",f"- Completed: {report.get('batch_completed')}",f"- Ledger events: {report.get('ledger_events')}",f"- Pre-run duplicate blocks: {report.get('pre_run_duplicate_blocks')}",f"- Strategy-effect signatures: {report.get('strategy_effect_signatures')}",f"- Exhausted branches: {len(report.get('exhausted_branches') or [])}","","## Recent value delivered",""]
    for k,v in sorted((report.get("recent_value_counts") or {}).items()): lines.append(f"- `{k}`: {v}")
    lines += ["","## Recommendations",""]
    lines += [f"- {x}" for x in report["recommendations"]] if report.get("recommendations") else ["- No major autonomy-quality warning detected."]
    (out/"autonomy_quality_report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return report

def main() -> int:
    import argparse, json
    p=argparse.ArgumentParser(); p.add_argument("--state-dir", default="state"); p.add_argument("--reports-dir", default="reports"); p.add_argument("--runs-dir", default="runs"); p.add_argument("--last-n", type=int, default=30)
    a=p.parse_args(); r=write_autonomy_quality_report(state_dir=a.state_dir, reports_dir=a.reports_dir, runs_dir=a.runs_dir, last_n=a.last_n)
    print(json.dumps({"written":True,"recommendations":r.get("recommendations", [])}, ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
