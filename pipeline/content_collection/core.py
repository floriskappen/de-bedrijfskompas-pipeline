"""Per-company collector and batch runner for content-collection."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pipeline.website_resolution import company_id

from . import crawl, extract, fetch, sitemap

DEFAULT_INTER_PAGE_SLEEP = 1.0

# Slugs whose pages typically carry the company's physical address inside
# structured side-blocks that trafilatura's precision mode classifies as
# boilerplate. For these we ALSO emit a recall-extracted ``<slug>.recall.md``
# so fact-extraction has a surface where the postcode anchor can land.
ADDRESS_SLUGS: frozenset[str] = frozenset({"contact", "over-ons", "about", "about-us"})


def process(
    record: dict,
    *,
    out_dir: Path,
    write: bool,
    sleep: float = DEFAULT_INTER_PAGE_SLEEP,
) -> dict:
    """Collect content for a single company. Never raises."""

    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        return _meta_skeleton(record, status="upstream_failed")

    website = record.get("website")
    if not isinstance(website, str) or not website.strip():
        meta = _meta_skeleton(record, status="upstream_failed")
        if write:
            _write_company(meta, pages={}, out_dir=out_dir)
        return meta

    homepage_url = crawl.normalize_homepage(website)

    homepage_result = fetch.get(homepage_url)
    urls_attempted: list[dict] = []
    pages_written: dict[str, str] = {}
    pages_meta: dict[str, dict] = {}
    footer_text: str | None = None

    if not homepage_result.ok:
        urls_attempted.append(
            {
                "url": homepage_url,
                "slug": "index",
                "status": "error",
                "error": homepage_result.error,
            }
        )
        meta = _meta_skeleton(record, status="fetch_failed")
        meta["urls_attempted"] = urls_attempted
        if write:
            _write_company(meta, pages={}, out_dir=out_dir)
        return meta

    homepage_html = homepage_result.html or ""
    footer_text = extract.extract_footer_text(homepage_html)
    favicon_url = extract.extract_favicon_url(homepage_url, homepage_html)
    recall_pages: dict[str, str] = {}

    links = crawl.extract_internal_links(homepage_url, homepage_html)

    sitemap_url = sitemap.discover_sitemap_url(homepage_url, fetch=fetch.get)
    sitemap_urls_raw = sitemap.harvest_urls(sitemap_url, fetch=fetch.get)
    base_domain = crawl._registered_domain(homepage_url)
    sitemap_filtered: list[str] = []
    for url in sitemap_urls_raw:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if crawl._registered_domain(url) != base_domain:
            continue
        canon = urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
        if canon == homepage_url:
            continue
        if canon in links or canon in sitemap_filtered:
            continue
        sitemap_filtered.append(canon)

    sitemap_consulted = True
    sitemap_used_url = sitemap_url if sitemap_urls_raw else None
    sitemap_urls_found = len(sitemap_urls_raw)

    candidate_links = links + sitemap_filtered
    selected, collisions = crawl.select_urls(homepage_url, candidate_links)
    for url, slug in collisions:
        urls_attempted.append(
            {
                "url": url,
                "slug": slug,
                "status": "error",
                "error": "slug-collision",
            }
        )

    for idx, (url, slug) in enumerate(selected):
        if idx == 0:
            html = homepage_html  # already fetched
        else:
            if sleep > 0:
                time.sleep(sleep)
            result = fetch.get(url)
            if not result.ok:
                urls_attempted.append(
                    {
                        "url": url,
                        "slug": slug,
                        "status": "error",
                        "error": result.error,
                    }
                )
                continue
            html = result.html or ""

        markdown = extract.extract_markdown(html)
        if not markdown or len(markdown) < extract.MIN_MARKDOWN_LENGTH:
            urls_attempted.append(
                {"url": url, "slug": slug, "status": "dropped_thin"}
            )
            continue

        pages_written[slug] = markdown
        # For address-bearing slugs, also store a recall-mode extraction so
        # fact-extraction sees structured address blocks that precision mode
        # strips as boilerplate. Skipped silently if recall yields nothing.
        if slug in ADDRESS_SLUGS:
            recall_md = extract.extract_markdown_recall(html)
            if recall_md and recall_md.strip():
                recall_pages[slug] = recall_md
        page_meta = extract.extract_page_metadata(html)
        page_meta["url"] = url
        pages_meta[slug] = page_meta
        urls_attempted.append({"url": url, "slug": slug, "status": "written"})

    pages_collected = len(pages_written)
    if pages_collected >= 3:
        status = "ok"
    elif pages_collected >= 1:
        status = "thin"
    else:
        status = "fetch_failed"

    meta = dict(record)
    meta["status"] = status
    meta["pages_collected"] = pages_collected
    meta["urls_attempted"] = urls_attempted
    meta["footer_text"] = footer_text
    meta["pages"] = pages_meta
    meta["sitemap_consulted"] = sitemap_consulted
    meta["sitemap_url"] = sitemap_used_url
    meta["sitemap_urls_found"] = sitemap_urls_found
    meta["favicon_url"] = favicon_url

    if write:
        _write_company(meta, pages=pages_written, recall_pages=recall_pages, out_dir=out_dir)

    return meta


def run(
    records: Iterable[dict],
    *,
    out_dir: Path,
    write: bool,
    sleep: float = DEFAULT_INTER_PAGE_SLEEP,
) -> Iterator[dict]:
    """Yield one ``_meta.json`` payload per record. Never raises on per-company errors."""

    for record in records:
        try:
            yield process(record, out_dir=out_dir, write=write, sleep=sleep)
        except Exception as exc:  # defense-in-depth; process should not raise
            failed = _meta_skeleton(record, status="fetch_failed")
            failed["urls_attempted"] = [
                {
                    "url": record.get("website"),
                    "slug": "index",
                    "status": "error",
                    "error": f"unexpected: {exc}",
                }
            ]
            yield failed


def _meta_skeleton(record: dict, *, status: str) -> dict:
    out = dict(record)
    out["status"] = status
    out["pages_collected"] = 0
    out["urls_attempted"] = []
    out["footer_text"] = None
    out["pages"] = {}
    out["sitemap_consulted"] = False
    out["sitemap_url"] = None
    out["sitemap_urls_found"] = 0
    out["favicon_url"] = None
    return out


def _write_company(
    meta: dict,
    *,
    pages: dict[str, str],
    recall_pages: dict[str, str] | None = None,
    out_dir: Path,
) -> None:
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        return

    company_dir = out_dir / company_id(name)
    meta_path = company_dir / "_meta.json"

    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_name = existing.get("name")
        except (OSError, json.JSONDecodeError):
            existing_name = None
        if isinstance(existing_name, str) and existing_name != name:
            raise RuntimeError(
                f"company-id collision at {meta_path}: "
                f"existing record has name={existing_name!r}, "
                f"new record has name={name!r}"
            )

    company_dir.mkdir(parents=True, exist_ok=True)
    for slug, markdown in pages.items():
        (company_dir / f"{slug}.md").write_text(markdown, encoding="utf-8")
    for slug, recall_md in (recall_pages or {}).items():
        (company_dir / f"{slug}.recall.md").write_text(recall_md, encoding="utf-8")
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
