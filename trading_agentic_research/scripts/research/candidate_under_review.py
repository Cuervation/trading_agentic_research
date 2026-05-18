"""Candidate-under-review state and config recovery.

Purpose
-------
When champion governance finds a strong promotion candidate, the autonomous loop
should be able to refine that candidate without promoting it as the official
parent. This module keeps:

- official parent: state/current_parent.json, usually AUTO_002;
- candidate under review: state/candidate_under_review.json, for example EXP_044.

The important part is config recovery. Some historical runs were created before
configs were versioned consistently, so this module recovers the candidate config
from, in order:

1. run_manifest.json strategy_config_path / strategy_config / strategy_id;
2. strategy_registry.json by strategy_id / hypothesis_id;
3. configs/generated/{hypothesis_id}.json or {strategy_id}.json;
4. hypothesis_bank.jsonl + parent config reconstruction.

It never moves the official parent.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_strategy_config import generate_strategy_config_from_hypothesis, upsert_strategy_registry
from scripts.research.champion_governance import load_champion_state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _repo_path(path: str | Path | None, repo_root: str | Path = ROOT) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo_root) / p
    return p


def _as_repo_relative(path: str | Path | None, repo_root: str | Path = ROOT) -> str | None:
    if not path:
        return None
    p = _repo_path(path, repo_root)
    if not p:
        return None
    try:
        return p.relative_to(Path(repo_root)).as_posix()
    except ValueError:
        return str(p)


def _find_hypothesis(hypothesis_bank_path: str | Path, hypothesis_id: str | None) -> dict[str, Any] | None:
    if not hypothesis_id:
        return None
    for row in read_jsonl(hypothesis_bank_path):
        if str(row.get("hypothesis_id")) == str(hypothesis_id):
            return row
    return None


def _find_registry_config(
    *,
    strategy_registry_path: str | Path,
    repo_root: str | Path,
    strategy_id: str | None,
    hypothesis_id: str | None,
) -> str | None:
    registry = read_json(_repo_path(strategy_registry_path, repo_root), {}) or {}
    for row in registry.get("strategies", []) if isinstance(registry, dict) else []:
        row_strategy_id = str(row.get("strategy_id") or "")
        row_hypothesis_id = str(row.get("hypothesis_id") or row.get("strategy_id") or "")
        if strategy_id and row_strategy_id != str(strategy_id):
            if not hypothesis_id or row_hypothesis_id != str(hypothesis_id):
                continue
        elif hypothesis_id and row_hypothesis_id != str(hypothesis_id) and row_strategy_id != str(hypothesis_id):
            continue
        config_path = row.get("config_path")
        p = _repo_path(config_path, repo_root)
        if p and p.exists():
            return _as_repo_relative(p, repo_root)
    return None


def _find_generated_config(
    *,
    generated_configs_dir: str | Path,
    repo_root: str | Path,
    strategy_id: str | None,
    hypothesis_id: str | None,
) -> str | None:
    base = _repo_path(generated_configs_dir, repo_root)
    if not base or not base.exists():
        return None
    for key in [hypothesis_id, strategy_id]:
        if not key:
            continue
        candidate = base / f"{key}.json"
        if candidate.exists():
            return _as_repo_relative(candidate, repo_root)
    # Fallback: inspect configs for matching internal ids.
    for p in base.glob("*.json"):
        cfg = read_json(p, {}) or {}
        if strategy_id and str(cfg.get("strategy_id")) == str(strategy_id):
            return _as_repo_relative(p, repo_root)
        if hypothesis_id and str(cfg.get("hypothesis_id")) == str(hypothesis_id):
            return _as_repo_relative(p, repo_root)
    return None


def _recover_from_manifest(
    *,
    run_manifest: dict[str, Any],
    repo_root: str | Path,
) -> tuple[str | None, str | None, str | None]:
    strategy_id = run_manifest.get("strategy_id") or run_manifest.get("strategy", {}).get("strategy_id")
    hypothesis_id = run_manifest.get("hypothesis_id") or run_manifest.get("strategy", {}).get("hypothesis_id") or strategy_id

    for key in ["strategy_config_path", "strategy_config", "config_path"]:
        value = run_manifest.get(key)
        if isinstance(value, dict):
            strategy_id = strategy_id or value.get("strategy_id")
            hypothesis_id = hypothesis_id or value.get("hypothesis_id") or value.get("strategy_id")
            continue
        p = _repo_path(value, repo_root)
        if p and p.exists():
            return _as_repo_relative(p, repo_root), strategy_id, hypothesis_id

    # Some manifests nest paths under strategy_config metadata.
    strategy_cfg = run_manifest.get("strategy_config")
    if isinstance(strategy_cfg, dict):
        strategy_id = strategy_id or strategy_cfg.get("strategy_id")
        hypothesis_id = hypothesis_id or strategy_cfg.get("hypothesis_id") or strategy_cfg.get("strategy_id")
        for key in ["path", "config_path", "strategy_config_path"]:
            p = _repo_path(strategy_cfg.get(key), repo_root)
            if p and p.exists():
                return _as_repo_relative(p, repo_root), strategy_id, hypothesis_id

    return None, strategy_id, hypothesis_id


def _recover_by_rebuilding_config(
    *,
    hypothesis_id: str | None,
    parent_config_path: str | Path | None,
    hypothesis_bank_path: str | Path,
    generated_configs_dir: str | Path,
    strategy_registry_path: str | Path,
    repo_root: str | Path,
) -> str | None:
    if not hypothesis_id or not parent_config_path:
        return None
    hypothesis = _find_hypothesis(_repo_path(hypothesis_bank_path, repo_root) or hypothesis_bank_path, hypothesis_id)
    parent_path = _repo_path(parent_config_path, repo_root)
    if not hypothesis or not parent_path or not parent_path.exists():
        return None
    parent_cfg = read_json(parent_path, {}) or {}
    generated = generate_strategy_config_from_hypothesis(hypothesis=hypothesis, parent_strategy_config=parent_cfg)
    out_dir = _repo_path(generated_configs_dir, repo_root) or (Path(repo_root) / "configs" / "generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{hypothesis_id}.json"
    write_json(out_path, generated)
    upsert_strategy_registry(
        registry_path=_repo_path(strategy_registry_path, repo_root) or strategy_registry_path,
        strategy_id=str(generated.get("strategy_id") or hypothesis_id),
        config_path=_as_repo_relative(out_path, repo_root) or str(out_path),
        strategy_family=str(generated.get("strategy_family") or hypothesis.get("family") or "candidate_under_review"),
        status="candidate_under_review_recovered",
        notes=f"Recovered config for candidate-under-review hypothesis {hypothesis_id}.",
    )
    return _as_repo_relative(out_path, repo_root)


def recover_candidate_config(
    *,
    candidate_run_id: str,
    runs_dir: str | Path = "runs",
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    repo_root: str | Path = ROOT,
) -> dict[str, Any]:
    repo = Path(repo_root)
    run_dir = _repo_path(Path(runs_dir) / candidate_run_id, repo) or (repo / str(runs_dir) / candidate_run_id)
    manifest = read_json(run_dir / "run_manifest.json", {}) or {}
    audit = read_json(run_dir / "audit.json", {}) or {}
    current_parent = read_json(_repo_path(Path(state_dir) / "current_parent.json", repo) or (repo / state_dir / "current_parent.json"), {}) or {}
    parent_config = current_parent.get("current_parent_config_path")

    config_path, strategy_id, hypothesis_id = _recover_from_manifest(run_manifest=manifest, repo_root=repo)

    if not config_path:
        config_path = _find_registry_config(
            strategy_registry_path=strategy_registry_path,
            repo_root=repo,
            strategy_id=strategy_id,
            hypothesis_id=hypothesis_id,
        )
    if not config_path:
        config_path = _find_generated_config(
            generated_configs_dir=generated_configs_dir,
            repo_root=repo,
            strategy_id=strategy_id,
            hypothesis_id=hypothesis_id,
        )
    if not config_path:
        config_path = _recover_by_rebuilding_config(
            hypothesis_id=hypothesis_id,
            parent_config_path=parent_config,
            hypothesis_bank_path=hypothesis_bank_path,
            generated_configs_dir=generated_configs_dir,
            strategy_registry_path=strategy_registry_path,
            repo_root=repo,
        )

    return {
        "candidate_run_id": candidate_run_id,
        "strategy_id": strategy_id,
        "hypothesis_id": hypothesis_id,
        "strategy_config_path": config_path,
        "audit_decision": audit.get("decision"),
        "can_move_parent": audit.get("can_move_parent"),
    }


def _candidate_from_champion_state(state_dir: str | Path) -> str | None:
    champion = load_champion_state(state_dir)
    candidate = champion.get("baseline_candidate_run_id")
    if candidate:
        return str(candidate)
    candidates = champion.get("promotion_candidates", []) or []
    if candidates:
        return str(candidates[0].get("run_id"))
    return None


def refresh_candidate_under_review(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    repo_root: str | Path = ROOT,
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    generated_configs_dir: str | Path = "configs/generated",
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
) -> dict[str, Any]:
    candidate_run_id = _candidate_from_champion_state(state_dir)
    if not candidate_run_id:
        payload = {"status": "none", "reason": "no_promotion_candidate", "updated_at": now_iso()}
        write_json(Path(state_dir) / "candidate_under_review.json", payload)
        return payload

    recovered = recover_candidate_config(
        candidate_run_id=candidate_run_id,
        runs_dir=runs_dir,
        state_dir=state_dir,
        strategy_registry_path=strategy_registry_path,
        generated_configs_dir=generated_configs_dir,
        hypothesis_bank_path=hypothesis_bank_path,
        repo_root=repo_root,
    )

    config_path = recovered.get("strategy_config_path")
    status = "active" if config_path else "blocked"
    reason = "candidate_config_recovered" if config_path else "candidate_config_missing"
    payload = {
        "status": status,
        "reason": reason,
        "candidate_run_id": candidate_run_id,
        "strategy_id": recovered.get("strategy_id"),
        "hypothesis_id": recovered.get("hypothesis_id"),
        "strategy_config_path": config_path,
        "official_parent_run_id": (read_json(Path(state_dir) / "current_parent.json", {}) or {}).get("current_parent_run_id"),
        "updated_at": now_iso(),
    }
    write_json(Path(state_dir) / "candidate_under_review.json", payload)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Refresh candidate-under-review state and recover its config when possible.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--repo-root", default=str(ROOT))
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--generated-configs-dir", default="configs/generated")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    args = p.parse_args()
    print(json.dumps(refresh_candidate_under_review(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        repo_root=args.repo_root,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        hypothesis_bank_path=args.hypothesis_bank,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
