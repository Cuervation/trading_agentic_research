# Synthetic Config Preflight v5

Fixes the EXP_161 gap:

- literature_miner generated a new hypothesis;
- eligibility marked it as selectable because no config file existed yet;
- run_research_batch generated the config;
- research_loop pre-run guard then detected duplicate_strategy_effect_signature.

This patch simulates the config from official parent + strategy_overrides and
compares strategy_effect_signature before selecting the hypothesis.

## Apply

```powershell
cd "C:\Pythons\ML-Trading\Momentum\trading_agentic_research"
Expand-Archive "$env:USERPROFILE\Downloads\synthetic_config_preflight_v5.zip" -DestinationPath "." -Force

python .\tools\apply_synthetic_config_preflight_v5.py
.\tools\verify_synthetic_config_preflight_v5.ps1 -RepoRoot "."
```

## Commit

```powershell
git add .\scripts\research\effective_hypothesis_filter.py .\tools\apply_synthetic_config_preflight_v5.py .\tools\verify_synthetic_config_preflight_v5.ps1
git commit -m "Detect duplicate generated configs before selection"
git push
```
