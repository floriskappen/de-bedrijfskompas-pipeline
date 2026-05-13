"""Per-company collector and batch runner for content-collection."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.website_resolution import company_id

from . import crawl, extract, fetch

DEFAULT_INTER_PAGE_SLEEP = 1.0


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

    links = crawl.extract_internal_links(homepage_url, homepage_html)
    selected, collisions = crawl.select_urls(homepage_url, links)
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

    if write:
        _write_company(meta, pages=pages_written, out_dir=out_dir)

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
    return out


def _write_company(meta: dict, *, pages: dict[str, str], out_dir: Path) -> None:
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
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
