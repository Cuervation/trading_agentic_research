"""Executor planning for autonomous research.

The vertical slice defaults to mocked execution, but the plan is explicit and
keeps the agreed research windows at 4, 8, 24, and 52 weeks.  No 156-week
window is introduced by default.
"""

from __future__ import annotations

DEFAULT_RESEARCH_WINDOWS_WEEKS = (4, 8, 24, 52)


def build_execution_plan(hypothesis_id: str, *, windows_weeks: tuple[int, ...] = DEFAULT_RESEARCH_WINDOWS_WEEKS, mock: bool = True) -> dict:
    return {
        "hypothesis_id": hypothesis_id,
        "windows_weeks": list(windows_weeks),
        "mock_execution": mock,
        "uses_existing_backtester": not mock,
    }


__all__ = ["DEFAULT_RESEARCH_WINDOWS_WEEKS", "build_execution_plan"]
