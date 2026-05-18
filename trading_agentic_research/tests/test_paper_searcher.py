from scripts.research.paper_searcher import generate_paper_ideas


def test_paper_searcher_offline_writes_ideas(tmp_path):
    output = tmp_path / "paper_ideas.jsonl"
    result = generate_paper_ideas(output=output, online=False)
    assert result["rows_written"] >= 1
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "claim_seed" in text
