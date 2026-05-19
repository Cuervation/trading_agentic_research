"""Pre-run duplicate guard for autonomous backtests."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.consumed_hypotheses import append_consumed_hypothesis
from scripts.research.strategy_effect_signature import read_json, strategy_effect_signature_from_path

INDEX_FILE = "strategy_effect_index.json"
BLOCKS_FILE = "pre_run_duplicate_blocks.jsonl"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")

def index_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / INDEX_FILE

def empty_index() -> dict[str, Any]:
    return {"version": 1, "created_at": now_iso(), "updated_at": now_iso(), "signatures": {}, "config_hashes": {}, "runs": {}, "blocked_attempts": []}

def load_index(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(index_path(state_dir), None)
    if not isinstance(payload, dict):
        return empty_index()
    payload.setdefault("signatures", {}); payload.setdefault("config_hashes", {}); payload.setdefault("runs", {}); payload.setdefault("blocked_attempts", [])
    return payload

def save_index(state_dir: str | Path, index: dict[str, Any]) -> None:
    index["updated_at"] = now_iso()
    write_json(index_path(state_dir), index)

def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists(): return []
    rows=[]
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try: rows.append(json.loads(line))
            except json.JSONDecodeError: pass
    return rows

def _registry_lookup(repo_root: Path, registry_path: str | Path) -> dict[str, Path]:
    p = Path(registry_path)
    if not p.is_absolute(): p = repo_root / p
    registry = read_json(p, {}) or {}
    out={}
    for row in registry.get("strategies", []) or []:
        sid, cp = row.get("strategy_id"), row.get("config_path")
        if sid and cp:
            q = Path(cp)
            if not q.is_absolute(): q = repo_root / q
            out[str(sid)] = q
    return out

def _candidate_config_paths(repo_root: Path, manifest: dict[str, Any], strategy_registry_path: str | Path) -> list[Path]:
    ids=[]
    for k in ("hypothesis_id","strategy_id"):
        v=manifest.get(k)
        if v and str(v) not in ids: ids.append(str(v))
    paths=[]
    for v in ids:
        paths += [repo_root/"configs"/"generated"/f"{v}.json", repo_root/"configs"/f"{v}.json"]
    reg=_registry_lookup(repo_root, strategy_registry_path)
    for v in ids:
        if v in reg: paths.append(reg[v])
    seen=set(); out=[]
    for p in paths:
        key=str(p)
        if key not in seen:
            out.append(p); seen.add(key)
    return out

def _add_signature_entry(index: dict[str, Any], *, run_id: str, info: dict[str, Any], audit: dict[str, Any] | None = None) -> None:
    audit=audit or {}
    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
    flags=audit.get("flags") or []
    value = "duplicate_blocked" if (audit.get("duplicate_result") or "duplicate_result" in flags or "duplicate_artifact" in flags) else audit.get("decision")
    index.setdefault("runs", {})[run_id] = {
        "run_id": run_id, "strategy_effect_signature": sig, "config_hash": cfg_hash,
        "strategy_id": info.get("strategy_id"), "hypothesis_id": info.get("hypothesis_id"),
        "strategy_family": info.get("strategy_family"), "config_path": info.get("config_path"),
        "decision": audit.get("decision"), "value_delivered": value, "duplicate_of_run_id": audit.get("duplicate_of_run_id"),
        "updated_at": now_iso(),
    }
    if sig:
        e=index.setdefault("signatures", {}).setdefault(sig, {"strategy_effect_signature": sig, "first_seen_run_id": run_id, "runs": [], "created_at": now_iso(), "canonical_payload": info.get("canonical_payload")})
        if run_id not in e["runs"]: e["runs"].append(run_id)
        e["updated_at"]=now_iso()
    if cfg_hash:
        e=index.setdefault("config_hashes", {}).setdefault(cfg_hash, {"config_hash": cfg_hash, "first_seen_run_id": run_id, "runs": [], "created_at": now_iso()})
        if run_id not in e["runs"]: e["runs"].append(run_id)
        e["updated_at"]=now_iso()

def rebuild_strategy_effect_index(*, state_dir: str | Path="state", runs_dir: str | Path="runs", strategy_registry_path: str | Path="configs/strategy_registry.json", repo_root: str | Path=".") -> dict[str, Any]:
    root=Path(repo_root); index=empty_index()
    for run_dir in sorted(Path(runs_dir).glob("*_*")):
        if not run_dir.is_dir(): continue
        manifest=read_json(run_dir/"run_manifest.json", {}) or {}
        audit=read_json(run_dir/"audit.json", {}) or {}
        if not manifest: continue
        info=None
        for cp in _candidate_config_paths(root, manifest, strategy_registry_path):
            if cp.exists():
                try:
                    info=strategy_effect_signature_from_path(cp); break
                except OSError:
                    pass
        if info is None and manifest.get("config_hash"):
            info={"strategy_effect_signature": None, "config_hash": manifest.get("config_hash"), "strategy_id": manifest.get("strategy_id"), "hypothesis_id": manifest.get("hypothesis_id"), "strategy_family": manifest.get("hypothesis_family"), "config_path": None, "canonical_payload": None}
        if info: _add_signature_entry(index, run_id=run_dir.name, info=info, audit=audit)
    save_index(state_dir, index)
    return index

def _ensure_index(**kwargs) -> dict[str, Any]:
    idx=load_index(kwargs["state_dir"])
    if not idx.get("runs"):
        return rebuild_strategy_effect_index(**kwargs)
    return idx

def check_pre_run_duplicate(*, strategy_config_path: str | Path, state_dir: str | Path="state", runs_dir: str | Path="runs", strategy_registry_path: str | Path="configs/strategy_registry.json", repo_root: str | Path=".", run_id: str | None=None, hypothesis_id: str | None=None, family: str | None=None) -> dict[str, Any]:
    info=strategy_effect_signature_from_path(strategy_config_path)
    index=_ensure_index(state_dir=state_dir, runs_dir=runs_dir, strategy_registry_path=strategy_registry_path, repo_root=repo_root)
    sig=info.get("strategy_effect_signature"); cfg_hash=info.get("config_hash")
    sig_entry=index.get("signatures", {}).get(sig) if sig else None
    hash_entry=index.get("config_hashes", {}).get(cfg_hash) if cfg_hash else None
    if sig_entry and sig_entry.get("runs"):
        return {"blocked": True, "reason": "duplicate_strategy_effect_signature", "duplicate_of_run_id": sig_entry.get("first_seen_run_id") or sig_entry["runs"][0], "existing_runs": sig_entry.get("runs", []), "candidate": info, "hypothesis_id": hypothesis_id, "family": family}
    if hash_entry and hash_entry.get("runs"):
        return {"blocked": True, "reason": "duplicate_config_hash", "duplicate_of_run_id": hash_entry.get("first_seen_run_id") or hash_entry["runs"][0], "existing_runs": hash_entry.get("runs", []), "candidate": info, "hypothesis_id": hypothesis_id, "family": family}
    return {"blocked": False, "candidate": info, "hypothesis_id": hypothesis_id, "family": family}

def write_blocked_duplicate_run(*, guard_result: dict[str, Any], run_id: str, runs_dir: str | Path="runs", state_dir: str | Path="state", strategy_config_path: str | Path="", project_config_path: str | Path="", weekly_file: str | Path="", daily_folder: str | Path="", parent_run_id: str | None=None, hypothesis_id: str | None=None, family: str | None=None) -> dict[str, Any]:
    run_dir=Path(runs_dir)/run_id; run_dir.mkdir(parents=True, exist_ok=True)
    cand=guard_result.get("candidate", {}) or {}; dup=guard_result.get("duplicate_of_run_id")
    audit={"audit_status":"completed_preflight_block","decision":"rejected","reasons":[f"Pre-run duplicate guard blocked this candidate: {guard_result.get('reason')}.", f"Equivalent strategy already seen in {dup}."],"blocking_issues":[],"warnings":[],"recommendation":"Skip expensive backtest; generate a materially different hypothesis.","can_move_parent":False,"can_promote_baseline":False,"flags":["duplicate_preflight_blocked","metric_no_effect"],"duplicate_result":True,"duplicate_of_run_id":dup,"pre_run_duplicate_guard":guard_result}
    manifest={"run_id":run_id,"parent_run_id":parent_run_id,"strategy_id":cand.get("strategy_id"),"hypothesis_id":hypothesis_id or cand.get("hypothesis_id"),"hypothesis_family":family or cand.get("strategy_family"),"strategy_config_path":str(strategy_config_path),"project_config_path":str(project_config_path),"weekly_file":str(weekly_file),"daily_folder":str(daily_folder),"config_hash":cand.get("config_hash"),"strategy_effect_signature":cand.get("strategy_effect_signature"),"generated_at":now_iso(),"pre_run_blocked":True}
    write_json(run_dir/"audit.json", audit); write_json(run_dir/"run_manifest.json", manifest)
    (run_dir/"summary.md").write_text(f"# Pre-run duplicate blocked\n\nDuplicate of: `{dup}`\n\nReason: `{guard_result.get('reason')}`\n", encoding="utf-8")
    consumed=append_consumed_hypothesis(state_dir=state_dir, run_id=run_id, hypothesis_id=hypothesis_id or cand.get("hypothesis_id"), family=family or cand.get("strategy_family"), decision="blocked_pre_run_duplicate", value_delivered="duplicate_preflight_blocked", source="pre_run_duplicate_guard")
    event={"created_at":now_iso(),"run_id":run_id,"hypothesis_id":hypothesis_id or cand.get("hypothesis_id"),"family":family or cand.get("strategy_family"),"reason":guard_result.get("reason"),"duplicate_of_run_id":dup,"strategy_effect_signature":cand.get("strategy_effect_signature"),"config_hash":cand.get("config_hash"),"consumed":consumed}
    append_jsonl(Path(state_dir)/BLOCKS_FILE, event)
    idx=load_index(state_dir); idx.setdefault("blocked_attempts", []).append(event); save_index(state_dir, idx)
    return event

def record_completed_strategy_effect(*, run_id: str, strategy_config_path: str | Path, state_dir: str | Path="state", runs_dir: str | Path="runs") -> dict[str, Any]:
    info=strategy_effect_signature_from_path(strategy_config_path)
    audit=read_json(Path(runs_dir)/run_id/"audit.json", {}) or {}
    idx=load_index(state_dir); _add_signature_entry(idx, run_id=run_id, info=info, audit=audit); save_index(state_dir, idx)
    return {"updated": True, "run_id": run_id, "strategy_effect_signature": info.get("strategy_effect_signature")}
