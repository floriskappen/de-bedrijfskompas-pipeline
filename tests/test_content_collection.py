"""Tests for the content-collection stage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.content_collection import core as core_module
from pipeline.content_collection import crawl, extract
from pipeline.content_collection.crawl import (
    extract_internal_links,
    select_urls,
    slugify_path,
)
from pipeline.content_collection.extract import extract_footer_text
from pipeline.content_collection.fetch import FetchResult

REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"


@pytest.fixture(autouse=True)
def _reset_trafilatura_dedup() -> None:
    """trafilatura keeps a module-level LRU of seen blocks; reset per test."""

    from trafilatura import deduplication

    deduplication.LRU_TEST.clear()


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
    # 10 tier-1 candidates, all distinct slugs.
    links = [base + p for p in ("/about", "/over-ons", "/mission", "/vision", "/services", "/diensten", "/products", "/oplossingen", "/platform", "/impact")]
    selected, _ = select_urls(homepage, links)
    assert len(selected) == 8


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
