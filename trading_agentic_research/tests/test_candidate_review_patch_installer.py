from pathlib import Path


def test_patch_installer_exists():
    assert Path("tools/apply_candidate_review_learning_patch.py").exists()
