Modelo recomendado: GPT-5.4, esfuerzo medio.

Prompt para Codex:

Aplicar `autonomy_quality_v2` en:

C:\Pythons\ML-Trading\Momentum\trading_agentic_research

Comandos:

.\autonomy_quality_v2\tools\apply_autonomy_quality_v2.ps1 -RepoRoot "."
.\autonomy_quality_v2\tools\verify_autonomy_quality_v2.ps1 -RepoRoot "."

Luego correr batch chico:

python .\scripts\run_research_batch_autonomous.py `
  --max-runs 5 `
  --max-recovery-cycles 2 `
  --project-config ".\configs\project_config.json" `
  --state-dir ".\state" `
  --runs-dir ".\runs" `
  --reports-dir ".\reports"

Validar:
- no ImportError
- no TypeError
- Test-Path de los 5 módulos nuevos da True
- se genera reports/autonomy_quality_report.md
- se genera reports/spy_feature_diagnostics.md
- AUTO_002 sigue como parent oficial
- baseline promotion sigue bloqueado
