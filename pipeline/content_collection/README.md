# `content-collection` — pipeline stage 2

Fetches each company's homepage and a curated set of internal pages, extracts clean markdown via `trafilatura`, and writes one markdown file per page plus a `_meta.json` sidecar.

## Run

```bash
# Default: read data/website-resolution/, write to data/content-collection/
python -m pipeline.content_collection

# Custom input/output (input can be a directory or a single JSON file)
python -m pipeline.content_collection --input my-records.json --out-dir /tmp/cc

# Dry-run: emit _meta.json payloads as JSON Lines to stdout, write nothing
python -m pipeline.content_collection --dry-run

# Limit to N records (handy when probing a large list)
python -m pipeline.content_collection --limit 3
```

Per-company output layout:

```
data/content-collection/<company-id>/
    _meta.json
    index.md
    about.md
    contact.md
    ...
```

## Status values

- `ok` — at least 3 pages collected.
- `thin` — 1–2 pages collected (homepage minimum). Usable but sparse.
- `fetch_failed` — homepage itself was unreachable.
- `upstream_failed` — `website-resolution` did not produce a usable URL.

Per-page errors (a single 404 inside an otherwise-healthy crawl) land in `urls_attempted` and do not change the company-level `status`.

## Page selection

URLs are gathered from two sources and then selected via tier matching:

1. **Homepage links** — `<a href>` from the homepage HTML, filtered to the same registered domain.
2. **Sitemap** — `/robots.txt` is checked for a `Sitemap:` directive; if none, `/sitemap.xml` is tried as a fallback. WordPress sites that serve `/wp-sitemap.xml` are correctly discovered via robots.txt. A sitemap-index is followed for up to 3 nested children. Bogus sitemap responses (HTML on `/sitemap.xml`, common on SPAs) are silently ignored.

`_meta.json` records `sitemap_consulted`, `sitemap_url`, and `sitemap_urls_found` so you can evaluate how often the fallback fires.

URLs are matched against three tiers of path patterns (English + Dutch) in `crawl.py`:

- **Tier 1**: identity, mission, vision, services, approach, expertise, sectors.
- **Tier 2**: cases, team, clients, partners, locations, careers, pricing, contact.
- **Tier 3**: blog/news/insights — included only when needed to reach 3 pages total.

Matching is path-prefix, case-insensitive, trailing-slash-insensitive. Hard cap: 8 URLs per company including the homepage.

## Dependencies

- [`httpx`](https://pypi.org/project/httpx/) — HTTP client with timeouts and follow-redirects.
- [`trafilatura`](https://pypi.org/project/trafilatura/) — HTML-to-markdown extractor; tuned for precision over recall.
- [`lxml`](https://pypi.org/project/lxml/) — link extraction and footer parsing.
- [`python-slugify`](https://pypi.org/project/python-slugify/) — slug derivation.
- [`tldextract`](https://pypi.org/project/tldextract/) — registered-domain comparison for internal-link filtering.

## Footer capture

`trafilatura` intentionally strips footers as boilerplate, but footers commonly hold structured facts (HQ address, postcode, Chamber of Commerce numbers). The stage extracts the homepage's `<footer>` text separately into `_meta.json.footer_text` so `fact-extraction` (stage 3a) can use it.

## Tests

```bash
# Offline only (default)
pytest tests/ -m "not network"

# Network smoke against the medium test set
pytest tests/test_content_collection.py -m network
```

## Known limitations

- **No JS rendering.** SPAs commonly land in `thin` or `fetch_failed`. A future change can add `playwright` behind a flag.
- **No `robots.txt`.** Requests-per-host stay low (≤ 8 pages with 1 s spacing), so we skip the lookup for now.
- **No on-disk HTTP cache.** Re-runs re-fetch. Add `requests-cache`-style caching when running against larger lists.
- **No sitemap parsing.** Only homepage internal links are considered.
