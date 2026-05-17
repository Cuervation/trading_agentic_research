"""Global artifact signature index for research runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.governance import ARTIFACT_HASH_FILES, artifact_hashes, stable_json_hash


def read_json(path: str | Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_artifact_signature(run_dir: str | Path) -> dict:
    """Return the stable signature for metrics/trades/equity artifacts."""
    run_path = Path(run_dir)
    hashes = artifact_hashes(run_path)
    missing = [name for name in ARTIFACT_HASH_FILES if name not in hashes]
    signature = None if missing else stable_json_hash({name: hashes[name] for name in ARTIFACT_HASH_FILES})
    return {
        "run_id": run_path.name,
        "signature": signature,
        "artifact_hashes": hashes,
        "missing_artifacts": missing,
    }


def find_duplicate_artifact(run_dir: str | Path, state_dir: str | Path = "state") -> dict | None:
    """Find a historical duplicate by global artifact signature."""
    current = build_artifact_signature(run_dir)
    signature = current.get("signature")
    if not signature:
        return None
    index = read_json(Path(state_dir) / "artifact_hash_index.json", {"signatures": {}})
    found = index.get("signatures", {}).get(signature)
    if not found:
        return None
    canonical = found.get("canonical_run_id")
    if canonical == current["run_id"]:
        return None
    return {
        "decision": "duplicate_result",
        "run_id": current["run_id"],
        "duplicate_of_run_id": canonical,
        "signature": signature,
        "accepted_for_followup": False,
        "promoted_to_baseline_candidate": False,
        "can_move_parent": False,
        "can_promote_baseline": False,
    }


def update_artifact_index(run_dir: str | Path, state_dir: str | Path = "state") -> dict:
    """Append one run to the global artifact signature index."""
    current = build_artifact_signature(run_dir)
    path = Path(state_dir) / "artifact_hash_index.json"
    index = read_json(path, {"version": 1, "signatures": {}, "runs": {}})
    run_id = current["run_id"]
    signature = current.get("signature")
    index.setdefault("runs", {})[run_id] = current
    duplicate = None
    if signature:
        entry = index.setdefault("signatures", {}).setdefault(
            signature,
            {
                "canonical_run_id": run_id,
                "run_ids": [],
                "artifact_hashes": current["artifact_hashes"],
            },
        )
        if run_id not in entry["run_ids"]:
            entry["run_ids"].append(run_id)
        if entry.get("canonical_run_id") != run_id:
            duplicate = {
                "run_id": run_id,
                "duplicate_of_run_id": entry.get("canonical_run_id"),
                "signature": signature,
            }
    write_json(path, index)
    return {"index": index, "signature": current, "duplicate": duplicate}


def rebuild_artifact_index_from_runs(runs_dir: str | Path = "runs", state_dir: str | Path = "state") -> dict:
    """Rebuild the global artifact index from EXP_* and AUTO_* run folders."""
    index = {"version": 1, "signatures": {}, "runs": {}}
    duplicates = []
    for run_dir in sorted([p for p in Path(runs_dir).glob("*_*") if p.is_dir() and (p.name.startswith("EXP_") or p.name.startswith("AUTO_"))]):
        current = build_artifact_signature(run_dir)
        run_id = current["run_id"]
        signature = current.get("signature")
        index["runs"][run_id] = current
        if not signature:
            continue
        entry = index["signatures"].setdefault(
            signature,
            {
                "canonical_run_id": run_id,
                "run_ids": [],
                "artifact_hashes": current["artifact_hashes"],
            },
        )
        if run_id not in entry["run_ids"]:
            entry["run_ids"].append(run_id)
        if entry["canonical_run_id"] != run_id:
            duplicates.append(
                {
                    "run_id": run_id,
                    "duplicate_of_run_id": entry["canonical_run_id"],
                    "signature": signature,
                    "decision": "duplicate_result",
                    "value_delivered": "duplicate_blocked",
                }
            )
    write_json(Path(state_dir) / "artifact_hash_index.json", index)
    return {"index": index, "duplicates": duplicates}


__all__ = [
    "build_artifact_signature",
    "find_duplicate_artifact",
    "update_artifact_index",
    "rebuild_artifact_index_from_runs",
]
