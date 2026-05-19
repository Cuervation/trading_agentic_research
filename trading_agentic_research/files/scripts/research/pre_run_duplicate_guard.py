"Pre-run duplicate/branch guard."
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.consumed_hypotheses import append_consumed_hypothesis
from scripts.research.strategy_effect_signature import (
    read_json,
    strategy_effect_signature,
    strategy_effect_summary,
    branch_for_config,
)
from scripts.research.branch_exhaustion import (
    is_branch_exhausted,
    record_branch_event,
    refresh_branch_exhaustion,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def _iter_config_files(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    root = repo_root / "configs"
    if root.exists():
        for path in root.rglob("*.json"):
            if path.name.lower() in {"project_config.json", "strategy_registry.json"}:
                continue
            out.append(path)
    return sorted(set(out))


def _config_catalog(repo_root: Path) -> dict[str, Any]:
    by_file_hash: dict[str, dict[str, Any]] = {}
    by_strategy_id: dict[str, dict[str, Any]] = {}
    by_hypothesis_id: dict[str, dict[str, Any]] = {}
    for path in _iter_config_files(repo_root):
        cfg = read_json(path, None)
        if not isinstance(cfg, dict):
            continue
        try:
            file_hash = sha256_file(path)
        except OSError:
            continue
        sig = strategy_effect_signature(cfg)
        entry = {
            "path": str(path.relative_to(repo_root)) if path.is_relative_to(repo_root) else str(path),
            "file_hash": file_hash,
            "signature": sig,
            "strategy_id": cfg.get("strategy_id"),
            "hypothesis_id": cfg.get("hypothesis_id"),
            "summary": strategy_effect_summary(cfg),
        }
        by_file_hash[file_hash] = entry
        if cfg.get("strategy_id"):
            by_strategy_id[str(cfg.get("strategy_id"))] = entry
        if cfg.get("hypothesis_id"):
            by_hypothesis_id[str(cfg.get("hypothesis_id"))] = entry
    return {"by_file_hash": by_file_hash, "by_strategy_id": by_strategy_id, "by_hypothesis_id": by_hypothesis_id}


def build_strategy_effect_index(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).resolve()
    catalog = _config_catalog(root)
    entries: dict[str, dict[str, Any]] = {}

    for run_dir in sorted(Path(runs_dir).glob("*_*")):
        if not run_dir.is_dir():
            continue
        manifest = read_json(run_dir / "run_manifest.json", {}) or {}
        audit = read_json(run_dir / "audit.json", {}) or {}
        strategy_id = str(manifest.get("strategy_id") or "")
        hypothesis_id = str(manifest.get("hypothesis_id") or "")
        config_hash = str(manifest.get("config_hash") or "")

        cfg_entry = catalog["by_file_hash"].get(config_hash) if config_hash else None
        if cfg_entry is None and strategy_id:
            cfg_entry = catalog["by_strategy_id"].get(strategy_id)
        if cfg_entry is None and hypothesis_id:
            cfg_entry = catalog["by_hypothesis_id"].get(hypothesis_id)
        if cfg_entry is None:
            continue

        sig = cfg_entry["signature"]
        item = entries.setdefault(sig, {
            "signature": sig,
            "first_run_id": run_dir.name,
            "runs": [],
            "config": cfg_entry,
            "last_seen_at": now_iso(),
        })
        item["runs"].append({
            "run_id": run_dir.name,
            "strategy_id": strategy_id,
            "hypothesis_id": hypothesis_id,
            "decision": audit.get("decision"),
            "flags": audit.get("flags", []),
            "duplicate_against": (audit.get("artifact_hashes") or {}).get("duplicate_run_id"),
        })

    payload = {"version": 1, "generated_at": now_iso(), "entries": entries}
    write_json(Path(state_dir) / "strategy_effect_index.json", payload)
    return payload


def _block(
    *,
    state_dir: str | Path,
    attempted_run_id: str,
    hypothesis_id: str | None,
    family: str | None,
    branch: str,
    value_delivered: str,
    reason: str,
    duplicate_against: str | None = None,
) -> dict[str, Any]:
    append_consumed_hypothesis(
        state_dir=state_dir,
        run_id=attempted_run_id,
        hypothesis_id=hypothesis_id,
        family=family,
        decision="rejected",
        value_delivered=value_delivered,
        source="pre_run_duplicate_guard",
    )
    row = {
        "created_at": now_iso(),
        "run_id": attempted_run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "branch": branch,
        "value_delivered": value_delivered,
        "reason": reason,
        "duplicate_against": duplicate_against,
    }
    append_jsonl(Path(state_dir) / "pre_run_duplicate_blocks.jsonl", row)
    record_branch_event(
        state_dir=state_dir,
        run_id=attempted_run_id,
        hypothesis_id=hypothesis_id,
        branch=branch,
        value_delivered=value_delivered,
        reason=reason,
    )
    write_json(Path(state_dir) / "research_state.json", {
        "loop_status": "blocked_duplicate_pre_run",
        "last_run_id": attempted_run_id,
        "mode": "automatic_loop",
        "notes": [reason],
        "updated_at": now_iso(),
    })
    return {
        "blocked": True,
        "reason": reason,
        "value_delivered": value_delivered,
        "duplicate_against": duplicate_against,
        "branch": branch,
    }


def check_pre_run_duplicate_guard(
    *,
    strategy_config_path: str | Path,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    hypothesis_id: str | None = None,
    family: str | None = None,
    attempted_run_id: str = "PRE_RUN",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    cfg = read_json(strategy_config_path, None)
    if not isinstance(cfg, dict):
        return {"blocked": False, "reason": "missing_or_invalid_strategy_config"}

    sig = strategy_effect_signature(cfg)
    branch = branch_for_config(cfg, hypothesis_id=hypothesis_id or cfg.get("hypothesis_id"))
    refresh_branch_exhaustion(state_dir)

    branch_status = is_branch_exhausted(branch, state_dir=state_dir)
    if branch_status.get("exhausted"):
        return _block(
            state_dir=state_dir,
            attempted_run_id=attempted_run_id,
            hypothesis_id=hypothesis_id or cfg.get("hypothesis_id"),
            family=family or cfg.get("strategy_family"),
            branch=branch,
            value_delivered="branch_exhausted_pre_run",
            reason=f"branch_exhausted_pre_run:{branch}",
        )

    index = build_strategy_effect_index(state_dir=state_dir, runs_dir=runs_dir, repo_root=repo_root)
    existing = (index.get("entries") or {}).get(sig)
    if existing and existing.get("runs"):
        first_run_id = str(existing.get("first_run_id") or existing["runs"][0].get("run_id"))
        return _block(
            state_dir=state_dir,
            attempted_run_id=attempted_run_id,
            hypothesis_id=hypothesis_id or cfg.get("hypothesis_id"),
            family=family or cfg.get("strategy_family"),
            branch=branch,
            value_delivered="duplicate_pre_run_blocked",
            reason=f"duplicate_strategy_signature_pre_run:{first_run_id}",
            duplicate_against=first_run_id,
        )

    return {"blocked": False, "signature": sig, "branch": branch, "summary": strategy_effect_summary(cfg)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy-config", required=True)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--hypothesis-id", default=None)
    p.add_argument("--family", default=None)
    p.add_argument("--attempted-run-id", default="PRE_RUN")
    args = p.parse_args()
    print(json.dumps(check_pre_run_duplicate_guard(
        strategy_config_path=args.strategy_config,
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        attempted_run_id=args.attempted_run_id,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
