from pathlib import Path
import re
import sys

path = Path("scripts/research/pre_run_duplicate_guard.py")

if not path.exists():
    print(f"ERROR: No existe {path}. Ejecutá este script desde el root del proyecto trading_agentic_research.")
    sys.exit(1)

text = path.read_text(encoding="utf-8-sig")

pattern = (
    r"def _add_signature_entry\(index: dict\[str, Any\], \*, run_id: str, "
    r"info: dict\[str, Any\], audit: dict\[str, Any\] \| None = None\) -> None:\n"
    r".*?\n(?=def rebuild_strategy_effect_index)"
)

clean_function = '''def _add_signature_entry(index: dict[str, Any], *, run_id: str, info: dict[str, Any], audit: dict[str, Any] | None = None) -> None:
    audit = audit or {}
    sig = info.get("strategy_effect_signature")
    cfg_hash = info.get("config_hash")
    flags = audit.get("flags") or []
    value = "duplicate_blocked" if (
        audit.get("duplicate_result")
        or "duplicate_result" in flags
        or "duplicate_artifact" in flags
    ) else audit.get("decision")

    index.setdefault("runs", {})[run_id] = {
        "run_id": run_id,
        "strategy_effect_signature": sig,
        "config_hash": cfg_hash,
        "strategy_id": info.get("strategy_id"),
        "hypothesis_id": info.get("hypothesis_id"),
        "strategy_family": info.get("strategy_family"),
        "config_path": info.get("config_path"),
        "decision": audit.get("decision"),
        "value_delivered": value,
        "duplicate_of_run_id": audit.get("duplicate_of_run_id"),
        "updated_at": now_iso(),
    }

    if sig:
        e = index.setdefault("signatures", {}).setdefault(
            sig,
            {
                "strategy_effect_signature": sig,
                "first_seen_run_id": run_id,
                "runs": [],
                "created_at": now_iso(),
                "canonical_payload": info.get("canonical_payload"),
            },
        )
        if run_id not in e["runs"]:
            e["runs"].append(run_id)
        e["updated_at"] = now_iso()

    if cfg_hash:
        e = index.setdefault("config_hashes", {}).setdefault(
            cfg_hash,
            {
                "config_hash": cfg_hash,
                "first_seen_run_id": run_id,
                "runs": [],
                "created_at": now_iso(),
            },
        )
        if run_id not in e["runs"]:
            e["runs"].append(run_id)
        e["updated_at"] = now_iso()


'''

text2, count = re.subn(pattern, clean_function, text, count=1, flags=re.S)

if count != 1:
    print("ERROR: No pude reemplazar _add_signature_entry.")
    print("Probablemente el archivo cambió o el patrón ya no coincide.")
    sys.exit(1)

if "def check_pre_run_duplicate" not in text2:
    print("ERROR: No encontré check_pre_run_duplicate.")
    sys.exit(1)

if "semantic_branch_preflight" not in text2:
    print("ERROR: Se perdió semantic_branch_preflight.")
    sys.exit(1)

marker_count = text2.count("SEMANTIC_BRANCH_GUARD_DIRECT_PATCH")
if marker_count != 1:
    print(f"ERROR: Debe quedar exactamente 1 SEMANTIC_BRANCH_GUARD_DIRECT_PATCH; quedaron {marker_count}.")
    sys.exit(1)

path.write_text(text2, encoding="utf-8")
print("FIX_OK: pre_run_duplicate_guard.py limpio")
print("Archivo corregido:", path)
