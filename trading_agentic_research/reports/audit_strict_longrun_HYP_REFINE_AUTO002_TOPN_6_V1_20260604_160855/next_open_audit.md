# Next open audit

- open column present/reliable sample: True
- runner supports strict_next_open: True
- next_open_available=True source: data has open and runner sets next_open_available from open_ok.
- Why no strict_next_open scenarios in completed rows: next_open queue is appended after all strict_next_close queue entries; max-scenarios/early stop can be reached before next_open entries.
- Minimal fix: prioritize a small next_open queue before/among close scenarios, or run explicit 6-row mini-validation for selected candidates.
