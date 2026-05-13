## 1. Module Scaffolding

- [x] 1.1 Create `pipeline/content_collection/` package with empty `__init__.py`
- [x] 1.2 Add `httpx`, `trafilatura`, `lxml`, and `python-slugify` to project dependencies
- [x] 1.3 Stub `core.py`, `crawl.py`, `extract.py`, `fetch.py`, `__main__.py` with module docstrings and imports

## 2. Fetching

- [x] 2.1 Implement `fetch.get(url, *, timeout) -> httpx.Response | None` in `fetch.py` with one retry on transient errors and a realistic User-Agent
- [x] 2.2 Raise/return a typed result object so callers can distinguish DNS errors, HTTP errors, and timeouts for `urls_attempted` reporting

## 3. Link Selection (`crawl.py`)

- [x] 3.1 Define `TIER_1_PATHS`, `TIER_2_PATHS`, `TIER_3_PATHS` as module-level tuples per design
- [x] 3.2 Implement `extract_internal_links(homepage_url, html) -> list[str]` filtering by registered domain, scheme, and excluded extensions (`.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`, etc.)
- [x] 3.3 Implement `select_urls(homepage_url, links) -> list[str]` applying tier ordering, the "tier-3 only as fallback to reach 3" rule, and the 8-URL hard cap
- [x] 3.4 Implement `slugify_path(url_path) -> str` per design (handles `/`, trailing slash, internal slashes, query, fragment)
- [x] 3.5 Dedupe selected URLs by derived slug (first occurrence wins)

## 4. Extraction (`extract.py`)

- [x] 4.1 Implement `extract_markdown(html) -> str | None` wrapping `trafilatura.extract` with the configured settings (precision, dedupe, no images/links/comments, include tables)
- [x] 4.2 Implement `extract_page_metadata(html) -> dict` returning `{title, description, sitename}` via `trafilatura.extract_metadata`
- [x] 4.3 Implement `extract_footer_text(html) -> str | None` using `lxml` to concatenate `<footer>` text, normalize whitespace, return `None` if empty
- [x] 4.4 Apply the 100-character minimum threshold (caller-side check; `extract_markdown` returns the raw result)

## 5. Core Orchestration (`core.py`)

- [x] 5.1 Implement `process(record, *, out_dir, write, sleep) -> dict` for a single company: branch on `upstream_failed`, fetch homepage, select URLs, fetch each with inter-page sleep, run extractors, assemble `_meta.json` payload
- [x] 5.2 Implement `run(records, *, out_dir, write, sleep) -> Iterator[dict]` that yields one payload per record and never raises on per-company failures
- [x] 5.3 Compute `status` (`ok`/`thin`/`fetch_failed`/`upstream_failed`) from page counts and homepage fetch result
- [x] 5.4 Preserve all upstream record keys into `_meta.json`; refuse to overwrite an existing `_meta.json` whose stored `name` disagrees with the current record
- [x] 5.5 When `write=True`, write markdown files and `_meta.json` to `data/content-collection/<id>/`; when `write=False`, write nothing but yield identical payloads

## 6. CLI (`__main__.py`)

- [x] 6.1 Parse args: input path (default `data/website-resolution/`), output dir (default `data/content-collection/`), `--dry-run`, `--sleep`, `--limit`
- [x] 6.2 Load upstream records from the directory or a single file
- [x] 6.3 Drive `run(...)` and print a per-company status line plus a final summary (counts per `status`)

## 7. Tests (`tests/test_content_collection.py`)

All offline unless tagged. Aim for one assertion per behavior, not exhaustive coverage.

- [x] 7.1 `select_urls`: tier-rich fixture covering English + Dutch, including (a) case-insensitive match (`/About` matches), (b) trailing-slash match (`/about-us/`), (c) prefix match (`/about-us/our-story` matches `/about-us`), (d) the 8-URL cap, (e) tier-1 ordering before tier-2
- [x] 7.2 `select_urls`: tier-3 fallback — when durable matches yield only 2 URLs, a `/blog` candidate is added; when they yield 3+, `/blog` is excluded
- [x] 7.3 `extract_internal_links`: rejects external domains, `mailto:`, `tel:`, fragment-only, and file-extension URLs (`.pdf`, `.zip`, `.jpg`)
- [x] 7.4 `slugify_path`: parametrized over the spec examples (`/`, `/about-us`, `/about/team`, `/over-ons/`, `/about?lang=en#x`)
- [x] 7.5 `extract_footer_text`: (a) address substring captured, (b) multiple `<footer>` elements concatenated, (c) `None` when no `<footer>` or empty after strip
- [x] 7.6 `process` end-to-end with mocked `fetch.get`: assert `_meta.json` shape, `pages_collected`, `status: "ok"`, extra upstream keys preserved, and `urls_attempted` entries include `written` / `dropped_thin` / `error`
- [x] 7.7 `process`: `status: "upstream_failed"` path — input with `website: null` writes only `_meta.json`, no fetches attempted
- [x] 7.8 `process`: `status: "fetch_failed"` path — homepage fetch returns an error; `pages_collected: 0`, error recorded in `urls_attempted`
- [x] 7.9 `process`: `status: "thin"` path — only homepage survives (other selected URLs 404 or sub-threshold)
- [x] 7.10 `process`: slug-collision case — two URLs slugify to the same name; one is fetched, the other recorded in `urls_attempted`
- [x] 7.11 `process`: `write=False` writes nothing to disk but yields the same payload as `write=True`
- [x] 7.12 `process`: name-mismatch protection — pre-existing `_meta.json` with a different `name` causes a refusal/raise
- [x] 7.13 Network (`@pytest.mark.network`): run against `test-set/companies-medium.json`; assert ≥70% land in `status: "ok"` and every successful company has `index.md` and a `_meta.json`

## 8. Wiring & Docs

- [x] 8.1 Add a brief `pipeline/content_collection/README.md` mirroring `website_resolution/README.md` (inputs, outputs, CLI examples, dry-run)
- [x] 8.2 Run the CLI end-to-end against the small test set; spot-check one `_meta.json` and one markdown file by hand
