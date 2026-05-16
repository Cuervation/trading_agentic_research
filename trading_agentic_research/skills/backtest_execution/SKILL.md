# Backtest Execution

## Goal

Run an approved candidate and produce run artifacts.

## Command

```bash
python scripts/run_backtest.py \
  --weekly-file "PATH_AL_WEEKLY.csv" \
  --daily-folder "PATH_A_DAILY_FOLDER" \
  --strategy-config configs/baseline_momentum_trend_v1.json \
  --project-config configs/project_config.json \
  --run-id EXP_001
```

## Expected Files

- `equity_curve.csv`
- `trades.csv`
- `metrics.json`
- `spy_comparison_daily.csv`
- `spy_comparison_monthly.csv`
- `spy_comparison_yearly.csv`
- `spy_comparison_summary.json`
- `summary.md`

## Failure Checks

- Missing columns: `date`, `ticker`, `close`.
- Empty equity curve.
- Missing SPY data.
- No daily price after signal date.

## Hard Rules

- Do not print full CSVs.
- Agents read `summary.md`, `metrics.json`, compact JSON first.
- Execution does not promote strategies.
