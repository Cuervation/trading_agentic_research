"""Branch exhaustion memory for autonomous feature-space search."""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRANCH_FILE = "branch_exhaustion.json"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError: return default

def write_json(path: str | Path, payload: Any) -> None:
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

def branch_state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / BRANCH_FILE

def load_branch_state(state_dir: str | Path="state") -> dict[str, Any]:
    payload=read_json(branch_state_path(state_dir), None)
    if not isinstance(payload, dict):
        payload={"version":1,"branches":{},"updated_at":now_iso()}
    payload.setdefault("branches", {})
    return payload

def save_branch_state(state_dir: str | Path, state: dict[str, Any]) -> None:
    state["updated_at"]=now_iso(); write_json(branch_state_path(state_dir), state)

def _slug(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "unknown").lower()).strip("_")

def branch_key_for_candidate(*, family: str | None, axis: str | None, field: str | None=None, layer: str | None=None) -> str:
    parts=[_slug(family), _slug(axis)]
    if field: parts.append(_slug(field))
    if layer: parts.append(_slug(layer))
    return "/".join([p for p in parts if p and p!="unknown"])

def infer_branch_key(*, hypothesis_id: str | None, family: str | None=None, axis: str | None=None) -> str:
    hid=str(hypothesis_id or "")
    field=None; layer=None
    m=re.search(r"_RANK_(.+?)(?:_TOPN|_EXIT|_CONF|_MKT|_V\d|$)", hid)
    if m: field=m.group(1)
    if "_TOPN_" in hid: layer="rank_topn"
    elif "_EXIT_" in hid: layer="rank_exit"
    elif "_CONF_" in hid: layer="rank_confirmation"
    elif "_MKT_" in hid or "_SPY_" in hid: layer="rank_market_filter"
    elif "_RANK_" in hid: layer="pure_ranking"
    return branch_key_for_candidate(family=family, axis=axis or layer, field=field, layer=layer)

def is_branch_exhausted(state_dir: str | Path, branch_key: str) -> bool:
    row=(load_branch_state(state_dir).get("branches") or {}).get(branch_key, {})
    return str(row.get("status")) == "exhausted"

def update_branch_exhaustion_after_run(*, state_dir: str | Path, run_id: str, hypothesis_id: str | None, family: str | None, audit: dict[str, Any], duplicate_threshold: int=2, rejected_threshold: int=4, window: int=12) -> dict[str, Any]:
    state=load_branch_state(state_dir)
    key=infer_branch_key(hypothesis_id=hypothesis_id, family=family, axis=None)
    if not key: return {"updated":False,"reason":"missing_branch_key"}
    row=state.setdefault("branches", {}).setdefault(key, {"branch_key":key,"status":"active","events":[],"duplicate_count":0,"rejected_count":0,"last_updated_at":now_iso()})
    flags=set(audit.get("flags", []) or [])
    is_dup=bool(audit.get("duplicate_result") or "duplicate_result" in flags or "duplicate_artifact" in flags)
    decision=str(audit.get("decision") or "")
    ev={"created_at":now_iso(),"run_id":run_id,"hypothesis_id":hypothesis_id,"family":family,"decision":decision,"is_duplicate":is_dup,"flags":sorted(flags)}
    events=[e for e in (row.get("events") or []) if e.get("run_id") != run_id]
    events.append(ev); events=events[-window:]
    row["events"]=events
    row["duplicate_count"]=sum(1 for e in events if e.get("is_duplicate"))
    row["rejected_count"]=sum(1 for e in events if e.get("decision")=="rejected")
    row["last_updated_at"]=now_iso()
    if row["duplicate_count"] >= duplicate_threshold:
        row["status"]="exhausted"; row["reason"]=f"duplicate_threshold_reached:{row['duplicate_count']}"
    elif row["rejected_count"] >= rejected_threshold:
        row["status"]="exhausted"; row["reason"]=f"rejected_threshold_reached:{row['rejected_count']}"
    else:
        row.setdefault("status", "active")
    save_branch_state(state_dir, state)
    return {"updated":True,"branch_key":key,"status":row.get("status"),"reason":row.get("reason")}
