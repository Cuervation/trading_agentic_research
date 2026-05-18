import json
from pathlib import Path

from scripts.research.candidate_review_refinement_factory import generate_candidate_review_hypotheses


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_review_factory_skips_exhausted_axes(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    cfg = tmp_path / "configs" / "generated" / "CAND.json"
    write_json(state / "candidate_under_review.json", {
        "status": "active",
        "candidate_run_id": "EXP_1",
        "hypothesis_id": "CAND",
        "strategy_config_path": "configs/generated/CAND.json",
    })
    write_json(state / "candidate_review_learning.json", {"exhausted_axes": ["exit", "trailing"], "attempts": [], "axis_stats": {}})
    write_json(cfg, {
        "strategy_id": "CAND",
        "hypothesis_id": "CAND",
        "entry_rule": {"top_n": 6},
        "exit_rule": {"rank_threshold": 20},
        "risk_management": {},
    })
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    result = generate_candidate_review_hypotheses(
        state_dir=state,
        hypothesis_bank_path=bank,
        repo_root=tmp_path,
        max_new=10,
    )
    ids = result["hypotheses"]
    assert ids
    assert all("EXIT" not in x and "TRAILING" not in x for x in ids)
    assert any("TOPN" in x for x in ids)
