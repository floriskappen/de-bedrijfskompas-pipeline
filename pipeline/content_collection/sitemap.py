"""Sitemap discovery and URL harvesting.

Best-effort: a missing, malformed, or non-XML sitemap is treated as "no
sitemap" and never raises. The caller still proceeds with homepage-link
candidates only.
"""

from __future__ import annotations

import re
from typing import Callable, Final
from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree as ET

from .fetch import FetchResult

MAX_NESTED_SITEMAPS: Final = 3
MAX_URLS_PER_DOC: Final = 500

_SITEMAP_LINE_RE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def discover_sitemap_url(
    homepage_url: str,
    *,
    fetch: Callable[[str], FetchResult],
) -> str:
    """Return the sitemap URL to probe.

    Looks at ``/robots.txt`` for a ``Sitemap:`` directive (case-insensitive);
    if none is found or robots.txt is unreachable, falls back to
    ``<homepage>/sitemap.xml``. Always returns a URL — the caller decides
    whether the response is usable.
    """

    parsed = urlparse(homepage_url)
    robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    fallback = urlunparse((parsed.scheme, parsed.netloc, "/sitemap.xml", "", "", ""))

    result = fetch(robots_url)
    if not result.ok or not result.html:
        return fallback

    match = _SITEMAP_LINE_RE.search(result.html)
    if match:
        return match.group(1).strip()
    return fallback


def harvest_urls(
    sitemap_url: str,
    *,
    fetch: Callable[[str], FetchResult],
    max_nested: int = MAX_NESTED_SITEMAPS,
    max_urls_per_doc: int = MAX_URLS_PER_DOC,
) -> list[str]:
    """Return URLs harvested from a sitemap (or sitemap index).

    Returns an empty list when the response is missing, non-XML, or has
    an unrecognised root element. Sitemap-index nesting is followed for
    at most ``max_nested`` children in declared order.
    """

    return list(_harvest(sitemap_url, fetch=fetch, max_nested=max_nested, max_urls_per_doc=max_urls_per_doc))


def _harvest(
    sitemap_url: str,
    *,
    fetch: Callable[[str], FetchResult],
    max_nested: int,
    max_urls_per_doc: int,
) -> list[str]:
    result = fetch(sitemap_url)
    if not result.ok or not result.html:
        return []

    try:
        root = ET.fromstring(result.html)
    except ET.ParseError:
        return []

    root_local = _local_name(root.tag)
    if root_local == "urlset":
        return _locs(root, limit=max_urls_per_doc)
    if root_local == "sitemapindex":
        out: list[str] = []
        children = _locs(root, limit=max_nested)
        for child_url in children:
            out.extend(
                _harvest(
                    child_url,
                    fetch=fetch,
                    max_nested=0,  # don't recurse deeper than one level
                    max_urls_per_doc=max_urls_per_doc,
                )
            )
        return out
    return []


def _locs(root: ET.Element, *, limit: int) -> list[str]:
    """Return text of `<loc>` descendants (namespace-agnostic) up to ``limit``."""

    out: list[str] = []
    for el in root.iter():
        if _local_name(el.tag) == "loc":
            if el.text and el.text.strip():
                out.append(el.text.strip())
                if len(out) >= limit:
                    break
    return out


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag
