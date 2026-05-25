import json

from scripts.run_dd_first_autonomous_daemon import generate_batch_specs


def test_daemon_generates_five_causal_dynamic_specs(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"strategies": []}), encoding="utf-8")
    axis_memory = {"axes": {"dynamic_regime_exposure": {"status": "active"}}}

    specs = generate_batch_specs(
        batch_size=5,
        registry_path=str(registry),
        axis_memory=axis_memory,
        weekly_columns={"close_vs_sma52w_pct", "close_vs_sma20w_pct"},
        allow_second_dimension=False,
    )

    assert len(specs) == 5
    assert {s["axis"] for s in specs} == {"dynamic_regime_exposure"}
    assert all("dynamic_regime_exposure_pct" in next(iter(s["patch"])) or "dynamic_regime_exposure_pct" in str(s["patch"]) for s in specs)
