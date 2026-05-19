"""Pre-run duplicate guard."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.consumed_hypotheses import append_consumed_hypothesis
from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature, strategy_effect_summary
from scripts.research.branch_exhaustion import is_branch_exhausted, rebuild_branch_exhaustion

INDEX_FILE = "strategy_effect_index.json"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def index_path(state_dir: str | Path = "state") -> Path:
    return Path(state_dir) / INDEX_FILE

def load_index(state_dir: str | Path = "state") -> dict[str, Any]:
    return read_json(index_path(state_dir), {"version": 1, "signatures": {}}) or {"version": 1, "signatures": {}}

def save_index(state_dir: str | Path, index: dict[str, Any]) -> None:
    index["updated_at"] = now_iso()
    write_json(index_path(state_dir), index)

def _config_by_hash() -> dict[str, Path]:
    out: dict[str, Path] = {}
    root = Path("configs")
    if not root.exists():
        return out
    for path in root.rglob("*.json"):
        try:
            out[sha256_file(path)] = path
        except OSError:
            continue
    return out

def rebuild_strategy_effect_index(*, state_dir: str | Path = "state", runs_dir: str | Path = "runs") -> dict[str, Any]:
    by_hash = _config_by_hash()
    signatures: dict[str, Any] = {}
    for run_dir in sorted(Path(runs_dir).glob("*_*")):
        if not run_dir.is_dir():
            continue
        manifest = read_json(run_dir / "run_manifest.json", {}) or {}
        audit = read_json(run_dir / "audit.json", {}) or {}
        cfg_path = by_hash.get(str(manifest.get("config_hash")))
        if not cfg_path or not cfg_path.exists():
            continue
        cfg = read_json(cfg_path, {}) or {}
        sig = strategy_effect_signature(cfg)
        row = signatures.setdefault(sig, {
            "first_run_id": run_dir.name,
            "first_strategy_id": cfg.get("strategy_id"),
            "first_hypothesis_id": manifest.get("hypothesis_id") or cfg.get("hypothesis_id"),
            "config_path": str(cfg_path),
            "summary": strategy_effect_summary(cfg),
            "runs": [],
        })
        row["runs"].append({
            "run_id": run_dir.name,
            "decision": audit.get("decision"),
            "strategy_id": cfg.get("strategy_id"),
            "hypothesis_id": manifest.get("hypothesis_id") or cfg.get("hypothesis_id"),
        })
    index = {"version": 1, "updated_at": now_iso(), "signatures": signatures}
    save_index(state_dir, index)
    return {"path": str(index_path(state_dir)), "signatures": len(signatures)}

def _append_guard_event(*, state_dir: str | Path, run_id: str, hypothesis_id: str | None, family: str | None, reason: str, signature: str | None = None, branch: str | None = None) -> None:
    path = Path(state_dir) / "pre_run_guard_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "created_at": now_iso(),
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "reason": reason,
        "signature": signature,
        "branch": branch,
        "value_delivered": "pre_run_guard_blocked",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")

def check_pre_run_duplicate_guard(*, run_id: str, strategy_config_path: str | Path, state_dir: str | Path = "state", runs_dir: str | Path = "runs", hypothesis_id: str | None = None, family: str | None = None, rebuild_index: bool = True, consume_on_block: bool = True) -> dict[str, Any]:
    cfg = read_json(strategy_config_path, {}) or {}
    sig = strategy_effect_signature(cfg)
    if rebuild_index:
        rebuild_strategy_effect_index(state_dir=state_dir, runs_dir=runs_dir)
        rebuild_branch_exhaustion(state_dir=state_dir, runs_dir=runs_dir)
    index = load_index(state_dir)
    existing = (index.get("signatures") or {}).get(sig)
    if existing:
        reason = f"duplicate_strategy_signature_pre_run:{existing.get('first_run_id')}"
        hid = hypothesis_id or cfg.get("hypothesis_id") or cfg.get("strategy_id")
        fam = family or cfg.get("strategy_family")
        if consume_on_block:
            append_consumed_hypothesis(state_dir=state_dir, run_id=run_id, hypothesis_id=hid, family=fam, decision="pre_run_guard_blocked", value_delivered="duplicate_strategy_signature_pre_run", source="pre_run_duplicate_guard")
        _append_guard_event(state_dir=state_dir, run_id=run_id, hypothesis_id=hid, family=fam, reason=reason, signature=sig)
        return {"blocked": True, "reason": reason, "signature": sig, "existing": existing}
    branch = is_branch_exhausted(state_dir=state_dir, strategy_config=cfg, family=family or cfg.get("strategy_family"))
    if branch.get("exhausted"):
        reason = f"branch_exhausted_pre_run:{branch.get('branch')}"
        hid = hypothesis_id or cfg.get("hypothesis_id") or cfg.get("strategy_id")
        fam = family or cfg.get("strategy_family")
        if consume_on_block:
            append_consumed_hypothesis(state_dir=state_dir, run_id=run_id, hypothesis_id=hid, family=fam, decision="pre_run_guard_blocked", value_delivered="branch_exhausted_pre_run", source="pre_run_duplicate_guard")
        _append_guard_event(state_dir=state_dir, run_id=run_id, hypothesis_id=hid, family=fam, reason=reason, signature=sig, branch=branch.get("branch"))
        return {"blocked": True, "reason": reason, "signature": sig, "branch": branch}
    return {"blocked": False, "reason": "new_strategy_signature", "signature": sig, "summary": strategy_effect_summary(cfg)}

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--strategy-config", required=True)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--hypothesis-id", default=None)
    p.add_argument("--family", default=None)
    args = p.parse_args()
    result = check_pre_run_duplicate_guard(run_id=args.run_id, strategy_config_path=args.strategy_config, state_dir=args.state_dir, runs_dir=args.runs_dir, hypothesis_id=args.hypothesis_id, family=args.family)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 3 if result.get("blocked") else 0

if __name__ == "__main__":
    raise SystemExit(main())
