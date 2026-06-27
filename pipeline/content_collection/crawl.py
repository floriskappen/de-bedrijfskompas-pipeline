"""Link extraction, tier-based selection, and slug derivation."""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urljoin, urlparse

import tldextract
from lxml import html as lxml_html
from slugify import slugify

_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

# Identity / mission / services — read first.
TIER_1_PATHS: Final = (
    "/about", "/about-us", "/over-ons", "/over", "/colofon",
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
    "/contact", "/contact-us", "/privacy", "/disclaimer", "/algemene-voorwaarden",
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


# A locale/language root path such as ``/nl``, ``/en``, ``/nl-nl`` or ``/en_us``.
# These are kept by ``normalize_homepage`` so a localised homepage (e.g.
# ``brunel.net/nl-nl``) is crawled from its Dutch shell — where the Dutch
# contact/location links live — rather than the global ``/`` shell.
_LOCALE_ROOT_RE: Final = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$")


def normalize_homepage(url: str) -> str:
    """Return the homepage URL to crawl from.

    Query and fragment are always dropped. The path is stripped to ``/`` too,
    except a single-segment locale/language root (``/nl-nl``, ``/en`` ...),
    which is preserved so localised sites are crawled from the right shell.
    """

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"cannot normalize non-absolute URL: {url!r}")
    segments = [s for s in (parsed.path or "").split("/") if s]
    if len(segments) == 1 and _LOCALE_ROOT_RE.match(segments[0].lower()):
        return f"{parsed.scheme}://{parsed.netloc}/{segments[0]}"
    return f"{parsed.scheme}://{parsed.netloc}/"


def _registered_domain(url: str) -> str:
    ext = _TLD_EXTRACT(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    # Fallback for hostnames without a recognized public-suffix TLD
    # (e.g. ``acme.example``, intranet hosts). Strip a leading ``www.``
    # so subdomain/no-subdomain pairs match.
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def has_excluded_extension(path: str) -> bool:
    """Return whether *path*'s last segment ends in a known binary/document extension."""

    lower = (path or "").lower()
    last = lower.rsplit("/", 1)[-1]
    if "." not in last:
        return False
    return ("." + last.rsplit(".", 1)[-1]) in _EXCLUDED_EXTENSIONS


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
        if has_excluded_extension(path):
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


# Address-intent detection. The tier-path lists only match a fixed set of
# leading prefixes, so address-bearing pages whose slug is a *variant*
# (``/contact-2``, ``/support/contact``, ``/nl/contact``, ``/privacy-policy``,
# ``/legal-information``, ``/voorwaarden-en-condities`` ...) are never selected.
# An address-intent slug is recognised anywhere in the path by token/stem so
# these variants enter the normal selection (as tier 2, alongside ``/contact``)
# and are recall-extracted for fact-extraction.
#
# NOTE: fact-extraction keeps its own mirror of this predicate. Stages are
# self-contained (no shared cross-stage helpers), so the two copies must be
# kept in sync by hand if either is widened.
_ADDRESS_INTENT_STEMS: Final = (
    "contact",
    "colofon",
    "disclaimer",
    "privacy",  # privacy, privacy-policy, privacybeleid
    "legal",  # legal, legal-information
    "voorwaarden",  # algemene-voorwaarden, voorwaarden-en-condities
    "condities",
    "terms",  # terms-and-conditions
    "imprint",
    "impressum",
)
# Identity pages that commonly carry the registered address. Matched as whole
# slug tokens (not substrings) because ``over`` would otherwise hit unrelated
# slugs like ``discover-qualify``.
_ADDRESS_INTENT_TOKENS: Final = frozenset({"about", "over", "ons"})

# Address-intent variants land in tier 2 at the front, so on a large site they
# rank ahead of generic tier-2 supporting pages without disturbing the tier-1
# identity pages that precede them.
_ADDRESS_INTENT_POSITION: Final = -1


def is_address_intent_slug(slug: str) -> bool:
    """Return whether *slug* names a contact/legal/privacy/identity address page."""

    s = slug.lower()
    if any(stem in s for stem in _ADDRESS_INTENT_STEMS):
        return True
    return bool(set(s.split("-")) & _ADDRESS_INTENT_TOKENS)


def _classify(url: str) -> tuple[int, int] | None:
    """Return ``(tier, position_in_tier)`` for a URL or ``None``."""

    path = urlparse(url).path or "/"
    for tier_index, tier_paths in enumerate(
        (TIER_1_PATHS, TIER_2_PATHS, TIER_3_PATHS), start=1
    ):
        for pos, tp in enumerate(tier_paths):
            if _path_matches(path, tp):
                return tier_index, pos
    if is_address_intent_slug(slugify_path(url)):
        return 2, _ADDRESS_INTENT_POSITION
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
    # sub-pages, with tier-position as a tie-breaker. Links whose path matches
    # no durable/fresh pattern are stashed for the shallow-link fallback.
    tiered: dict[int, list[tuple[int, int, str]]] = {1: [], 2: [], 3: []}
    fallback: list[tuple[int, str]] = []  # (depth, url) — non-tier shallow-link fallback
    seen_urls: set[str] = {homepage_url}
    for link in links:
        if link in seen_urls:
            continue
        cls = _classify(link)
        if cls is None:
            fallback.append((_path_depth(link), link))
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
            # Address-intent variants share one synthetic position but are
            # distinct pages (contact, privacy, voorwaarden, ...), so the
            # per-prefix cap — meant to stop one prefix's sub-tree from
            # monopolising slots — must not collapse them together.
            capped = pos != _ADDRESS_INTENT_POSITION
            if capped and prefix_count.get(pos, 0) >= PER_PREFIX_CAP:
                continue
            if _add(link) and capped:
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

    # Shallow-link fallback: when durable + fresh tiers still leave fewer than
    # the minimum, fill with the shallowest non-tiered same-domain links
    # (path-depth-1 first, then deeper) so sites using non-standard path
    # conventions (``/learn``, ``/knowledge``) are not silently skipped. Runs
    # last, so a durable or fresh match is never displaced by a generic link.
    if len(selected) < MIN_PAGES_BEFORE_TIER_3:
        fallback.sort(key=lambda item: item[0])
        for _depth, link in fallback:
            if len(selected) >= MIN_PAGES_BEFORE_TIER_3:
                break
            if len(selected) >= MAX_SELECTED_URLS:
                break
            _add(link)

    return selected, collisions
