"""Search for new bibliography when local hypotheses are exhausted.

The implementation is deliberately dependency-free and auditable:
- Semantic Scholar is the primary provider.
- Crossref is the fallback provider.
- Network errors do not stop the research loop; they are recorded in state.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomous import now_iso, read_json, write_json

Fetcher = Callable[[str], dict[str, Any]]

DEFAULT_SEARCH_QUERIES = [
    {"query": "S&P 500 cross-sectional momentum 52 week ranking strategy", "family": "momentum"},
    {"query": "momentum crash low volatility betting against beta equity strategy", "family": "low_volatility"},
    {"query": "sector industry momentum equity strategy S&P 500", "family": "sector_momentum"},
    {"query": "trend following volatility targeting equity index strategy", "family": "regime"},
    {"query": "quality investing momentum profitability equity strategy", "family": "quality"},
    {"query": "adaptive markets regime switching momentum strategy", "family": "regime"},
]


def default_fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "trading-agentic-research/0.1 (bibliography discovery; no email configured)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec - public bibliography APIs only
        return json.loads(response.read().decode("utf-8"))


def search_new_literature(
    *,
    state_dir: str | Path = "state",
    max_results: int = 5,
    fetch_json: Fetcher = default_fetch_json,
) -> dict:
    """Search public bibliography APIs and append new sources to state."""
    sources_payload = read_json(Path(state_dir) / "literature_sources.json", {"version": 1, "sources": []})
    existing_ids = {s.get("source_id") for s in sources_payload.get("sources", [])}
    queries = choose_search_queries(state_dir)
    added: list[dict] = []
    errors: list[dict] = []

    for query_payload in queries:
        query = query_payload["query"]
        family = query_payload["family"]
        provider_rows: list[dict] = []
        for provider, searcher in (
            ("semantic_scholar", search_semantic_scholar),
            ("crossref", search_crossref),
        ):
            try:
                provider_rows = searcher(query=query, family=family, limit=max_results, fetch_json=fetch_json)
            except Exception as exc:  # keep loop alive; record failure
                errors.append({"provider": provider, "query": query, "error": str(exc)})
                provider_rows = []
            if provider_rows:
                break

        for source in provider_rows:
            if source["source_id"] in existing_ids:
                continue
            sources_payload.setdefault("sources", []).append(source)
            existing_ids.add(source["source_id"])
            added.append(source)
            if len(added) >= max_results:
                break
        if len(added) >= max_results:
            break

    search_event = {
        "searched_at": now_iso(),
        "queries": queries,
        "added_source_ids": [s["source_id"] for s in added],
        "errors": errors,
    }
    sources_payload.setdefault("search_events", []).append(search_event)
    write_json(Path(state_dir) / "literature_sources.json", sources_payload)
    return {"added": len(added), "sources": added, "errors": errors, "queries": queries}


def choose_search_queries(state_dir: str | Path) -> list[dict]:
    """Choose search queries from exhausted axes, falling back to default frontier."""
    cooldowns = read_json(Path(state_dir) / "axis_cooldowns.json", {"axes": {}})
    exhausted = [
        key
        for key, value in (cooldowns.get("axes") or {}).items()
        if value.get("status") == "axis_exhausted"
    ]
    if not exhausted:
        return list(DEFAULT_SEARCH_QUERIES)

    queries = []
    for key in exhausted:
        family, axis = key.split(":", 1) if ":" in key else ("mixed", key)
        queries.append(
            {
                "query": f"S&P 500 equity strategy {family.replace('_', ' ')} {axis.replace('_', ' ')} recent evidence",
                "family": normalize_family(family),
            }
        )
    queries.extend(DEFAULT_SEARCH_QUERIES)
    return dedupe_queries(queries)


def search_semantic_scholar(*, query: str, family: str, limit: int, fetch_json: Fetcher) -> list[dict]:
    fields = "title,authors,year,venue,url,abstract,citationCount,externalIds"
    params = urllib.parse.urlencode({"query": query, "limit": limit, "fields": fields})
    payload = fetch_json(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}")
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    return [semantic_scholar_source(row, query=query, family=family) for row in rows if row.get("title")]


def search_crossref(*, query: str, family: str, limit: int, fetch_json: Fetcher) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "query.bibliographic": query,
            "rows": limit,
            "select": "DOI,title,author,published-print,published-online,container-title,abstract,URL,type,is-referenced-by-count",
        }
    )
    payload = fetch_json(f"https://api.crossref.org/v1/works?{params}")
    rows = ((payload.get("message") or {}).get("items") or []) if isinstance(payload, dict) else []
    return [crossref_source(row, query=query, family=family) for row in rows if row.get("title")]


def semantic_scholar_source(row: dict, *, query: str, family: str) -> dict:
    external = row.get("externalIds") or {}
    doi = external.get("DOI")
    authors = row.get("authors") or []
    author_text = ", ".join(a.get("name", "") for a in authors[:3] if a.get("name")) or "unknown"
    return {
        "source_id": source_id_for("S2", doi or row.get("paperId") or row.get("title")),
        "title": clean_title(row.get("title")),
        "author_or_family": author_text,
        "source_type": "paper",
        "year": row.get("year"),
        "family": family,
        "status": "pending",
        "notes": f"Discovered via Semantic Scholar query: {query}",
        "url": row.get("url"),
        "doi": doi,
        "citation_count": row.get("citationCount"),
        "abstract": truncate_text(row.get("abstract"), 800),
    }


def crossref_source(row: dict, *, query: str, family: str) -> dict:
    title = clean_title((row.get("title") or [""])[0])
    authors = row.get("author") or []
    author_text = ", ".join(
        " ".join(part for part in [a.get("given"), a.get("family")] if part)
        for a in authors[:3]
    ) or "unknown"
    return {
        "source_id": source_id_for("CR", row.get("DOI") or title),
        "title": title,
        "author_or_family": author_text,
        "source_type": source_type_from_crossref(row.get("type")),
        "year": extract_crossref_year(row),
        "family": family,
        "status": "pending",
        "notes": f"Discovered via Crossref query: {query}",
        "url": row.get("URL"),
        "doi": row.get("DOI"),
        "citation_count": row.get("is-referenced-by-count"),
        "abstract": truncate_text(strip_html(row.get("abstract")), 800),
    }


def source_id_for(prefix: str, value: Any) -> str:
    raw = str(value or "unknown").lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return f"SRC_{prefix}_{raw[:80].upper()}"


def clean_title(value: Any) -> str:
    return " ".join(str(value or "untitled").split())


def truncate_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def strip_html(value: Any) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))


def extract_crossref_year(row: dict) -> int | None:
    for key in ("published-print", "published-online"):
        parts = (((row.get(key) or {}).get("date-parts")) or [[]])[0]
        if parts:
            return int(parts[0])
    return None


def source_type_from_crossref(value: str | None) -> str:
    if value in {"book", "book-chapter"}:
        return "book"
    if value in {"journal-article", "proceedings-article"}:
        return "paper"
    return "article"


def normalize_family(value: str) -> str:
    value = (value or "mixed").strip()
    allowed = {
        "momentum",
        "trend_following",
        "can_slim",
        "quality",
        "low_volatility",
        "sector_momentum",
        "regime",
        "value",
        "mixed",
    }
    return value if value in allowed else "mixed"


def dedupe_queries(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = (row["query"], row["family"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


__all__ = [
    "search_new_literature",
    "search_semantic_scholar",
    "search_crossref",
    "choose_search_queries",
]
