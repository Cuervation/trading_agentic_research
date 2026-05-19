Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Compiling changed and related files..." -ForegroundColor Cyan
python -m py_compile .\scripts\research\feature_space_expansion_factory.py
python -m py_compile .\scripts\run_research_batch.py
python -m py_compile .\scripts\research\cooldown_governance.py
python -m py_compile .\scripts\score_hypothesis_against_memory.py
python -m py_compile .\scripts\run_research_batch_autonomous.py

Write-Host "Checking cooldown contract..." -ForegroundColor Cyan
python -c "from scripts.select_next_hypothesis import read_json; from scripts.research.cooldown_governance import hard_active_cooldown_family_names, hard_active_cooldown_families; c=read_json('state/subspace_cooldowns.json'); print('from_payload=', hard_active_cooldown_family_names(c)); print('from_state_dir=', hard_active_cooldown_families('state')); print('from_dict_compat=', hard_active_cooldown_families(c))"

Write-Host "OK: cooldown contract compiled and dict/state_dir calls are accepted." -ForegroundColor Green
