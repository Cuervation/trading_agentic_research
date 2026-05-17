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
from datetime import datetime, timedelta, timezone
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

SEARCH_FAILURE_COOLDOWN_HOURS = 12


def local_seed(
    source_id: str,
    title: str,
    family: str,
    axis: str,
    claim: str,
    mechanism: str,
    ranking_field: str,
    top_n: int,
    exit_rank: int,
    variables: list[str],
    *,
    by: str | None = None,
    market_filter: dict | None = None,
    risk_filters: dict | None = None,
) -> dict:
    overrides: dict[str, Any] = {
        "ranking": {"field": ranking_field, "order": "desc"},
        "entry_rule": {"top_n": top_n, "by": by or ranking_field},
        "exit_rule": {"rank_threshold": exit_rank},
    }
    if market_filter:
        overrides["market_filter"] = market_filter
    if risk_filters:
        overrides["risk_filters"] = risk_filters
    return {
        "source_id": source_id,
        "title": title,
        "author_or_family": "manual research frontier",
        "source_type": "manual_seed",
        "year": 2026,
        "family": family,
        "status": "pending",
        "notes": "Fallback seed used when external literature search is unavailable.",
        "claim": claim,
        "causal_mechanism": mechanism,
        "suggested_variables": variables,
        "possible_rankings": [ranking_field],
        "possible_filters": ["monthly_rebalance", "materiality_probe"],
        "expected_risks": ["duplicate_artifact", "overfit_proxy", "regime_specific_edge"],
        "falsification_rule": "Reject if signal/trades duplicate historical artifacts or if SPY-relative yearly robustness deteriorates.",
        "research_axis": axis,
        "strategy_overrides": overrides,
    }


LOCAL_FALLBACK_SOURCES = [
    {
        "source_id": "SRC_LOCAL_TREND_13_52_BLEND_SEED",
        "title": "Local seed: blend intermediate and long horizon trend for S&P 500 momentum",
        "author_or_family": "manual research frontier",
        "source_type": "manual_seed",
        "year": 2026,
        "family": "trend_following",
        "status": "pending",
        "notes": "Fallback seed used when external literature search is unavailable.",
        "claim": "Intermediate trend strength can catch leadership earlier than pure 52-week ranking while retaining trend persistence.",
        "causal_mechanism": "A 13/26-week trend proxy reacts faster to leadership rotation while still filtering short-term noise.",
        "suggested_variables": ["close_vs_sma26w_pct", "ret_26w_pct", "close_sma_26w_slope_8w_pct"],
        "possible_rankings": ["close_vs_sma26w_pct"],
        "possible_filters": ["monthly_rebalance", "drop_below_rank"],
        "expected_risks": ["whipsaw", "overreacting_to_short_trend"],
        "falsification_rule": "Reject if signal/trades duplicate the champion or if yearly SPY-relative robustness deteriorates.",
        "research_axis": "trend_26w_rotation",
        "strategy_overrides": {
            "ranking": {"field": "close_vs_sma26w_pct", "order": "desc"},
            "entry_rule": {"top_n": 11, "by": "close_vs_sma26w_pct"},
            "exit_rule": {"rank_threshold": 24},
        },
    },
    {
        "source_id": "SRC_LOCAL_LOW_VOL_MOMENTUM_ATR_SEED",
        "title": "Local seed: low volatility momentum crash guard",
        "author_or_family": "manual research frontier",
        "source_type": "manual_seed",
        "year": 2026,
        "family": "low_volatility",
        "status": "pending",
        "notes": "Fallback seed used when external literature search is unavailable.",
        "claim": "Momentum baskets with lower ATR participation should reduce crash sensitivity while preserving most relative strength edge.",
        "causal_mechanism": "High volatility winners are more fragile during de-risking; ATR-aware ranking should lower left-tail exposure.",
        "suggested_variables": ["ret_52w_pct", "atr_14w_pct", "volatility_26w_pct"],
        "possible_rankings": ["atr_14w_pct", "ret_52w_pct"],
        "possible_filters": ["max_volatility_proxy"],
        "expected_risks": ["underparticipation", "defensive_lag"],
        "falsification_rule": "Reject if drawdown does not improve or artifacts duplicate existing low-volatility runs.",
        "research_axis": "atr_guarded_momentum",
        "strategy_overrides": {
            "ranking": {"field": "ret_26w_pct", "order": "desc"},
            "entry_rule": {"top_n": 9, "by": "ret_26w_pct"},
            "exit_rule": {"rank_threshold": 18},
            "risk_filters": {"max_volatility_26w_pct": 35},
        },
    },
    {
        "source_id": "SRC_LOCAL_VOLUME_CONFIRMATION_MOMENTUM_SEED",
        "title": "Local seed: volume-confirmed leadership momentum",
        "author_or_family": "manual research frontier",
        "source_type": "manual_seed",
        "year": 2026,
        "family": "quality",
        "status": "pending",
        "notes": "Fallback seed used when external literature search is unavailable.",
        "claim": "Momentum confirmed by persistent volume participation should identify stronger institutional leadership.",
        "causal_mechanism": "Institutional accumulation tends to combine price leadership with sustained relative volume.",
        "suggested_variables": ["volume_ratio_vs_sma13w", "obv_w_slope_13w_pct", "ret_26w_pct"],
        "possible_rankings": ["volume_ratio_vs_sma13w"],
        "possible_filters": ["liquidity_confirmation"],
        "expected_risks": ["volume_spikes_not_accumulation", "late_leadership"],
        "falsification_rule": "Reject if monthly/yearly SPY comparison worsens or trade list duplicates a prior run.",
        "research_axis": "volume_confirmed_leadership",
        "strategy_overrides": {
            "ranking": {"field": "volume_ratio_vs_sma13w", "order": "desc"},
            "entry_rule": {"top_n": 10, "by": "volume_ratio_vs_sma13w"},
            "exit_rule": {"rank_threshold": 22},
        },
    },
    {
        "source_id": "SRC_LOCAL_CHANNEL_QUALITY_TREND_SEED",
        "title": "Local seed: channel-quality trend leadership",
        "author_or_family": "manual research frontier",
        "source_type": "manual_seed",
        "year": 2026,
        "family": "regime",
        "status": "pending",
        "notes": "Fallback seed used when external literature search is unavailable.",
        "claim": "Higher channel slope quality should favor persistent trends over noisy one-off momentum bursts.",
        "causal_mechanism": "A cleaner regression channel can proxy smoother institutional demand and lower false breakout risk.",
        "suggested_variables": ["channel_slope_pct", "channel_r2", "distance_to_channel_mid_pct"],
        "possible_rankings": ["channel_slope_pct"],
        "possible_filters": ["regression_channel_quality"],
        "expected_risks": ["overfitting_channel_shape", "slow_to_rotation"],
        "falsification_rule": "Reject if it cannot beat SPY in more years or duplicates existing artifacts.",
        "research_axis": "channel_quality_trend",
        "strategy_overrides": {
            "ranking": {"field": "channel_slope_pct", "order": "desc"},
            "entry_rule": {"top_n": 8, "by": "channel_slope_pct"},
            "exit_rule": {"rank_threshold": 20},
            "market_filter": {"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False},
        },
    },
]

LOCAL_FALLBACK_SOURCES.extend(
    [
        local_seed(
            "SRC_LOCAL_RET_12W_ACCELERATION_SEED",
            "Local seed: 12-week acceleration leadership",
            "momentum",
            "ret_12w_acceleration",
            "Recent 12-week acceleration can identify leadership before it appears in slower 52-week ranks.",
            "Momentum underreaction may first appear in intermediate returns before full-year rankings update.",
            "ret_12w_pct",
            11,
            23,
            ["ret_12w_pct", "ret_26w_pct", "ret_52w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_RET_8W_ROTATION_SEED",
            "Local seed: 8-week rotation capture",
            "sector_momentum",
            "ret_8w_rotation",
            "Shorter rotation windows can catch sector leadership transitions faster than annual momentum.",
            "Capital rotates in waves; an 8-week proxy may catch early flow before long-horizon confirmation.",
            "ret_8w_pct",
            9,
            18,
            ["ret_8w_pct", "ret_26w_pct", "volume_ratio_vs_sma13w"],
        ),
        local_seed(
            "SRC_LOCAL_ROC_26W_PERSISTENCE_SEED",
            "Local seed: 26-week rate-of-change persistence",
            "trend_following",
            "roc_26w_persistence",
            "26-week ROC should favor persistent trend continuation with less stale signal than 52-week returns.",
            "Medium-term price persistence captures behavioral anchoring while reducing stale winners.",
            "roc_26w",
            12,
            26,
            ["roc_26w", "close_vs_sma26w_pct", "ret_26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_CLOSE_SMA13_TREND_SEED",
            "Local seed: 13-week SMA trend strength",
            "trend_following",
            "close_vs_sma13w_trend",
            "Distance above a 13-week average can identify shorter trend strength that complements momentum.",
            "A positive moving-average spread proxies fresh demand while reducing dependence on one return window.",
            "close_vs_sma13w_pct",
            10,
            21,
            ["close_vs_sma13w_pct", "weeks_above_sma13_last8"],
        ),
        local_seed(
            "SRC_LOCAL_SMA52_SLOPE_STABILITY_SEED",
            "Local seed: 52-week moving-average slope stability",
            "regime",
            "sma52_slope_stability",
            "Long moving-average slope should select structurally persistent trends over noisy spikes.",
            "Smoother trend slope may reduce false leadership by emphasizing durable uptrends.",
            "close_sma_52w_slope_8w_pct",
            8,
            17,
            ["close_sma_52w_slope_8w_pct", "close_vs_sma52w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_CHANNEL_R2_QUALITY_SEED",
            "Local seed: channel R2 quality filter",
            "quality",
            "channel_r2_quality",
            "High channel fit can distinguish smooth institutional accumulation from noisy momentum.",
            "Better trend fit implies lower path noise and potentially lower crash fragility.",
            "channel_r2",
            10,
            20,
            ["channel_r2", "channel_slope_pct"],
        ),
        local_seed(
            "SRC_LOCAL_DISTANCE_HIGH_52W_BREAKOUT_SEED",
            "Local seed: proximity to 52-week highs",
            "momentum",
            "near_high_52w_breakout",
            "Stocks closer to 52-week highs can sustain leadership via anchoring and breakout behavior.",
            "Price proximity to highs is a simple behavioral anchor that can reinforce continuation.",
            "dist_to_high_52w_pct",
            12,
            24,
            ["dist_to_high_52w_pct", "ret_52w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_DRAWDOWN_13W_RECOVERY_SEED",
            "Local seed: shallow 13-week drawdown leadership",
            "low_volatility",
            "shallow_drawdown_13w",
            "Leaders with shallow recent drawdowns may preserve momentum while avoiding fragile reversals.",
            "Lower recent drawdown can proxy resilient demand during pullbacks.",
            "drawdown_from_high_13w_pct",
            9,
            19,
            ["drawdown_from_high_13w_pct", "ret_26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_RSI14_STRENGTH_SEED",
            "Local seed: RSI14 strength leadership",
            "momentum",
            "rsi14_strength",
            "Moderate-to-high RSI leadership may capture persistent demand not fully represented by returns.",
            "Momentum can manifest as repeated strong closes, captured by RSI-style persistence.",
            "rsi_14w",
            11,
            22,
            ["rsi_14w", "ret_12w_pct", "ret_26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_STOCHASTIC_CONFIRMATION_SEED",
            "Local seed: stochastic confirmation leadership",
            "quality",
            "stochastic_confirmation",
            "High stochastic positioning can confirm that momentum names are closing near recent highs.",
            "Consistent closes near range highs can proxy accumulation quality.",
            "stoch_k_14w",
            10,
            23,
            ["stoch_k_14w", "weekly_close_location_value"],
        ),
        local_seed(
            "SRC_LOCAL_OBV_ACCUMULATION_SEED",
            "Local seed: OBV accumulation leadership",
            "quality",
            "obv_accumulation",
            "OBV slope can identify price leaders with stronger accumulation support.",
            "Volume-confirmed trend may reduce false momentum from thin or fragile rallies.",
            "obv_w_slope_13w_pct",
            10,
            20,
            ["obv_w_slope_13w_pct", "volume_ratio_vs_sma13w", "ret_26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_VOLUME_DRYUP_MOMENTUM_SEED",
            "Local seed: volume dry-up with momentum",
            "low_volatility",
            "volume_dryup_momentum",
            "Momentum with lower relative volume pressure may avoid crowded exhaustion.",
            "Volume dry-up can indicate reduced selling pressure before trend continuation.",
            "volume_ratio_4_vs_13w",
            8,
            18,
            ["volume_ratio_4_vs_13w", "ret_26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_ATR4_LOW_NOISE_SEED",
            "Local seed: low short-term ATR leadership",
            "low_volatility",
            "atr4_low_noise",
            "Lower short-term ATR among leaders may reduce churn and false exits.",
            "Lower realized noise should improve trade persistence for monthly rebalancing.",
            "atr_4w_pct",
            7,
            16,
            ["atr_4w_pct", "ret_26w_pct", "volatility_8w_pct"],
            risk_filters={"max_volatility_26w_pct": 40},
        ),
        local_seed(
            "SRC_LOCAL_VOL26_DEFENSIVE_MOMENTUM_SEED",
            "Local seed: defensive volatility momentum",
            "low_volatility",
            "vol26_defensive_momentum",
            "A lower 26-week volatility proxy can make momentum more defensive during crash regimes.",
            "Longer realized volatility captures fragile winners before they unwind.",
            "volatility_26w_pct",
            6,
            14,
            ["volatility_26w_pct", "ret_52w_pct"],
            risk_filters={"max_volatility_26w_pct": 30},
        ),
        local_seed(
            "SRC_LOCAL_SPY_SLOPE_RISK_ON_SEED",
            "Local seed: SPY slope risk-on momentum",
            "regime",
            "spy_slope_risk_on",
            "Momentum should be more reliable when SPY channel slope confirms a risk-on regime.",
            "Broad-market slope can suppress momentum crash exposure by avoiding weak participation regimes.",
            "ret_52w_pct",
            10,
            20,
            ["ret_52w_pct", "spy_channel_slope_pct"],
            market_filter={"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False},
        ),
        local_seed(
            "SRC_LOCAL_SPY_SMA50_RELAXED_SEED",
            "Local seed: relaxed SPY SMA50 participation",
            "regime",
            "spy_sma50_relaxed",
            "Relaxing the market filter can improve recovery participation after brief SPY trend gaps.",
            "Strict market filters can miss rebounds; a relaxed fallback tests whether recovery participation matters.",
            "ret_26w_pct",
            13,
            28,
            ["ret_26w_pct", "spy_close_vs_sma50_pct"],
            market_filter={"require_positive_trend": False, "fallback_allow_if_missing_spy_metric": True},
        ),
        local_seed(
            "SRC_LOCAL_PRICE_LOCATION_RANGE_SEED",
            "Local seed: weekly close location leadership",
            "momentum",
            "weekly_close_location",
            "Stocks closing high in their weekly range may reflect persistent buying pressure.",
            "Close location compresses intraperiod demand into a ranking proxy complementary to returns.",
            "weekly_close_location_value",
            10,
            21,
            ["weekly_close_location_value", "ret_12w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_GREEN_STREAK_LEADERSHIP_SEED",
            "Local seed: up-streak leadership persistence",
            "momentum",
            "up_streak_leadership",
            "Sustained up-streaks can capture behavioral herding in emerging leaders.",
            "Repeated positive weeks may proxy persistent fund flows into leadership names.",
            "up_streak_weeks",
            8,
            17,
            ["up_streak_weeks", "ret_8w_pct", "ret_12w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_PULLBACK_TO_SMA26_SEED",
            "Local seed: pullback near 26-week trend",
            "value",
            "pullback_to_sma26",
            "Leaders near their 26-week trend can offer better entry after avoiding overextension.",
            "Pullbacks toward a rising medium trend may improve entry quality without abandoning momentum.",
            "distance_to_channel_mid_pct",
            9,
            20,
            ["distance_to_channel_mid_pct", "close_vs_sma26w_pct"],
        ),
        local_seed(
            "SRC_LOCAL_BREAKOUT_VOLUME_CLIMAX_SEED",
            "Local seed: breakout volume climax leadership",
            "can_slim",
            "breakout_volume_climax",
            "Breakout-style volume climax can identify leadership concentration in risk-on markets.",
            "CAN SLIM-style institutional demand often appears as price strength plus abnormal volume.",
            "volume_ratio_vs_sma26w",
            7,
            15,
            ["volume_ratio_vs_sma26w", "ret_26w_pct", "spy_close_vs_sma50_pct"],
            market_filter={"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": True},
        ),
    ]
)


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
            if provider_recently_failed(sources_payload, provider=provider, query=query):
                errors.append({"provider": provider, "query": query, "error": "skipped_recent_failure"})
                continue
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

    if not added:
        for source in local_fallback_sources(sources_payload, max_results=max_results):
            if source["source_id"] in existing_ids:
                continue
            sources_payload.setdefault("sources", []).append(source)
            existing_ids.add(source["source_id"])
            added.append(source)
            if len(added) >= max_results:
                break

    search_event = {
        "searched_at": now_iso(),
        "queries": queries,
        "added_source_ids": [s["source_id"] for s in added],
        "errors": errors,
        "fallback_used": bool(added and all(str(s.get("source_id", "")).startswith("SRC_LOCAL_") for s in added)),
    }
    sources_payload.setdefault("search_events", []).append(search_event)
    write_json(Path(state_dir) / "literature_sources.json", sources_payload)
    return {"added": len(added), "sources": added, "errors": errors, "queries": queries}


def provider_recently_failed(sources_payload: dict, *, provider: str, query: str, cooldown_hours: int = SEARCH_FAILURE_COOLDOWN_HOURS) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    for event in reversed(sources_payload.get("search_events", [])[-20:]):
        searched_at = parse_iso(event.get("searched_at"))
        if searched_at is not None and searched_at < cutoff:
            continue
        for error in event.get("errors", []):
            if error.get("provider") == provider and error.get("query") == query:
                return True
    return False


def local_fallback_sources(sources_payload: dict, *, max_results: int) -> list[dict]:
    existing_ids = {s.get("source_id") for s in sources_payload.get("sources", [])}
    return [dict(source) for source in LOCAL_FALLBACK_SOURCES if source["source_id"] not in existing_ids][:max_results]


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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
    "local_fallback_sources",
    "provider_recently_failed",
]
