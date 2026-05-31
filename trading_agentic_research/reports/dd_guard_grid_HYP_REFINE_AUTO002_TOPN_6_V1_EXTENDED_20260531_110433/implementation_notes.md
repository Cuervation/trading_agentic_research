# Implementation Notes

- `scripts/run_dd_guard_grid_auto.py` ahora soporta `--previous-report-dir`, `--ensure-runs-output` y `--runs-dir`.
- Cada backtest individual genera un `run_id` ?nico y persiste artefactos en `runs/<run_id>/`.
- `reports/.../variant_runs/<run_id>/run_pointer.json` es solo un puntero al run real; no reemplaza a `runs/`.
- `grid_results.csv` incluye `run_id`, `run_dir`, `report_dir`, `config_path`, `strategy_id`, `completed_at`.
- `combined_grid_results.csv` combina baseline + 180 variantes anteriores + 118 variantes nuevas.
- Para reproducir una corrida individual, abr? `run_dir` desde el CSV y revis? `summary.md`, `metrics.json`, `equity_curve.csv`, `trades.csv` y `run_manifest.json`.
- Para continuar, usar el comando `--resume` del README.
- Limitaci?n: ejecuci?n daily-close; no hay stop intradiario.
