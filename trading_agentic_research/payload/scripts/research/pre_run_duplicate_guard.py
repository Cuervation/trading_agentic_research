"""Pre-run duplicate guard for autonomous research.

Artifact duplicate detection is still authoritative after a run completes, but it
is too late to save runtime.  This module keeps a light index of canonical
strategy-effect signatures so the batch can skip configs that have already been
executed or preflight-blocked.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.consumed_hypotheses import append_consumed_hypothesis, read_jsonl
from scripts.research.strategy_effect_signature import (
    read_json,
    stable_json,
    strategy_effect_signature_from_path,
)

INDEX_FILE = "strategy_effect_index.json"
PREFLIGHT_FILE = "preflight_blocked_hypotheses.jsonl"
LEDGER_FILE = "research_ledger.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    return len(rows)


def effect_index_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / INDEX_FILE


def empty_index() -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "signatures": {},
        "hypotheses": {},
    }


def load_strategy_effect_index(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(effect_index_path(state_dir), None)
    if not isinstance(payload, dict):
        return empty_index()
    payload.setdefault("version", 1)
    payload.setdefault("signatures", {})
    payload.setdefault("hypotheses", {})
    return payload


def save_strategy_effect_index(state_dir: str | Path, index: dict[str, Any]) -> None:
    index["updated_at"] = now_iso()
    write_json(effect_index_path(state_dir), index)


def _repo_path(path: str | Path, repo_root: str | Path = ".") -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(repo_root) / p


def _config_paths_from_registry(strategy_registry_path: str | Path, repo_root: str | Path = ".") -> list[Path]:
    registry = read_json(strategy_registry_path, {}) or {}
    out: list[Path] = []
    for row in registry.get("strategies", []) or []:
        config_path = row.get("config_path")
        if not config_path:
            continue
        p = _repo_path(config_path, repo_root)
        if p.exists() and p.is_file():
            out.append(p)
    return out


def _resolve_config_for_hypothesis(
    *,
    hypothesis_id: str,
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    repo_root: str | Path = ".",
) -> Path | None:
    root = Path(repo_root)
    for p in _config_paths_from_registry(_repo_path(strategy_registry_path, root), root):
        cfg = read_json(p, {}) or {}
        if str(cfg.get("hypothesis_id") or cfg.get("strategy_id") or "") == str(hypothesis_id):
            return p
    for raw in [Path(generated_configs_dir) / f"{hypothesis_id}.json", Path("configs") / f"{hypothesis_id}.json"]:
        p = _repo_path(raw, root)
        if p.exists():
            return p
    return None


def upsert_strategy_effect_signature(
    *,
    state_dir: str | Path,
    strategy_config_path: str | Path,
    run_id: str | None,
    hypothesis_id: str | None,
    family: str | None = None,
    decision: str | None = None,
    value_delivered: str | None = None,
    source: str = "unknown",
) -> dict[str, Any]:
    sig_info = strategy_effect_signature_from_path(strategy_config_path)
    signature = sig_info["strategy_effect_signature"]
    index = load_strategy_effect_index(state_dir)
    entry = index.setdefault("signatures", {}).get(signature)
    now = now_iso()
    if not entry:
        entry = {
            "strategy_effect_signature": signature,
            "first_seen_at": now,
            "first_seen_run_id": run_id,
            "first_seen_hypothesis_id": hypothesis_id or sig_info.get("hypothesis_id"),
            "first_seen_config_path": str(strategy_config_path),
            "canonical_effect": sig_info.get("canonical_effect"),
            "runs": [],
            "hypotheses": [],
            "sources": [],
        }
        index["signatures"][signature] = entry

    if run_id and run_id not in entry.setdefault("runs", []):
        entry["runs"].append(run_id)
    hid = str(hypothesis_id or sig_info.get("hypothesis_id") or "")
    if hid and hid not in entry.setdefault("hypotheses", []):
        entry["hypotheses"].append(hid)
    if source and source not in entry.setdefault("sources", []):
        entry["sources"].append(source)
    entry["last_seen_at"] = now
    entry["last_decision"] = decision
    entry["last_value_delivered"] = value_delivered

    if hid:
        index.setdefault("hypotheses", {})[hid] = {
            "strategy_effect_signature": signature,
            "config_path": str(strategy_config_path),
            "run_id": run_id,
            "family": family or sig_info.get("family"),
            "decision": decision,
            "value_delivered": value_delivered,
            "updated_at": now,
        }
    save_strategy_effect_index(state_dir, index)
    return {"updated": True, "signature": signature, "entry": entry, "index_path": str(effect_index_path(state_dir))}


def sync_strategy_effect_index_from_consumed(
    *,
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    repo_root: str | Path = ".",
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Backfill strategy-effect signatures from consumed hypotheses/configs.

    This makes the pre-run guard useful immediately with existing history.
    """
    rows = read_jsonl(Path(state_dir) / "consumed_hypotheses.jsonl")
    if max_rows is not None:
        rows = rows[-int(max_rows):]
    synced = 0
    missing: list[str] = []
    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        if not hid:
            continue
        cfg_path = _resolve_config_for_hypothesis(
            hypothesis_id=hid,
            strategy_registry_path=strategy_registry_path,
            generated_configs_dir=generated_configs_dir,
            repo_root=repo_root,
        )
        if not cfg_path:
            missing.append(hid)
            continue
        upsert_strategy_effect_signature(
            state_dir=state_dir,
            strategy_config_path=cfg_path,
            run_id=row.get("run_id"),
            hypothesis_id=hid,
            family=row.get("family"),
            decision=row.get("decision"),
            value_delivered=row.get("value_delivered"),
            source="sync_from_consumed",
        )
        synced += 1
    return {"synced": synced, "missing_config_count": len(missing), "missing_examples": missing[:20]}


def preflight_strategy_effect_duplicate(
    *,
    strategy_config_path: str | Path,
    state_dir: str | Path = "state",
    hypothesis_id: str | None = None,
    allow_same_hypothesis: bool = False,
) -> dict[str, Any]:
    sig_info = strategy_effect_signature_from_path(strategy_config_path)
    signature = sig_info["strategy_effect_signature"]
    hid = str(hypothesis_id or sig_info.get("hypothesis_id") or "")
    index = load_strategy_effect_index(state_dir)
    entry = index.get("signatures", {}).get(signature)
    if not entry:
        return {"blocked": False, "reason": "new_strategy_effect_signature", **sig_info}

    known_hypotheses = [str(x) for x in entry.get("hypotheses", []) if x]
    known_runs = [str(x) for x in entry.get("runs", []) if x]
    same_hypothesis_only = hid and set(known_hypotheses) == {hid}
    if allow_same_hypothesis and same_hypothesis_only:
        return {"blocked": False, "reason": "same_hypothesis_allowed", "known_entry": entry, **sig_info}

    return {
        "blocked": True,
        "reason": "duplicate_strategy_effect_signature",
        "strategy_effect_signature": signature,
        "hypothesis_id": hid,
        "duplicate_of_hypothesis_id": entry.get("first_seen_hypothesis_id"),
        "duplicate_of_run_id": entry.get("first_seen_run_id") or (known_runs[0] if known_runs else None),
        "known_hypotheses": known_hypotheses,
        "known_runs": known_runs,
        "known_entry": entry,
        "canonical_effect": sig_info.get("canonical_effect"),
    }


def mark_preflight_duplicate_consumed(
    *,
    state_dir: str | Path,
    hypothesis_id: str,
    family: str | None,
    duplicate_check: dict[str, Any],
    source: str = "pre_run_duplicate_guard",
) -> dict[str, Any]:
    pseudo_run_id = f"PRE_RUN_DUP_{hypothesis_id}"
    consumed = append_consumed_hypothesis(
        state_dir=state_dir,
        run_id=pseudo_run_id,
        hypothesis_id=hypothesis_id,
        family=family,
        decision="rejected",
        value_delivered="duplicate_preflight_blocked",
        source=source,
    )
    row = {
        "created_at": now_iso(),
        "source": source,
        "run_id": pseudo_run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "decision": "rejected",
        "value_delivered": "duplicate_preflight_blocked",
        "reason": duplicate_check.get("reason"),
        "duplicate_of_run_id": duplicate_check.get("duplicate_of_run_id"),
        "duplicate_of_hypothesis_id": duplicate_check.get("duplicate_of_hypothesis_id"),
        "strategy_effect_signature": duplicate_check.get("strategy_effect_signature"),
    }
    append_jsonl(Path(state_dir) / PREFLIGHT_FILE, [row])
    append_jsonl(Path(state_dir) / LEDGER_FILE, [{
        "event_id": f"LEDGER_{pseudo_run_id}",
        "created_at": row["created_at"],
        "run_id": pseudo_run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "decision": "rejected",
        "value_delivered": "duplicate_preflight_blocked",
        "learned": f"{hypothesis_id} was blocked before backtest because its canonical strategy effect duplicated {row.get('duplicate_of_hypothesis_id') or row.get('duplicate_of_run_id')}.",
        "next_action": "select_different_strategy_effect_signature",
        "strategy_effect_signature": row.get("strategy_effect_signature"),
        "duplicate_of_run_id": row.get("duplicate_of_run_id"),
        "duplicate_of_hypothesis_id": row.get("duplicate_of_hypothesis_id"),
    }])
    return {"blocked": True, "consumed": consumed, "row": row}


def register_strategy_effect_from_run(
    *,
    state_dir: str | Path,
    strategy_config_path: str | Path,
    run_id: str,
    hypothesis_id: str,
    family: str | None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = audit or {}
    value = "duplicate_blocked" if audit.get("duplicate_result") else ("metric_no_effect_blocked" if "metric_no_effect" in (audit.get("flags") or []) else audit.get("decision"))
    return upsert_strategy_effect_signature(
        state_dir=state_dir,
        strategy_config_path=strategy_config_path,
        run_id=run_id,
        hypothesis_id=hypothesis_id,
        family=family,
        decision=audit.get("decision"),
        value_delivered=value,
        source="completed_run",
    )


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Pre-run duplicate guard for a strategy config.")
    p.add_argument("--strategy-config", required=True)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--hypothesis-id", default=None)
    args = p.parse_args()
    print(json.dumps(preflight_strategy_effect_duplicate(
        strategy_config_path=args.strategy_config,
        state_dir=args.state_dir,
        hypothesis_id=args.hypothesis_id,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
