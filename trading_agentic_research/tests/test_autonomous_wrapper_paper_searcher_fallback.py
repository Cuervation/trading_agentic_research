from scripts.research.paper_searcher import generate_paper_ideas


def test_paper_searcher_creates_nonempty_paper_ideas(tmp_path):
    output = tmp_path / "paper_ideas.jsonl"
    result = generate_paper_ideas(output=output, online=False)
    assert result["rows_written"] >= 1
    assert output.exists()
    assert output.stat().st_size > 0
