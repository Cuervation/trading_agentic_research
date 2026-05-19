from pathlib import Path
import sys

ROOT = Path.cwd()
path = ROOT / "scripts" / "research" / "effective_hypothesis_filter.py"

if not path.exists():
    print(f"ERROR: missing {path}")
    sys.exit(1)

text = path.read_text(encoding="utf-8-sig")

old_import = "from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate\nfrom scripts.research.strategy_effect_signature import read_json\n"
new_import = "from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate, load_index, rebuild_strategy_effect_index\nfrom scripts.research.strategy_effect_signature import read_json, strategy_effect_signature, canonical_strategy_effect_payload\n"
if new_import not in text:
    if old_import not in text:
        print("ERROR: import anchor not found")
        sys.exit(1)
    text = text.replace(old_import, new_import, 1)

helper_anchor = "\ndef _resolve_config_for_hypothesis(\n"
helpers = '''

# SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5

def _deep_merge_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in (base or {}).items():
        if isinstance(value, dict):
            merged[key] = _deep_merge_dict(value, {})
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value

    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _resolve_parent_config_for_synthetic(
    *,
    state_dir: str | Path,
    repo_root: str | Path,
) -> Path | None:
    root = Path(repo_root)
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = root / state_path

    current_parent = read_json(state_path / "current_parent.json", {}) or {}

    candidates: list[Path] = []
    for value in (
        current_parent.get("current_parent_config_path"),
        "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json",
        "configs/baseline_momentum_trend_v1.json",
    ):
        if not value:
            continue
        p = Path(str(value))
        if not p.is_absolute():
            p = root / p
        candidates.append(p)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate
    return None


def _synthetic_strategy_config_from_hypothesis(
    *,
    hypothesis: dict[str, Any],
    state_dir: str | Path,
    repo_root: str | Path,
) -> dict[str, Any] | None:
    overrides = hypothesis.get("strategy_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return None

    parent_path = _resolve_parent_config_for_synthetic(state_dir=state_dir, repo_root=repo_root)
    if parent_path is None:
        return None

    parent_cfg = read_json(parent_path, {}) or {}
    if not isinstance(parent_cfg, dict) or not parent_cfg:
        return None

    generated = _deep_merge_dict(parent_cfg, overrides)
    generated["parent_strategy_id"] = str(parent_cfg.get("strategy_id"))
    if "strategy_id" not in overrides:
        generated["strategy_id"] = str(hypothesis.get("hypothesis_id"))
    generated.setdefault("strategy_family", parent_cfg.get("strategy_family") or hypothesis.get("family"))
    generated["hypothesis_id"] = str(hypothesis.get("hypothesis_id"))
    generated.setdefault("bibliography_basis", [])
    generated.setdefault("empirical_basis", [])
    return generated


def synthetic_duplicate_status(
    *,
    hypothesis: dict[str, Any],
    state_dir: str | Path,
    runs_dir: str | Path,
    strategy_registry_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    # Check duplicate strategy effect before a config file exists.
    generated = _synthetic_strategy_config_from_hypothesis(
        hypothesis=hypothesis,
        state_dir=state_dir,
        repo_root=repo_root,
    )
    if generated is None:
        return {"checked": False, "synthetic": True, "reason": "synthetic_config_unavailable"}

    sig = strategy_effect_signature(generated)
    index = load_index(state_dir)
    if not index.get("runs"):
        index = rebuild_strategy_effect_index(
            state_dir=state_dir,
            runs_dir=runs_dir,
            strategy_registry_path=strategy_registry_path,
            repo_root=repo_root,
        )

    sig_entry = (index.get("signatures") or {}).get(sig)
    if sig_entry and sig_entry.get("runs"):
        return {
            "checked": True,
            "synthetic": True,
            "blocked": True,
            "reason": "duplicate_strategy_effect_signature_synthetic_config",
            "duplicate_of_run_id": sig_entry.get("first_seen_run_id") or sig_entry.get("runs", [None])[0],
            "existing_runs": sig_entry.get("runs", []),
            "strategy_effect_signature": sig,
            "canonical_payload": canonical_strategy_effect_payload(generated),
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "family": hypothesis.get("family"),
        }

    return {
        "checked": True,
        "synthetic": True,
        "blocked": False,
        "reason": "synthetic_config_unique",
        "strategy_effect_signature": sig,
        "canonical_payload": canonical_strategy_effect_payload(generated),
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "family": hypothesis.get("family"),
    }

'''
if "SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5" not in text:
    if helper_anchor not in text:
        print("ERROR: helper anchor not found")
        sys.exit(1)
    text = text.replace(helper_anchor, helpers + helper_anchor, 1)

old_branch = '''        else:
            exact = {"checked": False, "reason": "config_not_resolved"}

    return {
        "blocked": False,
        "reason": "effective",
'''
new_branch = '''        else:
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
if "duplicate_strategy_effect_signature_synthetic_config" not in text:
    if old_branch not in text:
        print("ERROR: exact-branch anchor not found")
        sys.exit(1)
    text = text.replace(old_branch, new_branch, 1)

path.write_text(text, encoding="utf-8")
print("PATCH_OK: synthetic config preflight v5 applied")
