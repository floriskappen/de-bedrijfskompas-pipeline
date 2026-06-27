"""Tests for the content-collection stage."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from pipeline.content_collection import core as core_module
from pipeline.content_collection import fetch as fetch_module
from pipeline.content_collection import crawl, extract
from pipeline.content_collection.crawl import (
    extract_internal_links,
    select_urls,
    slugify_path,
)
from pipeline.content_collection.extract import extract_footer_text, extract_favicon_url
from pipeline.content_collection.fetch import FetchResult

REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"


@pytest.fixture(autouse=True)
def _reset_trafilatura_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """trafilatura keeps a module-level LRU of seen blocks; reset per test."""

    from trafilatura import deduplication

    deduplication.LRU_TEST.clear()
    monkeypatch.setattr(
        core_module.render,
        "render_homepage",
        lambda url: FetchResult(
            url=url,
            html=None,
            error="headless unavailable",
            error_kind="headless",
        ),
    )


# ---------------------------------------------------------------------------
# crawl: link extraction
# ---------------------------------------------------------------------------


def _wrap(body: str) -> str:
    return f"<html><body>{body}</body></html>"


def test_extract_internal_links_filters() -> None:
    html = _wrap(
        """
        <a href="/about">About</a>
        <a href="https://acme.example/team">Team</a>
        <a href="https://other.example/x">External</a>
        <a href="mailto:hi@acme.example">Mail</a>
        <a href="tel:+31123">Phone</a>
        <a href="#mission">Anchor</a>
        <a href="/flyer.pdf">PDF</a>
        <a href="/logo.png">PNG</a>
        <a href="/archive.zip">ZIP</a>
        <a href="/about-us/our-story">Story</a>
        """
    )
    links = extract_internal_links("https://acme.example/", html)
    paths = sorted(l.replace("https://acme.example", "") for l in links)
    assert paths == ["/about", "/about-us/our-story", "/team"]


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("/app/uploads/2023/05/logo-about.jpg", True),  # image whose slug has an "about" token
        ("/files/report.pdf", True),
        ("/archive.zip", True),
        ("/nl/contact", False),
        ("/privacy-policy", False),
        ("/", False),
    ],
)
def test_has_excluded_extension(path: str, excluded: bool) -> None:
    assert crawl.has_excluded_extension(path) is excluded


# ---------------------------------------------------------------------------
# crawl: select_urls — tier ordering, case/prefix/trailing-slash, cap
# ---------------------------------------------------------------------------


def test_select_urls_tier_ordering_and_matching() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    links = [
        base + "/About",  # tier-1, case-insensitive
        base + "/over-ons/",  # tier-1, Dutch + trailing slash
        base + "/about-us/our-story",  # tier-1, prefix match on /about-us
        base + "/diensten",  # tier-1
        base + "/team",  # tier-2
        base + "/contact",  # tier-2
        base + "/careers",  # tier-2
        base + "/blog",  # tier-3, must not appear (cap reached / tier-1 fills)
        base + "/whatever",  # not classified
    ]
    selected, collisions = select_urls(homepage, links)
    assert collisions == []
    urls = [u for u, _ in selected]
    # Homepage first.
    assert urls[0] == homepage
    # Tier-1 entries precede tier-2 entries.
    tier1_set = {base + "/About", base + "/over-ons/", base + "/about-us/our-story", base + "/diensten"}
    tier2_set = {base + "/team", base + "/contact", base + "/careers"}
    tier1_positions = [i for i, u in enumerate(urls) if u in tier1_set]
    tier2_positions = [i for i, u in enumerate(urls) if u in tier2_set]
    assert tier1_positions and tier2_positions
    assert max(tier1_positions) < min(tier2_positions)
    # Tier-3 excluded because durable count ≥ 3.
    assert base + "/blog" not in urls
    # Unclassified excluded.
    assert base + "/whatever" not in urls


def test_select_urls_enforces_cap() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # 14 tier-1 candidates, all distinct slugs and distinct tier-path prefixes.
    links = [
        base + p for p in (
            "/about", "/over-ons", "/mission", "/vision", "/services",
            "/diensten", "/products", "/oplossingen", "/platform",
            "/impact", "/expertise", "/portfolio", "/sectors", "/technology",
        )
    ]
    selected, _ = select_urls(homepage, links)
    assert len(selected) == 12  # MAX_SELECTED_URLS


def test_select_urls_top_level_beats_subpages() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # /platform sub-pages (depth 2) compete with /contact (depth 1, tier-2).
    # With depth-first ordering AND per-prefix cap=2, /contact must be selected
    # while only 2 of the /platform/* sub-pages get in.
    links = [
        base + "/platform",
        base + "/platform/a", base + "/platform/b", base + "/platform/c",
        base + "/platform/d", base + "/platform/e", base + "/platform/f",
        base + "/contact",
    ]
    selected, _ = select_urls(homepage, links)
    urls = {u for u, _ in selected}
    assert base + "/contact" in urls
    # Per-prefix cap: at most 2 URLs matching the /platform tier-path prefix.
    platform_count = sum(1 for u in urls if u.startswith(base + "/platform"))
    assert platform_count <= 2


def test_select_urls_per_prefix_cap_leaves_room_for_others() -> None:
    # Even without competing top-level paths from the same depth, the per-prefix
    # cap must hold so other prefixes get a turn.
    base = "https://acme.example"
    homepage = base + "/"
    links = [
        base + "/platform",
        base + "/platform/a", base + "/platform/b", base + "/platform/c",
        base + "/about", base + "/contact", base + "/careers",
    ]
    selected, _ = select_urls(homepage, links)
    urls = {u for u, _ in selected}
    platform_count = sum(1 for u in urls if u.startswith(base + "/platform"))
    assert platform_count <= 2
    # /about, /contact, /careers all land — they're not crowded out.
    assert base + "/about" in urls
    assert base + "/contact" in urls
    assert base + "/careers" in urls


def test_select_urls_tier3_fallback() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # Only 1 durable match → tier-3 fills to reach 3.
    links_with_blog = [base + "/about", base + "/blog", base + "/news"]
    selected, _ = select_urls(homepage, links_with_blog)
    urls = [u for u, _ in selected]
    assert base + "/blog" in urls or base + "/news" in urls
    assert len(selected) >= 3

    # 3+ durable matches → tier-3 excluded.
    links_with_3_durable = [base + "/about", base + "/team", base + "/contact", base + "/blog"]
    selected, _ = select_urls(homepage, links_with_3_durable)
    urls = [u for u, _ in selected]
    assert base + "/blog" not in urls


def test_select_urls_shallow_link_fallback_recovers_nonstandard_path() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # /learn (depth 1) + two depth-2 non-standard pages; none match a durable/fresh pattern.
    links = [base + "/learn/roadmaps", base + "/learn/fundamentals", base + "/learn"]
    selected, _ = select_urls(homepage, links)
    urls = [u for u, _ in selected]
    # Homepage + /learn (depth 1) recovered first, then a depth-2 link to reach the minimum.
    assert base + "/learn" in urls
    assert base + "/learn/roadmaps" in urls
    assert urls.index(base + "/learn") < urls.index(base + "/learn/roadmaps")
    assert len(selected) >= 3


def test_select_urls_shallow_link_fallback_does_not_displace_durable() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    links = [base + "/about", base + "/learn"]  # durable + non-standard
    selected, _ = select_urls(homepage, links)
    urls = [u for u, _ in selected]
    assert base + "/about" in urls  # durable wins
    assert base + "/learn" in urls  # fallback fills the remaining slot
    assert urls.index(base + "/about") < urls.index(base + "/learn")


def test_select_urls_shallow_link_fallback_skipped_when_minimum_met() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # 3 durable matches already meet the minimum → no fallback selection.
    links = [base + "/about", base + "/team", base + "/contact", base + "/learn"]
    selected, _ = select_urls(homepage, links)
    urls = [u for u, _ in selected]
    assert base + "/learn" not in urls  # fallback not needed, generic link excluded


def test_select_urls_slug_collision_recorded() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    # /about and /about/ both slugify to "about" — second one collides.
    # We use distinct paths that nonetheless slugify identically.
    links = [base + "/about", base + "/about/"]
    selected, collisions = select_urls(homepage, links)
    slugs = [s for _, s in selected]
    assert slugs.count("about") == 1
    assert any(slug == "about" for _, slug in collisions)


# ---------------------------------------------------------------------------
# crawl: slugify_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.example/", "index"),
        ("https://acme.example/about-us", "about-us"),
        ("https://acme.example/about/team", "about-team"),
        ("https://acme.example/over-ons/", "over-ons"),
        ("https://acme.example/about?lang=en#section", "about"),
        ("/", "index"),
        ("/about-us", "about-us"),
    ],
)
def test_slugify_path(url: str, expected: str) -> None:
    assert slugify_path(url) == expected


# ---------------------------------------------------------------------------
# extract: footer
# ---------------------------------------------------------------------------


def test_footer_captures_address() -> None:
    html = _wrap("<footer>Acme B.V. — Europalaan 100, 3526 KS Utrecht</footer>")
    out = extract_footer_text(html)
    assert out is not None
    assert "Europalaan 100, 3526 KS Utrecht" in out


def test_footer_multiple_concatenated() -> None:
    html = _wrap("<footer>Top footer</footer><div><footer>Sub footer</footer></div>")
    out = extract_footer_text(html)
    assert out is not None
    assert "Top footer" in out
    assert "Sub footer" in out


def test_footer_strips_embedded_style_and_script() -> None:
    html = _wrap(
        "<footer>"
        "<style>.x { color: red; --grid-gutter: 6vw; }</style>"
        "<script>window.foo = function(){};</script>"
        "Europalaan 100, Utrecht"
        "</footer>"
    )
    out = extract_footer_text(html)
    assert out is not None
    assert "Europalaan 100, Utrecht" in out
    assert "color: red" not in out
    assert "function" not in out
    assert "{" not in out


def test_footer_absent_or_empty() -> None:
    assert extract_footer_text(_wrap("<p>no footer</p>")) is None
    assert extract_footer_text(_wrap("<footer>   \n  </footer>")) is None


def test_footer_block_boundaries_preserved() -> None:
    # Block-level elements emit newlines so sibling inline elements don't fuse
    # into single tokens (e.g. LinkedIn + Instagram → LinkedInInstagram), and
    # so the downstream postcode anchor sees Smallepad / 3811 MG / Amersfoort
    # on separate "lines" for clean field extraction.
    html = _wrap(
        "<footer>"
        "<p>Smallepad 32</p>"
        "<p>3811 MG Amersfoort</p>"
        "<div>Volg ons</div>"
        "<a>LinkedIn</a><a>Instagram</a>"
        "</footer>"
    )
    out = extract_footer_text(html)
    assert out is not None
    lines = out.split("\n")
    assert "Smallepad 32" in lines
    assert "3811 MG Amersfoort" in lines
    assert "Volg ons" in lines
    # Inline siblings must NOT fuse; each is on its own (line or token).
    assert "LinkedInInstagram" not in out
    assert "LinkedIn" in out and "Instagram" in out


def test_favicon_url_ranking_and_selection() -> None:
    # 1. Preferred exact size 512x512
    html = """
    <html>
      <head>
        <link rel="icon" href="/favicon-16.png" sizes="16x16">
        <link rel="icon" href="/favicon-192.png" sizes="192x192">
        <link rel="icon" href="/favicon-512.png" sizes="512x512">
        <link rel="shortcut icon" href="/favicon.ico">
      </head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon-512.png"

    # 2. Preferred larger sizes >= 512, choosing the smallest among them (closest to 512)
    html = """
    <html>
      <head>
        <link rel="icon" href="/favicon-1024.png" sizes="1024x1024">
        <link rel="icon" href="/favicon-2048.png" sizes="2048x2048">
      </head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon-1024.png"

    # 3. Preferred largest size < 512 when no sizes >= 512 exist
    html = """
    <html>
      <head>
        <link rel="icon" href="/favicon-16.png" sizes="16x16">
        <link rel="icon" href="/favicon-192.png" sizes="192x192">
        <link rel="icon" href="/favicon-32.png" sizes="32x32">
      </head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon-192.png"

    # 4. Sizes="any" treated as 512
    html = """
    <html>
      <head>
        <link rel="icon" href="/favicon-any.svg" sizes="any">
        <link rel="icon" href="/favicon-192.png" sizes="192x192">
      </head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon-any.svg"

    # 5. Tie-breaker prefers modern icon/apple-touch-icon over shortcut icon
    html = """
    <html>
      <head>
        <link rel="shortcut icon" href="/favicon-legacy.png" sizes="192x192">
        <link rel="apple-touch-icon" href="/favicon-modern.png" sizes="192x192">
      </head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon-modern.png"


def test_favicon_fallback_and_null_status() -> None:
    # No link tags -> fallback to favicon.ico
    html = """
    <html>
      <head></head>
      <body></body>
    </html>
    """
    url = extract_favicon_url("https://acme.example", html)
    assert url == "https://acme.example/favicon.ico"

    # Invalid HTML / parsing error -> fallback to favicon.ico
    url = extract_favicon_url("https://acme.example", "invalid html < < <")
    assert url == "https://acme.example/favicon.ico"


# ---------------------------------------------------------------------------
# fetch: User-Agent
# ---------------------------------------------------------------------------


def test_fetch_sends_browser_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict[str, str] = {}

    class FakeUA:
        @property
        def random(self) -> str:
            return (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
            )

    class FakeClient:
        def __init__(self, *, follow_redirects, timeout, headers):
            captured_headers.update(headers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url: str):
            return types.SimpleNamespace(status_code=200, text="<html></html>", url=url)

    monkeypatch.setitem(sys.modules, "fake_useragent", types.SimpleNamespace(UserAgent=FakeUA))
    monkeypatch.setattr(fetch_module.httpx, "Client", FakeClient)

    result = fetch_module.get("https://acme.example/")

    assert result.ok
    ua = captured_headers["User-Agent"]
    assert "Mozilla/5.0" in ua
    assert "Chrome/" in ua
    assert "de-bedrijfskompas" not in ua


def test_fetch_falls_back_to_pinned_ua(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict[str, str] = {}

    class BrokenUA:
        @property
        def random(self) -> str:
            raise RuntimeError("no UA")

    class FakeClient:
        def __init__(self, *, follow_redirects, timeout, headers):
            captured_headers.update(headers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url: str):
            return types.SimpleNamespace(status_code=200, text="<html></html>", url=url)

    monkeypatch.setitem(sys.modules, "fake_useragent", types.SimpleNamespace(UserAgent=BrokenUA))
    monkeypatch.setattr(fetch_module.httpx, "Client", FakeClient)

    result = fetch_module.get("https://acme.example/")

    assert result.ok
    assert captured_headers["User-Agent"] == fetch_module.PINNED_BROWSER_USER_AGENT
    assert "de-bedrijfskompas" not in captured_headers["User-Agent"]


# ---------------------------------------------------------------------------
# extract: structured address capture
# ---------------------------------------------------------------------------


def test_structured_text_from_jsonld() -> None:
    html = _wrap(
        """
        <script type="application/ld+json">
        {"@type":"Organization","address":{"@type":"PostalAddress","streetAddress":"Stadsplateau 34","postalCode":"3521 AZ","addressLocality":"Utrecht"}}
        </script>
        """
    )
    out = extract.extract_structured_text(html)
    assert out is not None
    assert "Stadsplateau 34" in out
    assert "3521 AZ" in out
    assert "Utrecht" in out


def test_structured_text_from_address_element() -> None:
    out = extract.extract_structured_text(
        _wrap("<address>Europalaan 100, 3526 KS Utrecht</address>")
    )
    assert out == "Europalaan 100, 3526 KS Utrecht"


def test_structured_text_null_when_absent() -> None:
    assert extract.extract_structured_text(_wrap("<main>No address here</main>")) is None


def test_extract_visible_text_recovers_dropped_address() -> None:
    # trafilatura recall drops address cards; the raw visible-text surface keeps
    # them. The block-break walk puts the postcode on a line the anchor reaches.
    html = _wrap(
        "<main><h1>Contact</h1></main>"
        "<aside class='office-card'><div>Princetonlaan 6</div>"
        "<div>3584 CB Utrecht</div></aside>"
    )
    out = extract.extract_visible_text(html)
    assert out is not None
    assert "Princetonlaan 6" in out
    assert "3584 CB Utrecht" in out


def test_extract_visible_text_strips_script_and_style() -> None:
    html = _wrap("<style>.x{color:red}</style><script>var a=1;</script><p>Hello</p>")
    out = extract.extract_visible_text(html)
    assert out == "Hello"


# ---------------------------------------------------------------------------
# crawl: address-intent classification & locale roots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("contact", True),
        ("contact-2", True),
        ("support-contact", True),
        ("nl-contact", True),
        ("contact-ons", True),
        ("privacy", True),
        ("privacy-policy", True),
        ("privacybeleid", True),
        ("legal-information", True),
        ("voorwaarden-en-condities", True),
        ("algemene-voorwaarden", True),
        ("colofon", True),
        ("disclaimer", True),
        ("over-ons", True),
        ("about-us", True),
        ("platform", False),
        ("discover-qualify", False),  # contains "over" only as a substring, not a token
        ("index", False),
        ("team", False),
        ("blog", False),
    ],
)
def test_is_address_intent_slug(slug: str, expected: bool) -> None:
    assert crawl.is_address_intent_slug(slug) is expected


def test_select_urls_classifies_address_variants() -> None:
    base = "https://acme.example"
    homepage = base + "/"
    links = [
        base + "/contact-2/",
        base + "/support/contact",
        base + "/privacy-policy",
        base + "/legal-information",
        base + "/nl/contact",
        base + "/some-product",  # unclassified, must not appear
    ]
    selected, _ = select_urls(homepage, links)
    urls = {u for u, _ in selected}
    assert base + "/contact-2/" in urls
    assert base + "/support/contact" in urls
    assert base + "/privacy-policy" in urls
    assert base + "/legal-information" in urls
    assert base + "/nl/contact" in urls
    assert base + "/some-product" not in urls


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://brunel.net/nl-nl", "https://brunel.net/nl-nl"),
        ("https://acme.example/en", "https://acme.example/en"),
        ("https://acme.example/en_us", "https://acme.example/en_us"),
        ("https://acme.example/nl-nl/", "https://acme.example/nl-nl"),
        ("https://acme.example/products", "https://acme.example/"),
        ("https://acme.example/nl-nl/contact", "https://acme.example/"),
        ("https://acme.example/", "https://acme.example/"),
        ("https://acme.example/nl?lang=en#x", "https://acme.example/nl"),
    ],
)
def test_normalize_homepage_locale_roots(url: str, expected: str) -> None:
    assert crawl.normalize_homepage(url) == expected


# ---------------------------------------------------------------------------
# core.process — end-to-end with mocked fetch
# ---------------------------------------------------------------------------

PROSE = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5


def _page(title: str, body: str = PROSE, extra_links: str = "") -> str:
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<header><nav>{extra_links}</nav></header>"
        f"<main><h1>{title}</h1><p>{body}</p></main>"
        f"<footer>Acme B.V., Europalaan 100, 3526 KS Utrecht</footer>"
        f"</body></html>"
    )


HOMEPAGE_LINKS = (
    '<a href="/about">About</a>'
    '<a href="/team">Team</a>'
    '<a href="/contact">Contact</a>'
    '<a href="/x.pdf">Flyer</a>'
)


def _make_fetcher(pages: dict[str, str], *, errors: dict[str, str] | None = None):
    errors = errors or {}

    def _fake_get(url: str, *, timeout: float = 15.0) -> FetchResult:
        if url in errors:
            return FetchResult(url=url, html=None, error=errors[url], error_kind="http_404")
        html = pages.get(url)
        if html is None:
            return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")
        return FetchResult(url=url, html=html, error=None, error_kind=None)

    return _fake_get


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_module.time, "sleep", lambda _s: None)


def test_process_ok_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))

    record = {"name": "Acme B.V.", "website": base + "/", "source": "test"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)

    assert meta["status"] == "ok"
    assert meta["pages_collected"] == 4
    assert meta["source"] == "test"
    assert meta["footer_text"] and "Europalaan" in meta["footer_text"]
    assert meta["favicon_url"] == base + "/favicon.ico"
    statuses = {a["status"] for a in meta["urls_attempted"]}
    assert "written" in statuses
    # Files on disk:
    company_dir = tmp_path / "acme"
    assert (company_dir / "_meta.json").exists()
    assert (company_dir / "index.md").exists()
    assert (company_dir / "about.md").exists()


def test_process_upstream_failed_no_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = []

    def _no_fetch(*args, **kwargs):
        called.append(args)
        raise AssertionError("fetch should not be called for upstream_failed")

    monkeypatch.setattr(core_module.fetch, "get", _no_fetch)
    record = {"name": "Foo B.V.", "website": None, "status": "failed", "error": "no search results"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)

    assert meta["status"] == "upstream_failed"
    assert meta["pages_collected"] == 0
    assert meta["urls_attempted"] == []
    assert meta["pages"] == {}
    assert meta["structured_text"] is None
    assert (tmp_path / "foo" / "_meta.json").exists()
    assert called == []


def test_process_fetch_failed_homepage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    def _always_fail(url: str, *, timeout: float = 15.0) -> FetchResult:
        return FetchResult(url=url, html=None, error="timeout after 15s", error_kind="timeout")

    monkeypatch.setattr(core_module.fetch, "get", _always_fail)
    record = {"name": "Acme B.V.", "website": "https://acme.example/"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)
    assert meta["status"] == "fetch_failed"
    assert meta["pages_collected"] == 0
    assert meta["urls_attempted"][0]["status"] == "error"
    assert "timeout" in meta["urls_attempted"][0]["error"]


def test_headless_triggered_on_429(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    rendered_html = _page("Home", extra_links='<a href="/contact">Contact</a>')

    def _fetch(url: str, *, timeout: float = 15.0) -> FetchResult:
        if url == f"{base}/":
            return FetchResult(url=url, html=None, error="HTTP 429", error_kind="http_429")
        return FetchResult(url=url, html=_page("Contact"), error=None, error_kind=None)

    monkeypatch.setattr(core_module.fetch, "get", _fetch)
    render_calls: list[str] = []

    def _render(url: str) -> FetchResult:
        render_calls.append(url)
        return FetchResult(url=url, html=rendered_html, error=None, error_kind=None)

    monkeypatch.setattr(core_module.render, "render_homepage", _render)

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=False)

    assert render_calls == [f"{base}/"]
    assert meta["status"] == "thin"
    assert any(a["slug"] == "index" and a["status"] == "written" for a in meta["urls_attempted"])


def test_headless_triggered_on_linkless_homepage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    static_html = _page("Static", extra_links="")
    rendered_html = _page("Rendered", extra_links='<a href="/contact">Contact</a>')
    pages = {f"{base}/": static_html, f"{base}/contact": _page("Contact")}
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    render_calls: list[str] = []

    def _render(url: str) -> FetchResult:
        render_calls.append(url)
        return FetchResult(url=url, html=rendered_html, error=None, error_kind=None)

    monkeypatch.setattr(core_module.render, "render_homepage", _render)

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=False)

    assert render_calls == [f"{base}/"]
    assert "Rendered" in (meta["pages"]["index"]["title"] or "")


def test_headless_skipped_when_static_homepage_usable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links='<a href="/contact">Contact</a>'),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    render_calls: list[str] = []
    monkeypatch.setattr(
        core_module.render,
        "render_homepage",
        lambda url: render_calls.append(url)
        or FetchResult(url=url, html=_page("Rendered"), error=None, error_kind=None),
    )

    core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=False)

    assert render_calls == []


def test_headless_failure_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    monkeypatch.setattr(
        core_module.fetch,
        "get",
        lambda url: FetchResult(url=url, html=None, error="HTTP 429", error_kind="http_429"),
    )
    monkeypatch.setattr(
        core_module.render,
        "render_homepage",
        lambda url: FetchResult(url=url, html=None, error="headless timeout", error_kind="timeout"),
    )

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=False)

    assert meta["status"] == "fetch_failed"
    assert meta["urls_attempted"][0]["status"] == "error"
    assert "headless timeout" in meta["urls_attempted"][0]["error"]


def test_js_site_subpages_fetched_headlessly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    static_html = _page("Static", extra_links="")  # link-less → triggers headless homepage render
    rendered_home = _page("Rendered", extra_links='<a href="/contact">Contact</a>')
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher({f"{base}/": static_html}))
    monkeypatch.setattr(
        core_module.render,
        "render_homepage",
        lambda url: FetchResult(url=url, html=rendered_home, error=None, error_kind=None),
    )

    render_calls: list[str] = []
    fetch_calls: list[str] = []

    class _FakeRenderer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def render(self, url: str, **kwargs) -> FetchResult:
            render_calls.append(url)
            return FetchResult(url=url, html=_page("Contact"), error=None, error_kind=None)

        def close(self) -> None:
            pass

    monkeypatch.setattr(core_module.render, "PageRenderer", _FakeRenderer)

    real_fetcher = _make_fetcher({f"{base}/": static_html})

    def _tracking_fetch(url: str, *, timeout: float = 15.0) -> FetchResult:
        fetch_calls.append(url)
        return real_fetcher(url)

    monkeypatch.setattr(core_module.fetch, "get", _tracking_fetch)

    core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=False)

    # The sub-page was fetched via the headless renderer, NOT plain HTTP.
    assert f"{base}/contact" in render_calls
    assert f"{base}/contact" not in fetch_calls


def test_process_thin_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS)}
    # /about, /team, /contact all 404
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)
    assert meta["status"] == "thin"
    assert meta["pages_collected"] == 1
    error_entries = [a for a in meta["urls_attempted"] if a["status"] == "error"]
    assert len(error_entries) >= 3


def test_process_substantial_single_page_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    # One page only (sub-pages 404), but its markdown is substantial (≥ MIN_SUBSTANTIAL_CONTENT_CHARS).
    long_body = PROSE * 10  # ~2900 chars — well above the 2000 threshold
    pages = {f"{base}/": _page("Home", body=long_body, extra_links=HOMEPAGE_LINKS)}
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)
    assert meta["pages_collected"] == 1
    assert meta["status"] == "ok"  # complete-but-small site is not a failure


def test_process_dropped_thin_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": "<html><body><main>short</main></body></html>",  # sub-threshold
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    dropped = [a for a in meta["urls_attempted"] if a["status"] == "dropped_thin"]
    assert any(a["slug"] == "team" for a in dropped)


def test_process_write_false_no_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    payload_dry = core_module.process(record, out_dir=tmp_path, write=False)
    assert not any(tmp_path.iterdir())  # nothing written

    # Reset trafilatura dedup so the wet-run sees the same content as fresh.
    from trafilatura import deduplication

    deduplication.LRU_TEST.clear()
    out_dir2 = tmp_path / "out"
    payload_wet = core_module.process(record, out_dir=out_dir2, write=True)
    assert payload_dry == payload_wet


def test_meta_records_structured_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    homepage = _page("Home", extra_links=HOMEPAGE_LINKS).replace(
        "</body>",
        '<script type="application/ld+json">{"@type":"Organization","address":{"@type":"PostalAddress","streetAddress":"Stadsplateau 34","postalCode":"3521 AZ","addressLocality":"Utrecht"}}</script></body>',
    )
    pages = {
        f"{base}/": homepage,
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    assert meta["structured_text"] is not None
    assert "Stadsplateau 34" in meta["structured_text"]
    saved = json.loads((tmp_path / "acme" / "_meta.json").read_text(encoding="utf-8"))
    assert saved["structured_text"] == meta["structured_text"]


def test_process_writes_recall_md_for_address_slugs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    # Make the recall extraction return a deterministic, non-empty body so
    # we can assert the file gets written for address-bearing slugs.
    monkeypatch.setattr(
        core_module.extract,
        "extract_markdown_recall",
        lambda html: "RECALL BODY with Europalaan 100, 3526 KS Utrecht",
    )

    record = {"name": "Acme B.V.", "website": base + "/"}
    core_module.process(record, out_dir=tmp_path, write=True)

    company_dir = tmp_path / "acme"
    # Address-bearing slugs get a .recall.md companion.
    assert (company_dir / "about.recall.md").exists()
    assert (company_dir / "contact.recall.md").exists()
    # Non-address slugs do NOT.
    assert not (company_dir / "team.recall.md").exists()
    assert not (company_dir / "index.recall.md").exists()


def test_sparse_contact_page_yields_recall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links='<a href="/contact">Contact</a>'),
        f"{base}/contact": (
            "<html><body><main>Contact</main>"
            "<address>Europalaan 100, 3526 KS Utrecht</address></body></html>"
        ),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    monkeypatch.setattr(core_module.extract, "extract_markdown", lambda html: "short")
    monkeypatch.setattr(
        core_module.extract,
        "extract_markdown_recall",
        lambda html: "Europalaan 100, 3526 KS Utrecht",
    )

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    assert any(a["slug"] == "contact" and a["status"] == "dropped_thin" for a in meta["urls_attempted"])
    company_dir = tmp_path / "acme"
    assert not (company_dir / "contact.md").exists()
    assert (company_dir / "contact.recall.md").read_text(encoding="utf-8") == (
        "Europalaan 100, 3526 KS Utrecht"
    )


def test_recall_emitted_for_colofon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links='<a href="/colofon">Colofon</a>'),
        f"{base}/colofon": _page("Colofon"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    monkeypatch.setattr(core_module.extract, "extract_markdown_recall", lambda html: "Recall colofon")

    core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    assert (tmp_path / "acme" / "colofon.recall.md").exists()


def test_non_address_subthreshold_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links='<a href="/platform">Platform</a>'),
        f"{base}/platform": "<html><body><main>tiny</main></body></html>",
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))

    meta = core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    assert any(a["slug"] == "platform" and a["status"] == "dropped_thin" for a in meta["urls_attempted"])
    assert not (tmp_path / "acme" / "platform.md").exists()


def test_recall_skipped_for_non_address_slug(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links='<a href="/platform">Platform</a>'),
        f"{base}/platform": _page("Platform"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    monkeypatch.setattr(core_module.extract, "extract_markdown_recall", lambda html: "Recall platform")

    core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    assert (tmp_path / "acme" / "platform.md").exists()
    assert not (tmp_path / "acme" / "platform.recall.md").exists()


def test_process_omits_recall_md_when_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    # Recall returns nothing usable → no .recall.md file should appear.
    monkeypatch.setattr(
        core_module.extract,
        "extract_markdown_recall",
        lambda html: None,
    )

    record = {"name": "Acme B.V.", "website": base + "/"}
    core_module.process(record, out_dir=tmp_path, write=True)

    company_dir = tmp_path / "acme"
    assert (company_dir / "about.md").exists()  # precision still written
    assert not (company_dir / "about.recall.md").exists()
    assert not (company_dir / "contact.recall.md").exists()


def test_visible_txt_written_for_address_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))

    core_module.process({"name": "Acme B.V.", "website": base + "/"}, out_dir=tmp_path, write=True)

    company_dir = tmp_path / "acme"
    # Address-intent pages get a raw visible-text companion; others do not.
    assert (company_dir / "contact.visible.txt").exists()
    assert (company_dir / "about.visible.txt").exists()
    assert not (company_dir / "team.visible.txt").exists()
    assert not (company_dir / "index.visible.txt").exists()


def test_canonical_homepage_url_adopted_after_redirect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None
) -> None:
    input_url = "https://old.example/"
    canonical = "https://new.example"
    # The homepage redirects to a different registered domain; its links live
    # on the new host. fetch.get reports the post-redirect URL.
    home_html = _page("Home", extra_links='<a href="https://new.example/contact">Contact</a>')

    def _fetcher(url: str, *, timeout: float = 15.0) -> FetchResult:
        if url == input_url:
            return FetchResult(url=canonical + "/", html=home_html, error=None, error_kind=None)
        if url == canonical + "/contact":
            return FetchResult(url=url, html=_page("Contact"), error=None, error_kind=None)
        return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")

    monkeypatch.setattr(core_module.fetch, "get", _fetcher)

    meta = core_module.process({"name": "Acme B.V.", "website": input_url}, out_dir=tmp_path, write=True)

    assert meta["canonical_homepage_url"] == canonical + "/"
    # The new-domain contact link survived same-domain filtering and was fetched.
    assert any(a["url"] == canonical + "/contact" and a["status"] == "written" for a in meta["urls_attempted"])


def test_process_name_mismatch_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS)}
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    # Seed a pre-existing _meta.json under acme/ with a different name.
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "_meta.json").write_text(
        json.dumps({"name": "Some Other Company"}), encoding="utf-8"
    )
    record = {"name": "Acme B.V.", "website": base + "/"}
    with pytest.raises(RuntimeError, match="collision"):
        core_module.process(record, out_dir=tmp_path, write=True)


def test_process_slug_collision_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    # Two links that slugify to the same slug: /about and /about/.
    homepage_html = (
        '<html><body><header><nav>'
        '<a href="/about">A</a>'
        '<a href="/about/">B</a>'
        '<a href="/team">T</a>'
        '<a href="/contact">C</a>'
        '</nav></header>'
        f'<main><h1>Home</h1><p>{PROSE}</p></main>'
        '<footer>x</footer></body></html>'
    )
    pages = {
        f"{base}/": homepage_html,
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    collisions = [a for a in meta["urls_attempted"] if a.get("error") == "slug-collision"]
    assert len(collisions) == 1


# ---------------------------------------------------------------------------
# Sitemap fallback
# ---------------------------------------------------------------------------

SITEMAP_NS = ' xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def _urlset(urls: list[str], *, namespaced: bool = True) -> str:
    ns = SITEMAP_NS if namespaced else ""
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset{ns}>{locs}</urlset>'


def _sitemapindex(child_urls: list[str], *, namespaced: bool = True) -> str:
    ns = SITEMAP_NS if namespaced else ""
    locs = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in child_urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex{ns}>{locs}</sitemapindex>'


def test_sitemap_surfaces_unlinked_durable_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    homepage = _page("Home", extra_links='<a href="/login">Login</a>')
    pages = {
        f"{base}/": homepage,
        f"{base}/pricing": _page("Pricing"),
        f"{base}/sitemap.xml": _urlset([f"{base}/", f"{base}/pricing"]),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    written = [a["slug"] for a in meta["urls_attempted"] if a["status"] == "written"]
    assert "pricing" in written


def test_sitemap_discovered_via_robots_txt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    fetched: list[str] = []

    def _fetch(url: str, *, timeout: float = 15.0) -> FetchResult:
        fetched.append(url)
        canned = {
            f"{base}/": _page("Home", extra_links='<a href="/about">A</a>'),
            f"{base}/about": _page("About"),
            f"{base}/robots.txt": FetchResult(
                url=url,
                html=f"User-agent: *\nDisallow: /admin\nSitemap: {base}/wp-sitemap.xml\n",
                error=None,
                error_kind=None,
            ),
            f"{base}/wp-sitemap.xml": _urlset([f"{base}/contact"]),
            f"{base}/contact": _page("Contact"),
        }
        v = canned.get(url)
        if isinstance(v, FetchResult):
            return v
        if v is None:
            return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")
        return FetchResult(url=url, html=v, error=None, error_kind=None)

    monkeypatch.setattr(core_module.fetch, "get", _fetch)
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)

    assert f"{base}/wp-sitemap.xml" in fetched
    assert f"{base}/sitemap.xml" not in fetched
    assert meta["sitemap_url"] == f"{base}/wp-sitemap.xml"


def test_sitemap_index_nesting_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    children = [f"{base}/sm-{i}.xml" for i in range(5)]
    fetched_children: list[str] = []

    def _fetch(url: str, *, timeout: float = 15.0) -> FetchResult:
        if url == f"{base}/":
            return FetchResult(url=url, html=_page("Home"), error=None, error_kind=None)
        if url == f"{base}/sitemap.xml":
            return FetchResult(url=url, html=_sitemapindex(children), error=None, error_kind=None)
        if url in children:
            fetched_children.append(url)
            return FetchResult(url=url, html=_urlset([f"{base}/page-{url[-5]}"]), error=None, error_kind=None)
        if url == f"{base}/robots.txt":
            return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")
        return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")

    monkeypatch.setattr(core_module.fetch, "get", _fetch)
    record = {"name": "Acme B.V.", "website": base + "/"}
    core_module.process(record, out_dir=tmp_path, write=False)
    assert fetched_children == children[:3]


def test_malformed_sitemap_silently_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
        f"{base}/sitemap.xml": "<!DOCTYPE html><html><body>oops</body></html>",
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    assert meta["status"] == "ok"
    assert meta["sitemap_url"] is None
    assert meta["sitemap_urls_found"] == 0
    assert meta["sitemap_consulted"] is True


def test_sitemap_metadata_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"
    pages = {
        f"{base}/": _page("Home", extra_links=HOMEPAGE_LINKS),
        f"{base}/about": _page("About"),
        f"{base}/team": _page("Team"),
        f"{base}/contact": _page("Contact"),
        f"{base}/sitemap.xml": _urlset([f"{base}/about", f"{base}/team", f"{base}/contact", f"{base}/pricing"]),
        f"{base}/pricing": _page("Pricing"),
    }
    monkeypatch.setattr(core_module.fetch, "get", _make_fetcher(pages))
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    assert meta["sitemap_consulted"] is True
    assert meta["sitemap_url"] == f"{base}/sitemap.xml"
    assert meta["sitemap_urls_found"] == 4


def test_upstream_failed_has_new_sitemap_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_module.fetch, "get", lambda *a, **k: pytest.fail("no fetch expected"))
    record = {"name": "Foo B.V.", "website": None, "status": "failed"}
    meta = core_module.process(record, out_dir=tmp_path, write=True)
    assert meta["sitemap_consulted"] is False
    assert meta["sitemap_url"] is None
    assert meta["sitemap_urls_found"] == 0


def test_robots_txt_disallow_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_sleep: None) -> None:
    base = "https://acme.example"

    def _fetch(url: str, *, timeout: float = 15.0) -> FetchResult:
        canned = {
            f"{base}/": _page("Home", extra_links='<a href="/pricing">P</a>'),
            f"{base}/pricing": _page("Pricing"),
            f"{base}/robots.txt": FetchResult(
                url=url,
                html=f"User-agent: *\nDisallow: /pricing\nSitemap: {base}/sitemap.xml\n",
                error=None,
                error_kind=None,
            ),
            f"{base}/sitemap.xml": _urlset([f"{base}/"]),
        }
        v = canned.get(url)
        if isinstance(v, FetchResult):
            return v
        if v is None:
            return FetchResult(url=url, html=None, error="HTTP 404", error_kind="http_404")
        return FetchResult(url=url, html=v, error=None, error_kind=None)

    monkeypatch.setattr(core_module.fetch, "get", _fetch)
    record = {"name": "Acme B.V.", "website": base + "/"}
    meta = core_module.process(record, out_dir=tmp_path, write=False)
    written = {a["slug"] for a in meta["urls_attempted"] if a["status"] == "written"}
    assert "pricing" in written


def test_namespaced_sitemap_parsed() -> None:
    from pipeline.content_collection import sitemap as sitemap_mod

    xml = _urlset(["https://acme.example/about", "https://acme.example/contact"], namespaced=True)

    def _fetch(url: str) -> FetchResult:
        return FetchResult(url=url, html=xml, error=None, error_kind=None)

    urls = sitemap_mod.harvest_urls("https://acme.example/sitemap.xml", fetch=_fetch)
    assert urls == ["https://acme.example/about", "https://acme.example/contact"]


def test_sitemap_per_doc_cap() -> None:
    from pipeline.content_collection import sitemap as sitemap_mod

    urls = [f"https://acme.example/p{i}" for i in range(1000)]
    xml = _urlset(urls)

    def _fetch(url: str) -> FetchResult:
        return FetchResult(url=url, html=xml, error=None, error_kind=None)

    harvested = sitemap_mod.harvest_urls("https://acme.example/sitemap.xml", fetch=_fetch, max_urls_per_doc=500)
    assert len(harvested) == 500


# ---------------------------------------------------------------------------
# Network smoke
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_network_medium_set(tmp_path: Path) -> None:
    if not MEDIUM_TEST_SET.exists():
        pytest.skip("companies-medium.json not present")
    records = json.loads(MEDIUM_TEST_SET.read_text(encoding="utf-8"))
    # Only keep records that already have a website (skip the upstream stage).
    records = [r for r in records if isinstance(r.get("website"), str) and r["website"]]
    assert records, "no usable medium-set records"

    statuses: list[str] = []
    for result in core_module.run(records, out_dir=tmp_path, write=True, sleep=0.5):
        statuses.append(result["status"])
        if result["status"] == "ok":
            from pipeline.website_resolution import company_id

            cid = company_id(result["name"])
            assert (tmp_path / cid / "index.md").exists()
            assert (tmp_path / cid / "_meta.json").exists()

    ok_ratio = statuses.count("ok") / len(statuses)
    assert ok_ratio >= 0.70, f"only {ok_ratio:.0%} OK across {len(statuses)} companies"
