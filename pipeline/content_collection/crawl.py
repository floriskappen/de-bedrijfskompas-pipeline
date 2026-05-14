"""Link extraction, tier-based selection, and slug derivation."""

from __future__ import annotations

from typing import Final
from urllib.parse import urljoin, urlparse

import tldextract
from lxml import html as lxml_html
from slugify import slugify

# Identity / mission / services — read first.
TIER_1_PATHS: Final = (
    "/about", "/about-us", "/over-ons", "/over",
    "/who-we-are", "/wie-we-zijn",
    "/company", "/bedrijf",
    "/story", "/ons-verhaal", "/history", "/geschiedenis",
    "/manifesto", "/mission", "/missie", "/vision", "/visie",
    "/values", "/waarden",
    "/what-we-do", "/wat-we-doen",
    "/how-we-work", "/hoe-wij-werken", "/aanpak", "/onze-aanpak",
    "/werkwijze", "/process", "/proces",
    "/services", "/diensten",
    "/products", "/producten",
    "/solutions", "/oplossingen",
    "/platform",
    "/expertise", "/expertises", "/specialisaties",
    "/portfolio", "/our-work", "/ons-werk",
    "/sectors", "/sectoren", "/industries", "/branches",
    "/technology", "/technologie", "/research", "/onderzoek",
    "/culture", "/cultuur",
    "/impact", "/sustainability", "/duurzaamheid",
)

# Supporting context.
TIER_2_PATHS: Final = (
    "/cases", "/case-studies", "/projects", "/projecten",
    "/team", "/leadership", "/founders", "/people", "/mensen",
    "/clients", "/klanten", "/customers",
    "/referenties", "/references", "/testimonials",
    "/partners",
    "/locations", "/locaties", "/vestigingen", "/kantoren", "/offices",
    "/careers", "/jobs", "/werken-bij", "/vacatures",
    "/pricing", "/prijzen",
    "/press", "/pers", "/media",
    "/faq", "/veelgestelde-vragen",
    "/contact",
)

# Fresh content — fallback only.
TIER_3_PATHS: Final = (
    "/blog", "/nieuws", "/news", "/actueel", "/updates",
    "/insights", "/inzichten", "/articles", "/artikelen",
)

MAX_SELECTED_URLS: Final = 12
MIN_PAGES_BEFORE_TIER_3: Final = 3
PER_PREFIX_CAP: Final = 2  # Max URLs sharing a single tier-path prefix
# (e.g., at most 2 of /platform, /platform/discover-qualify, ... — prevents
# deep sub-trees from monopolising the slot budget and crowding out other
# tier-1/2 paths like /contact).

_EXCLUDED_EXTENSIONS: Final = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".tar", ".gz", ".rar", ".7z",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".mp3", ".mp4", ".wav", ".mov", ".avi", ".webm",
        ".csv", ".json", ".xml",
    }
)


def normalize_homepage(url: str) -> str:
    """Strip path/query/fragment from a website URL to get the root."""

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"cannot normalize non-absolute URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}/"


def _registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    # Fallback for hostnames without a recognized public-suffix TLD
    # (e.g. ``acme.example``, intranet hosts). Strip a leading ``www.``
    # so subdomain/no-subdomain pairs match.
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def extract_internal_links(homepage_url: str, html: str) -> list[str]:
    """Return absolute internal links found on the homepage HTML.

    Filters out: external domains, non-http(s) schemes, fragment-only,
    ``mailto:`` / ``tel:``, and links whose path ends in a known
    binary/document extension.
    """

    base_domain = _registered_domain(homepage_url)
    if not base_domain:
        return []

    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return []
    doc.make_links_absolute(homepage_url, resolve_base_href=True)

    seen: set[str] = set()
    out: list[str] = []
    for el, _attr, link, _pos in doc.iterlinks():
        if el.tag != "a":
            continue
        parsed = urlparse(link)
        if parsed.scheme not in ("http", "https"):
            continue
        if _registered_domain(link) != base_domain:
            continue
        path = parsed.path or "/"
        # Reject file downloads by extension.
        lower = path.lower()
        if "." in lower.rsplit("/", 1)[-1]:
            ext = "." + lower.rsplit(".", 1)[-1]
            if ext in _EXCLUDED_EXTENSIONS:
                continue
        # Drop fragments and queries to canonicalize.
        canon = f"{parsed.scheme}://{parsed.netloc}{path}"
        if canon == homepage_url:
            continue  # fragment-only or self-links back to the homepage
        if canon in seen:
            continue
        seen.add(canon)
        out.append(canon)
    return out


def _path_matches(url_path: str, tier_path: str) -> bool:
    p = url_path.rstrip("/").lower() or "/"
    t = tier_path.rstrip("/").lower()
    if p == t:
        return True
    return p.startswith(t + "/")


def _classify(url: str) -> tuple[int, int] | None:
    """Return ``(tier, position_in_tier)`` for a URL or ``None``."""

    path = urlparse(url).path or "/"
    for tier_index, tier_paths in enumerate(
        (TIER_1_PATHS, TIER_2_PATHS, TIER_3_PATHS), start=1
    ):
        for pos, tp in enumerate(tier_paths):
            if _path_matches(path, tp):
                return tier_index, pos
    return None


def _path_depth(url: str) -> int:
    """Number of non-empty path segments. ``/platform`` is 1, ``/platform/x`` is 2."""
    path = urlparse(url).path or "/"
    segments = [s for s in path.split("/") if s]
    return len(segments) or 1


def slugify_path(url_path_or_url: str) -> str:
    """Derive the markdown file slug from a URL or URL path.

    Empty path → ``index``. Internal slashes become hyphens. Query and
    fragment are dropped before slugification.
    """

    if "://" in url_path_or_url:
        parsed = urlparse(url_path_or_url)
        path = parsed.path or "/"
    else:
        path = url_path_or_url.split("?", 1)[0].split("#", 1)[0]

    path = path.strip("/")
    if not path:
        return "index"
    return slugify(path.replace("/", "-"))


def select_urls(
    homepage_url: str,
    links: list[str],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Select URLs to fetch, ordered by tier.

    Returns ``(selected, collisions)`` where each item is ``(url, slug)``.
    ``selected`` always starts with the homepage; ``collisions`` lists
    URLs dropped because their slug duplicated one already selected.
    """

    homepage_slug = slugify_path(homepage_url)
    selected: list[tuple[str, str]] = [(homepage_url, homepage_slug)]
    used_slugs: set[str] = {homepage_slug}
    collisions: list[tuple[str, str]] = []

    # Group candidates by tier. Each entry is (depth, position, link) so the
    # subsequent sort can prioritise top-level paths (depth=1) ahead of deeper
    # sub-pages, with tier-position as a tie-breaker.
    tiered: dict[int, list[tuple[int, int, str]]] = {1: [], 2: [], 3: []}
    seen_urls: set[str] = {homepage_url}
    for link in links:
        if link in seen_urls:
            continue
        cls = _classify(link)
        if cls is None:
            continue
        tier, pos = cls
        depth = _path_depth(link)
        tiered[tier].append((depth, pos, link))
        seen_urls.add(link)

    for tier in (1, 2, 3):
        tiered[tier].sort(key=lambda item: (item[0], item[1]))

    def _add(url: str) -> bool:
        slug = slugify_path(url)
        if slug in used_slugs:
            collisions.append((url, slug))
            return False
        used_slugs.add(slug)
        selected.append((url, slug))
        return True

    # Tier 1 and 2 fill the slate up to the cap, with at most PER_PREFIX_CAP
    # URLs sharing the same tier-path prefix (so /platform sub-pages can't
    # eat the budget meant for /contact, /about, etc.). Candidates are
    # pre-sorted depth-then-position so top-level paths land before deeper
    # sub-pages.
    for tier in (1, 2):
        prefix_count: dict[int, int] = {}
        for _depth, pos, link in tiered[tier]:
            if len(selected) >= MAX_SELECTED_URLS:
                break
            if prefix_count.get(pos, 0) >= PER_PREFIX_CAP:
                continue
            if _add(link):
                prefix_count[pos] = prefix_count.get(pos, 0) + 1
        if len(selected) >= MAX_SELECTED_URLS:
            break

    # Tier 3 only when we still need more pages to reach the minimum.
    if len(selected) < MIN_PAGES_BEFORE_TIER_3:
        for _depth, _pos, link in tiered[3]:
            if len(selected) >= MAX_SELECTED_URLS:
                break
            if len(selected) >= MIN_PAGES_BEFORE_TIER_3:
                break
            _add(link)

    return selected, collisions
