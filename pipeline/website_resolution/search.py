"""DDGS-backed search wrapper.

Isolated from `core.py` so an alternate search backend can be swapped in
without touching the resolver. Reliability of any single DDGS engine
fluctuates, so we try a fallback chain and accept the first engine that
returns at least one result.
"""

from __future__ import annotations

import time

from ddgs import DDGS

# Engine fallback chain. Edit this list (top of module) to change order or
# add/remove engines without touching call sites.
#
# Order is empirical: on the 3-company test set with region=nl-nl, yandex's
# top hit was the correct company website in all 3 cases. mojeek and brave
# each got 2/3. duckduckgo/grokipedia/yahoo/wikipedia returned no results or
# only encyclopedia entries. See openspec/.../design.md for the probe data.
ENGINES: list[str] = ["yandex", "mojeek", "brave"]

REGION = "nl-nl"
RETRY_SLEEP_SECONDS = 5.0


def search(query: str) -> str | None:
    """Return the top result's URL for `query`, or `None` if every engine
    returned zero results.

    Each engine call is wrapped in a single retry: on exception, sleep
    `RETRY_SLEEP_SECONDS` and try the same engine once more. A second
    failure propagates (the caller decides how to record it).
    """

    for engine in ENGINES:
        url = _query_engine(engine, query)
        if url is not None:
            return url
    return None


def _query_engine(engine: str, query: str) -> str | None:
    """Query one engine with one retry. Return top hit URL or None."""

    try:
        return _top_hit(engine, query)
    except Exception:
        time.sleep(RETRY_SLEEP_SECONDS)
        return _top_hit(engine, query)


def _top_hit(engine: str, query: str) -> str | None:
    with DDGS() as ddgs:
        results = ddgs.text(query, region=REGION, backend=engine, max_results=1)
        for hit in results:
            url = hit.get("href") or hit.get("url")
            if url:
                return url
    return None
