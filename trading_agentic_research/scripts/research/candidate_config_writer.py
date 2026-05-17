"""Write concrete strategy configs from bibliography hypotheses."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.governance import changed_parameters_between
from scripts.research.autonomous import apply_hypothesis_to_config


def write_candidate_config(parent_config: dict, hypothesis: dict, output_dir: str | Path = "configs/generated") -> Path:
    """Apply a hypothesis to parent config and persist an auditable candidate JSON."""
    candidate = apply_hypothesis_to_config(parent_config, hypothesis)
    changed = changed_parameters_between(parent_config, candidate)
    candidate["changed_parameters"] = changed
    candidate["expected_effect"] = hypothesis.get("expected_effect")
    candidate["falsification_rule"] = hypothesis.get("falsification_rule")
    candidate["claim"] = hypothesis.get("claim")
    candidate["causal_mechanism"] = hypothesis.get("causal_mechanism")
    candidate["bibliography_basis"] = [{"source_id": sid} for sid in hypothesis.get("source_ids", [])]

    path = Path(output_dir) / f"{hypothesis['hypothesis_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


__all__ = ["write_candidate_config"]
