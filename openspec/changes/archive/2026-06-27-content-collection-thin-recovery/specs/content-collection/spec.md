## ADDED Requirements

### Requirement: Shallow-Link Fallback Selection

When the durable-pattern tiers (identity/mission/services and supporting) and the fresh-content tier together select fewer than the minimum page count (`MIN_PAGES_BEFORE_TIER_3`, currently 3), the stage SHALL fill the remaining slots with the shallowest same-domain internal links not already selected — path-depth-1 links first, then depth-2 — up to the 12-URL cap. This fallback runs after durable and fresh-content selection, so a durable or fresh match is never displaced by a generic link. Links already excluded by the same-registered-domain and binary/document-extension rules SHALL NOT be reconsidered. Selected fallback URLs are subject to the same per-page fetch, content-threshold, and drop rules as any other page.

#### Scenario: Non-standard path recovered by fallback

- **WHEN** the homepage links to `/learn`, `/learn/roadmaps`, and `/knowledge` (none matching a durable or fresh pattern) and only the homepage was selected
- **THEN** `/learn` and `/knowledge` (depth 1) are selected as fallback before any depth-2 link, subject to the 12-URL cap

#### Scenario: Fallback does not displace durable matches

- **WHEN** the homepage links to `/about` (durable) and `/learn` (non-standard) and selection is below the minimum
- **THEN** `/about` is selected first; `/learn` fills a remaining slot only after the durable and fresh tiers are exhausted

#### Scenario: Fallback skipped when minimum already met

- **WHEN** the durable and fresh tiers already select 3 or more pages
- **THEN** no shallow-link fallback selection is performed

## MODIFIED Requirements

### Requirement: Headless Browser Fallback

The stage SHALL render the homepage with a headless browser (Playwright/Chromium) as a fallback, and only as a fallback, when the plain-HTTP homepage fetch either (a) fails with an HTTP `4xx`/`5xx`, a `429`, or a transport/timeout error, or (b) succeeds but yields fewer than a configured minimum of internal `<a>` links (the JS-rendered-SPA signal; default minimum is 1). On a successful render the stage SHALL feed the rendered HTML into the same link-extraction, selection, and extraction path used for plain-HTTP HTML.

When the homepage was rendered headlessly (the site is detected as JS-rendered), the stage SHALL fetch the selected sub-pages headlessly too — plain-HTTP sub-pages on a JS-site return the empty SPA shell and would be dropped as thin. Sub-page renders SHALL reuse the headless browser instance across the company's pages. Static-HTML sites (homepage fetched via plain HTTP) keep the plain-HTTP sub-page path unchanged.

The headless render SHALL enforce a navigation timeout. A headless failure (timeout, navigation error, missing browser binary) SHALL be treated as a normal fetch failure: it is recorded and the company proceeds without aborting the batch. The stage SHALL NOT use the headless browser when plain HTTP already yielded a usable, link-bearing homepage.

#### Scenario: Anti-bot status triggers headless

- **WHEN** the plain-HTTP homepage fetch returns HTTP `429`
- **THEN** the stage re-fetches the homepage with the headless browser and, on success, proceeds with the rendered HTML

#### Scenario: Link-less homepage triggers headless

- **WHEN** the plain-HTTP homepage returns `200` but its HTML contains no internal `<a>` links
- **THEN** the stage re-renders the homepage with the headless browser to recover client-rendered links

#### Scenario: Usable static homepage skips headless

- **WHEN** the plain-HTTP homepage returns `200` with internal `<a>` links present
- **THEN** no headless render is performed

#### Scenario: JS-site sub-pages fetched headlessly

- **WHEN** the homepage was rendered headlessly (SPA signal) and 3 sub-pages are selected
- **THEN** each sub-page is fetched with the headless browser rather than plain HTTP, so client-rendered content is recovered

#### Scenario: Headless failure degrades gracefully

- **WHEN** the headless render times out or the browser binary is unavailable
- **THEN** the failure is recorded, the company is processed as a normal fetch failure, and the batch continues

### Requirement: Status Tracking

`_meta.json.status` SHALL be exactly one of:

- `"ok"` — ≥3 pages collected, OR 1–2 pages collected whose total written-markdown length is ≥ `MIN_SUBSTANTIAL_CONTENT_CHARS` (default 2000; ~20× the per-page drop threshold of 100, i.e. a real page's worth of substance).
- `"thin"` — 1 or 2 pages collected whose total written-markdown length is below `MIN_SUBSTANTIAL_CONTENT_CHARS` (homepage minimum).
- `"fetch_failed"` — the homepage itself could not be fetched.
- `"upstream_failed"` — `website-resolution` did not produce a usable URL; no fetch attempted.

Per-page errors inside an otherwise-successful crawl SHALL be recorded in `urls_attempted` and SHALL NOT change the company-level `status`.

#### Scenario: Healthy crawl

- **WHEN** 5 pages are fetched and pass the content threshold
- **THEN** `status` is `"ok"`

#### Scenario: Substantial single-page brochure site

- **WHEN** only the homepage survives but its written markdown is ≥ `MIN_SUBSTANTIAL_CONTENT_CHARS`
- **THEN** `status` is `"ok"` (a complete-but-small site is not a failure)

#### Scenario: Thin result

- **WHEN** only the homepage survives and its written markdown is below `MIN_SUBSTANTIAL_CONTENT_CHARS`
- **THEN** `status` is `"thin"`; the failed URLs appear in `urls_attempted`

#### Scenario: Homepage unreachable

- **WHEN** the homepage fetch fails
- **THEN** `status` is `"fetch_failed"`, `pages_collected` is `0`, the error is recorded in `urls_attempted`
