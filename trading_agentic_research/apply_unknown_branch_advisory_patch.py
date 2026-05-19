from pathlib import Path
import sys

path = Path("scripts/research/semantic_branch_guard.py")

if not path.exists():
    print(f"ERROR: No existe {path}. Ejecutá desde el root del proyecto trading_agentic_research.")
    sys.exit(1)

text = path.read_text(encoding="utf-8-sig")

marker = "UNKNOWN_BRANCH_ADVISORY_DIRECT_PATCH"

if marker in text:
    print("OK: el patch de unknown branch advisory ya estaba aplicado.")
    sys.exit(0)

old = '''    status = semantic_branch_status(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id,
        family=family,
        refresh=True,
    )
    if not status.get("exhausted"):
        return {"blocked": False, **status}

    duplicate_of = None
'''

new = '''    status = semantic_branch_status(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id,
        family=family,
        refresh=True,
    )

    # UNKNOWN_BRANCH_ADVISORY_DIRECT_PATCH
    # Unknown branches are too coarse to block safely. Examples:
    # paper_time_series_momentum/unknown_field/unknown_layer
    # cross_sectional_momentum/unknown_field/unknown_layer
    # Those should inform generation/analysis, but must not block all future
    # paper/literature/non-feature hypotheses. Only precise branches should
    # trigger a pre-run block.
    branch_key = str(status.get("branch_key") or "")
    if "unknown_field" in branch_key or "unknown_layer" in branch_key:
        return {
            "blocked": False,
            "advisory": True,
            "reason": f"semantic_branch_advisory_unknown:{branch_key}:{status.get('reason')}",
            **status,
        }

    if not status.get("exhausted"):
        return {"blocked": False, **status}

    duplicate_of = None
'''

if old not in text:
    print("ERROR: No encontré el bloque esperado dentro de semantic_branch_preflight.")
    print("El archivo cambió o el patch ya fue aplicado de otra forma.")
    sys.exit(1)

text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

print("PATCH_OK: unknown/unknown semantic branches ahora son advisory y no bloqueantes.")
print("Archivo corregido:", path)
