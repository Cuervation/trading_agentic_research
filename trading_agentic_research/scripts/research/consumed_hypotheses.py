"""Track hypothesis ids that already produced a run.

The selector should not run the same exact hypothesis twice unless a caller
explicitly enables retry/replay. This file is the durable memory for that rule.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONSUMED_FILE = "consumed_hypotheses.jsonl"


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


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
            written += 1
    return written


def consumed_path(state_dir: str | Path = "state") -> Path:
    return Path(state_dir) / CONSUMED_FILE


def consumed_hypothesis_ids(state_dir: str | Path = "state") -> set[str]:
    return {
        str(row.get("hypothesis_id"))
        for row in read_jsonl(consumed_path(state_dir))
        if row.get("hypothesis_id")
    }


def append_consumed_hypothesis(
    *,
    state_dir: str | Path = "state",
    run_id: str,
    hypothesis_id: str | None,
    family: str | None = None,
    decision: str | None = None,
    value_delivered: str | None = None,
    source: str = "evaluate_candidate",
) -> dict[str, Any]:
    if not hypothesis_id:
        return {"written": 0, "reason": "missing_hypothesis_id"}
    ids = consumed_hypothesis_ids(state_dir)
    if str(hypothesis_id) in ids:
        return {"written": 0, "reason": "already_consumed", "hypothesis_id": str(hypothesis_id)}

    row = {
        "created_at": now_iso(),
        "run_id": run_id,
        "hypothesis_id": str(hypothesis_id),
        "family": family,
        "decision": decision,
        "value_delivered": value_delivered,
        "source": source,
    }
    append_jsonl(consumed_path(state_dir), [row])
    return {"written": 1, "hypothesis_id": str(hypothesis_id), "path": str(consumed_path(state_dir))}


def rebuild_consumed_from_runs(*, runs_dir: str | Path = "runs", state_dir: str | Path = "state") -> dict[str, Any]:
    """Rebuild consumed hypotheses from run manifests/audits.

    This is idempotent: it only appends hypothesis ids that are not already in
    state/consumed_hypotheses.jsonl.
    """
    existing = consumed_hypothesis_ids(state_dir)
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(Path(runs_dir).glob("*_*")):
        if not run_dir.is_dir():
            continue
        manifest = read_json(run_dir / "run_manifest.json", {}) or {}
        audit = read_json(run_dir / "audit.json", {}) or {}
        hypothesis_id = manifest.get("hypothesis_id") or manifest.get("strategy_id") or audit.get("hypothesis_id")
        if not hypothesis_id or str(hypothesis_id) in existing:
            continue
        row = {
            "created_at": now_iso(),
            "run_id": run_dir.name,
            "hypothesis_id": str(hypothesis_id),
            "family": manifest.get("family") or manifest.get("strategy_family"),
            "decision": audit.get("decision"),
            "value_delivered": None,
            "source": "rebuild_consumed_from_runs",
        }
        rows.append(row)
        existing.add(str(hypothesis_id))
    written = append_jsonl(consumed_path(state_dir), rows)
    return {"written": written, "path": str(consumed_path(state_dir))}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--state-dir", default="state")
    args = p.parse_args()
    print(json.dumps(rebuild_consumed_from_runs(runs_dir=args.runs_dir, state_dir=args.state_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
