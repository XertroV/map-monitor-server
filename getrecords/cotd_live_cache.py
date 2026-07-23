"""Live COTD quali rankings in Django/Redis cache; history stays in Postgres."""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.core.cache import cache

# Scrape every ~20s for live freshness; persist history ~once/minute.
COTD_SCRAPE_PERIOD = 20
COTD_HISTORY_PERSIST_PERIOD = 60
# Keep live snapshot longer than one scrape period so restarts/misses don't flap.
COTD_LIVE_CACHE_TTL = 120


def live_rankings_cache_key(challenge_id: int, map_uid: str) -> str:
    return f"cotd_live:{challenge_id}:{map_uid}"


def set_live_rankings(
    challenge_id: int,
    map_uid: str,
    *,
    req_timestamp: int,
    cardinal: int,
    records: list[dict[str, Any]],
) -> None:
    payload = {
        "req_timestamp": req_timestamp,
        "cardinal": cardinal,
        "records": records,
    }
    cache.set(
        live_rankings_cache_key(challenge_id, map_uid),
        payload,
        COTD_LIVE_CACHE_TTL,
    )


def get_live_rankings(challenge_id: int, map_uid: str) -> Optional[dict[str, Any]]:
    return cache.get(live_rankings_cache_key(challenge_id, map_uid))


def ranking_dict(rank: int, score: int, player: str) -> dict[str, Any]:
    return {"score": score, "time": score, "rank": rank, "player": player}


def records_from_models(models) -> list[dict[str, Any]]:
    return [ranking_dict(m.rank, m.score, m.player) for m in models]
