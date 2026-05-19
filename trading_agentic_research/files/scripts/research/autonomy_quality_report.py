"Generate a lightweight autonomy quality report."
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


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
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_report(state_dir: str | Path = "state", reports_dir: str | Path = "reports", last_n: int = 40) -> str:
    ledger = read_jsonl(Path(state_dir) / "research_ledger.jsonl")[-last_n:]
    pre = read_jsonl(Path(state_dir) / "pre_run_duplicate_blocks.jsonl")[-last_n:]
    branch = read_json(Path(state_dir) / "branch_exhaustion.json", {"branches": {}}) or {"branches": {}}
    effect = read_json(Path(state_dir) / "strategy_effect_index.json", {"entries": {}}) or {"entries": {}}
    values = Counter(str(row.get("value_delivered") or row.get("decision") or "unknown") for row in ledger)
    pre_values = Counter(str(row.get("value_delivered") or "unknown") for row in pre)
    exhausted = [k for k, v in (branch.get("branches") or {}).items() if v.get("status") == "exhausted"]

    lines = ["# Autonomy Quality Report", "", f"- Ledger rows analyzed: {len(ledger)}", f"- Pre-run blocks analyzed: {len(pre)}", f"- Strategy effect signatures indexed: {len(effect.get('entries') or {})}", f"- Exhausted branches: {len(exhausted)}", "", "## Recent value delivered"]
    if values:
        lines.extend([f"- {k}: {v}" for k, v in values.most_common()])
    else:
        lines.append("- none")
    lines += ["", "## Pre-run blocks"]
    if pre_values:
        lines.extend([f"- {k}: {v}" for k, v in pre_values.most_common()])
    else:
        lines.append("- none")
    lines += ["", "## Exhausted branches"]
    if exhausted:
        for b in exhausted[:30]:
            info = branch["branches"][b]
            lines.append(f"- {b}: {info.get('reason')} duplicate={info.get('duplicate_count_recent')} bad={info.get('bad_count_recent')}")
    else:
        lines.append("- none")
    text = "\n".join(lines) + "\n"
    out = Path(reports_dir) / "autonomy_quality_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return str(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--last-n", type=int, default=40)
    args = p.parse_args()
    print(json.dumps({"output": build_report(args.state_dir, args.reports_dir, args.last_n)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
