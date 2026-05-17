import json

import pytest

from scripts.promote_candidate import promote_candidate_to_baseline
from scripts.update_parent import can_update_parent_from_audit, update_current_parent


def test_rejected_audit_cannot_move_parent(tmp_path):
    audit = {
        "decision": "rejected",
        "can_move_parent": False,
        "can_promote_baseline": False,
        "blocking_issues": [],
    }

    result = update_current_parent(
        state_dir=tmp_path,
        run_id="EXP_BAD",
        strategy_id="STRAT_BAD",
        audit=audit,
    )

    assert result["updated"] is False
    assert not (tmp_path / "current_parent.json").exists()


def test_parent_update_requires_no_baseline_auto_promotion():
    audit = {
        "decision": "promoted_candidate",
        "can_move_parent": True,
        "can_promote_baseline": True,
        "blocking_issues": [],
    }

    allowed, reasons = can_update_parent_from_audit(audit)

    assert allowed is False
    assert any("baseline" in reason.lower() for reason in reasons)


def test_accepted_audit_updates_current_parent(tmp_path):
    parent_path = tmp_path / "current_parent.json"
    parent_path.write_text(
        json.dumps(
            {
                "current_parent_run_id": "EXP_OLD",
                "current_parent_strategy_id": "STRAT_OLD",
            }
        ),
        encoding="utf-8",
    )
    audit = {
        "decision": "promoted_candidate",
        "can_move_parent": True,
        "can_promote_baseline": False,
        "blocking_issues": [],
    }

    result = update_current_parent(
        state_dir=tmp_path,
        run_id="EXP_NEW",
        strategy_id="STRAT_NEW",
        audit=audit,
    )

    updated = json.loads(parent_path.read_text(encoding="utf-8"))
    assert result["updated"] is True
    assert updated["current_parent_run_id"] == "EXP_NEW"
    assert updated["current_parent_strategy_id"] == "STRAT_NEW"
    assert updated["previous_parent_run_id"] == "EXP_OLD"
    assert updated["updated_from_audit"] is True


def test_parent_update_keeps_existing_strategy_id_when_not_provided(tmp_path):
    parent_path = tmp_path / "current_parent.json"
    parent_path.write_text(
        json.dumps(
            {
                "current_parent_run_id": None,
                "current_parent_strategy_id": "STRAT_BASELINE",
            }
        ),
        encoding="utf-8",
    )
    audit = {
        "decision": "accepted_for_followup",
        "can_move_parent": True,
        "can_promote_baseline": False,
        "blocking_issues": [],
    }

    update_current_parent(state_dir=tmp_path, run_id="EXP_NEW", audit=audit)

    updated = json.loads(parent_path.read_text(encoding="utf-8"))
    assert updated["current_parent_strategy_id"] == "STRAT_BASELINE"



def test_baseline_not_modified_by_loop(tmp_path):
    baseline_path = tmp_path / "current_baseline.json"
    baseline_path.write_text(json.dumps({"baseline_run_id": "EXP_BASE"}), encoding="utf-8")
    audit = {
        "decision": "promoted_candidate",
        "can_move_parent": True,
        "can_promote_baseline": False,
        "blocking_issues": [],
    }

    update_current_parent(state_dir=tmp_path, run_id="EXP_NEW", strategy_id="STRAT_NEW", audit=audit)

    assert json.loads(baseline_path.read_text(encoding="utf-8"))["baseline_run_id"] == "EXP_BASE"



def test_promote_candidate_py_requires_manual_review(tmp_path):
    run_dir = tmp_path / "runs" / "EXP_CANDIDATE"
    run_dir.mkdir(parents=True)
    (run_dir / "audit.json").write_text(
        json.dumps({"decision": "promoted_candidate", "blocking_issues": []}),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"strategy_id": "STRAT", "hypothesis_id": "HYP"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Manual review"):
        promote_candidate_to_baseline(
            state_dir=tmp_path / "state",
            runs_dir=tmp_path / "runs",
            run_id="EXP_CANDIDATE",
            confirm_manual_review=False,
        )

    payload = promote_candidate_to_baseline(
        state_dir=tmp_path / "state",
        runs_dir=tmp_path / "runs",
        run_id="EXP_CANDIDATE",
        confirm_manual_review=True,
    )

    assert payload["baseline_run_id"] == "EXP_CANDIDATE"
    assert payload["source"] == "scripts/promote_candidate.py"
