from pathlib import Path
import sys

path = Path("scripts/research/effective_hypothesis_filter.py")
if not path.exists():
    print(f"ERROR: missing {path}. Ejecutá desde el root del repo.")
    sys.exit(1)

text = path.read_text(encoding="utf-8-sig")

old = '''        else:
            exact = {"checked": False, "reason": "config_not_resolved"}

    return {
        "blocked": False,
        "reason": "effective",
'''

new = '''        else:
            # WIRE_SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5B
            exact = synthetic_duplicate_status(
                hypothesis=hypothesis,
                state_dir=state_dir,
                runs_dir=runs_dir,
                strategy_registry_path=strategy_registry_path,
                repo_root=repo_root,
            )
            if exact.get("blocked"):
                return {
                    "blocked": True,
                    "reason": str(exact.get("reason") or "duplicate_strategy_effect_signature_synthetic_config"),
                    "detail": exact.get("duplicate_of_run_id"),
                    "hypothesis_id": hid,
                    "family": family,
                    "semantic": semantic,
                    "exact_duplicate": exact,
                    "feature_space_stall": feature_stall,
                    "family_stall": fam_stall,
                }

    return {
        "blocked": False,
        "reason": "effective",
'''

if "WIRE_SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5B" in text:
    print("OK: synthetic preflight ya estaba conectado.")
    sys.exit(0)

if old not in text:
    print("ERROR: no encontré el branch config_not_resolved exacto para reemplazar.")
    sys.exit(1)

text = text.replace(old, new, 1)

required = [
    "SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5",
    "def synthetic_duplicate_status(",
    "WIRE_SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5B",
]
missing = [x for x in required if x not in text]
if missing:
    print("ERROR: faltan marcas requeridas:", missing)
    sys.exit(1)

path.write_text(text, encoding="utf-8")
print("PATCH_OK: synthetic config preflight conectado en effective_hypothesis_status")
