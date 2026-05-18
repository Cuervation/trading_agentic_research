import json
import subprocess
import sys
from pathlib import Path


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_review_refinement_factory_cli_imports_from_repo_root(tmp_path):
    repo = tmp_path
    # Copy is not available in this isolated test, so import the installed repo module directly via subprocess cwd.
    state = repo / "state"
    cfg = repo / "configs" / "generated" / "CANDIDATE.json"
    bank = repo / "bibliography" / "hypothesis_bank.jsonl"
    write_json(cfg, {"strategy_id": "CANDIDATE", "hypothesis_id": "CANDIDATE", "entry_rule": {"top_n": 6}, "exit_rule": {"rank_threshold": 20}})
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_044", "hypothesis_id": "CANDIDATE", "strategy_config_path": str(cfg)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    code = "from scripts.research.candidate_review_refinement_factory import generate_candidate_review_hypotheses; import json; print(json.dumps(generate_candidate_review_hypotheses(state_dir=r'%s', hypothesis_bank_path=r'%s', repo_root=r'%s')))" % (state, bank, repo)
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, cwd=repo_root)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["generated"] >= 1
