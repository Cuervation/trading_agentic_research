"""Global artifact-index helpers for continuous research learning.

Purpose:
- Detect duplicate/no-effect runs by the actual produced artifacts, not only by
  hypothesis id, config hash, parent, or last run.
- Persist a global index in state/artifact_hash_index.json.

A run is considered a duplicate when metrics.json + trades.csv + equity_curve.csv
have the same SHA-256 hashes as a previous run.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_FILES = ("metrics.json", "trades.csv", "equity_curve.csv")
DEFAULT_INDEX_FILE = "artifact_hash_index.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


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


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run_id_from_dir(run_dir: str | Path) -> str:
    return Path(run_dir).name


def artifact_hashes(run_dir: str | Path) -> dict[str, str]:
    path = Path(run_dir)
    return {name: sha256_file(path / name) for name in ARTIFACT_FILES if (path / name).exists()}


def has_required_artifacts(run_dir: str | Path) -> bool:
    path = Path(run_dir)
    return all((path / name).exists() for name in ARTIFACT_FILES)


def build_artifact_signature(run_dir: str | Path) -> dict[str, Any]:
    """Return hashes + global signature for a run directory."""
    path = Path(run_dir)
    hashes = artifact_hashes(path)
    missing = [name for name in ARTIFACT_FILES if name not in hashes]
    signature = stable_hash({name: hashes.get(name) for name in ARTIFACT_FILES}) if not missing else None
    return {
        "run_id": path.name,
        "run_dir": str(path),
        "hashes": hashes,
        "missing_artifacts": missing,
        "artifact_signature": signature,
    }


def empty_index() -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "artifact_files": list(ARTIFACT_FILES),
        "signatures": {},
        "runs": {},
    }


def artifact_index_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / DEFAULT_INDEX_FILE


def load_artifact_index(state_dir: str | Path) -> dict[str, Any]:
    path = artifact_index_path(state_dir)
    payload = read_json(path, None)
    if not payload:
        return empty_index()
    payload.setdefault("version", 1)
    payload.setdefault("artifact_files", list(ARTIFACT_FILES))
    payload.setdefault("signatures", {})
    payload.setdefault("runs", {})
    return payload


def save_artifact_index(state_dir: str | Path, index: dict[str, Any]) -> None:
    index["updated_at"] = now_iso()
    write_json(artifact_index_path(state_dir), index)


def find_duplicate_artifact(run_dir: str | Path, state_dir: str | Path, *, exclude_same_run: bool = True) -> dict[str, Any]:
    """Return duplicate info for run_dir using the global artifact index."""
    current = build_artifact_signature(run_dir)
    if current["missing_artifacts"] or not current["artifact_signature"]:
        return {"is_duplicate": False, "reason": "missing_artifacts", "current": current}

    index = load_artifact_index(state_dir)
    entry = index.get("signatures", {}).get(current["artifact_signature"])
    if not entry:
        return {"is_duplicate": False, "current": current}

    current_run_id = current["run_id"]
    first_seen = entry.get("first_seen_run_id")
    runs = list(entry.get("runs", []))
    candidate_other_runs = [rid for rid in runs if not (exclude_same_run and rid == current_run_id)]
    if exclude_same_run and first_seen == current_run_id and not candidate_other_runs:
        return {"is_duplicate": False, "current": current, "existing_entry": entry}

    duplicate_of = first_seen if first_seen != current_run_id else (candidate_other_runs[0] if candidate_other_runs else first_seen)
    return {
        "is_duplicate": True,
        "duplicate_of_run_id": duplicate_of,
        "duplicate_signature": current["artifact_signature"],
        "current": current,
        "existing_entry": entry,
    }


def update_artifact_index(run_dir: str | Path, state_dir: str | Path) -> dict[str, Any]:
    """Upsert run_dir into state/artifact_hash_index.json and return status."""
    current = build_artifact_signature(run_dir)
    index = load_artifact_index(state_dir)
    run_id = current["run_id"]
    signature = current.get("artifact_signature")

    if current["missing_artifacts"] or not signature:
        index.setdefault("runs", {})[run_id] = {
            "run_id": run_id,
            "artifact_signature": None,
            "missing_artifacts": current["missing_artifacts"],
            "updated_at": now_iso(),
        }
        save_artifact_index(state_dir, index)
        return {"updated": True, "is_duplicate": False, "reason": "missing_artifacts", "current": current}

    entry = index.setdefault("signatures", {}).get(signature)
    is_duplicate = False
    duplicate_of = None
    if not entry:
        entry = {
            "artifact_signature": signature,
            "first_seen_run_id": run_id,
            "first_seen_run_dir": str(Path(run_dir)),
            "hashes": current["hashes"],
            "runs": [run_id],
            "duplicate_run_ids": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        index["signatures"][signature] = entry
    else:
        duplicate_of = entry.get("first_seen_run_id")
        if run_id not in entry.setdefault("runs", []):
            entry["runs"].append(run_id)
        if duplicate_of != run_id and run_id not in entry.setdefault("duplicate_run_ids", []):
            entry["duplicate_run_ids"].append(run_id)
            is_duplicate = True
        entry["updated_at"] = now_iso()

    index.setdefault("runs", {})[run_id] = {
        "run_id": run_id,
        "artifact_signature": signature,
        "metrics_hash": current["hashes"].get("metrics.json"),
        "trades_hash": current["hashes"].get("trades.csv"),
        "equity_hash": current["hashes"].get("equity_curve.csv"),
        "first_seen_run_id": entry.get("first_seen_run_id"),
        "is_duplicate": bool(is_duplicate or (entry.get("first_seen_run_id") != run_id)),
        "duplicate_of_run_id": duplicate_of if duplicate_of != run_id else None,
        "updated_at": now_iso(),
    }
    save_artifact_index(state_dir, index)
    return {
        "updated": True,
        "is_duplicate": bool(index["runs"][run_id]["is_duplicate"]),
        "duplicate_of_run_id": index["runs"][run_id].get("duplicate_of_run_id"),
        "current": current,
        "index_path": str(artifact_index_path(state_dir)),
    }


def apply_duplicate_to_audit(audit: dict, duplicate_info: dict[str, Any]) -> dict:
    """Return audit payload forced to rejected duplicate_result."""
    if not duplicate_info.get("is_duplicate"):
        return audit
    updated = dict(audit or {})
    flags = list(updated.get("flags", []) or [])
    for flag in ("duplicate_result", "duplicate_artifact", "metric_no_effect"):
        if flag not in flags:
            flags.append(flag)
    reasons = list(updated.get("reasons", []) or [])
    duplicate_of = duplicate_info.get("duplicate_of_run_id")
    reasons.append(f"Global duplicate artifact signature already seen in {duplicate_of}.")
    updated.update(
        {
            "decision": "rejected",
            "recommendation": "Reject: duplicate_result detected by global artifact index.",
            "can_move_parent": False,
            "can_promote_baseline": False,
            "flags": flags,
            "reasons": reasons,
            "duplicate_result": True,
            "duplicate_of_run_id": duplicate_of,
            "global_artifact_duplicate": duplicate_info,
        }
    )
    return updated


def run_sort_key(path: Path) -> tuple[int, int, str]:
    name = path.name
    match = re.match(r"^(EXP|AUTO)_(\d+)$", name)
    if match:
        prefix_order = 0 if match.group(1) == "EXP" else 1
        return (prefix_order, int(match.group(2)), name)
    return (9, 10**9, name)


def iter_run_dirs(runs_dir: str | Path) -> list[Path]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir() and re.match(r"^(EXP|AUTO)_\d+$", p.name)], key=run_sort_key)


def rebuild_artifact_index_from_runs(runs_dir: str | Path, state_dir: str | Path) -> dict[str, Any]:
    """Rebuild global artifact index from all EXP_*/AUTO_* run folders."""
    index = empty_index()
    duplicates: list[dict[str, Any]] = []

    for run_dir in iter_run_dirs(runs_dir):
        current = build_artifact_signature(run_dir)
        run_id = current["run_id"]
        signature = current.get("artifact_signature")
        if current["missing_artifacts"] or not signature:
            index.setdefault("runs", {})[run_id] = {
                "run_id": run_id,
                "artifact_signature": None,
                "missing_artifacts": current["missing_artifacts"],
                "is_duplicate": False,
            }
            continue

        entry = index.setdefault("signatures", {}).get(signature)
        if not entry:
            index["signatures"][signature] = {
                "artifact_signature": signature,
                "first_seen_run_id": run_id,
                "first_seen_run_dir": str(run_dir),
                "hashes": current["hashes"],
                "runs": [run_id],
                "duplicate_run_ids": [],
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            is_duplicate = False
            duplicate_of = None
        else:
            duplicate_of = entry.get("first_seen_run_id")
            entry.setdefault("runs", []).append(run_id)
            entry.setdefault("duplicate_run_ids", []).append(run_id)
            entry["updated_at"] = now_iso()
            is_duplicate = True
            duplicates.append(
                {
                    "run_id": run_id,
                    "duplicate_of_run_id": duplicate_of,
                    "artifact_signature": signature,
                }
            )

        index.setdefault("runs", {})[run_id] = {
            "run_id": run_id,
            "artifact_signature": signature,
            "metrics_hash": current["hashes"].get("metrics.json"),
            "trades_hash": current["hashes"].get("trades.csv"),
            "equity_hash": current["hashes"].get("equity_curve.csv"),
            "first_seen_run_id": duplicate_of or run_id,
            "is_duplicate": is_duplicate,
            "duplicate_of_run_id": duplicate_of,
            "updated_at": now_iso(),
        }

    save_artifact_index(state_dir, index)
    write_json(Path(state_dir) / "duplicate_runs.json", {"version": 1, "duplicates": duplicates, "updated_at": now_iso()})
    return {"index": index, "duplicates": duplicates, "runs_indexed": len(index.get("runs", {}))}


__all__ = [
    "ARTIFACT_FILES",
    "build_artifact_signature",
    "find_duplicate_artifact",
    "update_artifact_index",
    "rebuild_artifact_index_from_runs",
    "apply_duplicate_to_audit",
    "iter_run_dirs",
    "read_json",
    "write_json",
]
