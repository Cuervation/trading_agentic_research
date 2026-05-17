"""Ingest bibliography sources into compact JSONL principles.

No external YAML dependency: this script expects the simple seeded YAML shape used by
`bibliography/sources.yaml`.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_seed_sources(path: str | Path) -> list[dict]:
    """Read the simple source blocks from sources.yaml."""
    text = Path(path).read_text(encoding="utf-8-sig")
    sources: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "sources:":
            continue
        if line.startswith("- source_id:"):
            if current:
                sources.append(current)
            current = {"source_id": _clean_value(line.split(":", 1)[1])}
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = _clean_value(value)

    if current:
        sources.append(current)
    return sources


def _clean_value(value: str) -> str:
    return value.strip().strip('"')


def main() -> int:
    sources = read_seed_sources("bibliography/sources.yaml")
    print(f"Loaded bibliography sources: {len(sources)}")
    print(json.dumps([s["source_id"] for s in sources], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
