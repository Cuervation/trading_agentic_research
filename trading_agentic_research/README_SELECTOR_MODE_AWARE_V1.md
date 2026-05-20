# Selector Mode-Aware v1

Objetivo: dejar de tratar filas viejas del hypothesis bank como trabajo útil.

Este paquete NO toca parent, baseline, candidate_under_review ni state histórico.

## Archivos

- scripts/research/effective_hypothesis_filter.py
- tools/apply_selector_mode_aware_v1.py
- tools/apply_selector_mode_aware_v1.ps1
- tools/verify_selector_mode_aware_v1.ps1

## Aplicar

```powershell
cd "C:\Pythons\ML-Trading\Momentum\trading_agentic_research"
Expand-Archive "$env:USERPROFILE\Downloads\selector_mode_aware_v1.zip" -DestinationPath "." -Force

.\tools\apply_selector_mode_aware_v1.ps1 -RepoRoot "."
.\tools\verify_selector_mode_aware_v1.ps1 -RepoRoot "."
```

## Commit

```powershell
git add `
  .\scripts\research\effective_hypothesis_filter.py `
  .\scripts\select_next_hypothesis.py `
  .\scripts\research\hypothesis_eligibility.py `
  .\scripts\run_research_batch.py `
  .\scripts\run_research_batch_autonomous.py `
  .\tools\apply_selector_mode_aware_v1.py `
  .\tools\apply_selector_mode_aware_v1.ps1 `
  .\tools\verify_selector_mode_aware_v1.ps1

git commit -m "Make hypothesis selection semantic and mode aware"
git push
```

## Resultado esperado

- El selector no debería elegir ramas con semantic_branch_exhausted.
- Si feature-space está estancado, HYP_FSPACE_* debería bloquearse con feature_space_stalled_literature_mode.
- El preflight debería devolver recommended_mode=literature_or_new_family si no queda trabajo ejecutable útil.
- El batch debería registrar stop_reason feature_space_exhausted_needs_literature_mode cuando el recovery no puede crear trabajo nuevo.
