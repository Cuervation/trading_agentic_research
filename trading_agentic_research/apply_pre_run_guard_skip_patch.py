from pathlib import Path
import sys

path = Path("scripts/run_research_batch.py")

if not path.exists():
    print(f"ERROR: No existe {path}. Ejecutá desde el root del proyecto trading_agentic_research.")
    sys.exit(1)

text = path.read_text(encoding="utf-8-sig")

marker = "PRE_RUN_GUARD_SKIP_DIRECT_PATCH"

if marker in text:
    print("OK: el patch ya estaba aplicado.")
    sys.exit(0)

anchor = '''        audit = read_json(audit_path)

        state["completed"] += 1
        decision = str(audit.get("decision"))
'''

insert = '''        audit = read_json(audit_path)

        # PRE_RUN_GUARD_SKIP_DIRECT_PATCH
        # Pre-run guard blocks are useful learning/cleanup events, but they are
        # not real backtests. Do not count them as completed strategy runs and
        # do not increment consecutive_rejections, otherwise a batch can stop
        # after cleaning only 2 exhausted/duplicate hypotheses.
        pre_run_blocked = bool(
            audit.get("pre_run_duplicate_guard")
            or audit.get("pre_run_blocked")
            or audit.get("audit_status") == "completed_preflight_block"
            or "duplicate_preflight_blocked" in set(audit.get("flags") or [])
        )
        if pre_run_blocked:
            state["pre_run_guard_blocks"] = int(state.get("pre_run_guard_blocks", 0) or 0) + 1
            state.setdefault("history", []).append(
                {
                    "iteration": state["completed"] + 1,
                    "run_id": latest_run,
                    "hypothesis_id": hypothesis_id,
                    "family": str(hypothesis.get("family")),
                    "decision": "pre_run_guard_blocked",
                    "reason": (
                        (audit.get("pre_run_duplicate_guard") or {}).get("reason")
                        or audit.get("audit_status")
                    ),
                    "parent_strategy_config": effective_parent_strategy_config,
                    "pre_run_blocked": True,
                }
            )
            _save_batch_state(args.state_dir, state)
            print(
                f"Skipping completed-run counter for pre-run guard block: "
                f"{latest_run} / {hypothesis_id}"
            )
            max_pre_run_blocks = max(20, int(args.max_runs) * 10)
            if int(state.get("pre_run_guard_blocks", 0) or 0) >= max_pre_run_blocks:
                state["status"] = "stopped"
                state["stop_reason"] = f"too_many_pre_run_guard_blocks:{max_pre_run_blocks}"
                _save_batch_state(args.state_dir, state)
                print(f"Stopping: too many pre-run guard blocks ({max_pre_run_blocks}).")
                break
            continue

        state["completed"] += 1
        decision = str(audit.get("decision"))
'''

if anchor not in text:
    print("ERROR: No encontré el bloque anchor en scripts/run_research_batch.py.")
    print("Buscado:")
    print(anchor)
    sys.exit(1)

text = text.replace(anchor, insert, 1)
path.write_text(text, encoding="utf-8")

print("PATCH_OK: run_research_batch.py ahora no cuenta bloqueos pre-run como corridas reales.")
