## ADDED Requirements

### Requirement: Input Record Shape

The stage SHALL read its input from `data/website-resolution/<company-id>.json` per the canonical output of the upstream stage. Each record is a JSON object with at least `name` (string, required) and `website` (string, optional). All other keys SHALL be preserved unchanged into the stage's per-company `_meta.json`.

If `website` is `null`, missing, or empty — typically because `website-resolution` recorded a failure for that company — the stage SHALL NOT attempt any HTTP fetch and SHALL write only `_meta.json` with `status: "upstream_failed"`, preserving the upstream error context when available.

#### Scenario: Valid input with website

- **WHEN** input is `{"name": "Acme B.V.", "website": "https://acme.example"}`
- **THEN** the stage proceeds with page selection and fetching

#### Scenario: Upstream failure propagation

- **WHEN** input is `{"name": "Foo B.V.", "website": null, "status": "failed", "error": "no search results"}`
- **THEN** no HTTP fetch is attempted; only `_meta.json` is written, with `status: "upstream_failed"` and the original upstream error retained

#### Scenario: Extra input keys preserved

- **WHEN** input is `{"name": "Acme B.V.", "website": "https://acme.example", "source": "incubator-list-2026-01"}`
- **THEN** the resulting `_meta.json` retains `source` with the same value

### Requirement: Page Selection

For each company with a usable website, the stage SHALL select between 1 and 8 URLs to fetch, including the resolved homepage. The selection algorithm:

1. The resolved homepage is always selected.
2. Internal links from the homepage are extracted: only same-registered-domain links, only `http`/`https` schemes. Fragment-only, `mailto:`, `tel:`, query-only links, and links to file downloads (e.g. `.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`) are excluded.
3. URLs whose path matches a configured list of **durable** path patterns are selected first. The patterns SHALL cover both English and Dutch slugs and SHALL be ordered by priority (identity/mission/services first; cases/team/contact/pricing/etc. second).
4. URLs whose path matches **fresh-content** patterns (e.g. `/blog`, `/news`, `/nieuws`) are selected only as fallback to bring the page count to at least 3, and never replace a durable match.
5. Total selection MUST NOT exceed 8 URLs (homepage included).

The configured path patterns are an implementation detail (lives in code, not the spec); changes to them are not breaking changes.

#### Scenario: Durable paths win over fresh paths

- **WHEN** homepage links include `/about`, `/team`, `/pricing`, and `/blog`
- **THEN** `/about`, `/team`, and `/pricing` are selected; `/blog` is selected only if removing it would leave fewer than 3 pages

#### Scenario: Page cap enforced

- **WHEN** more than 8 candidate URLs match durable patterns
- **THEN** at most 8 URLs are fetched (including the homepage)

#### Scenario: External and non-HTTP links excluded

- **WHEN** homepage links include `/about`, `https://twitter.com/acme`, `mailto:hi@acme.example`, `/flyer.pdf`, and `#mission`
- **THEN** only `/about` is considered for selection

#### Scenario: Dutch-language paths recognised

- **WHEN** a Dutch site has links to `/over-ons`, `/diensten`, and `/werken-bij`
- **THEN** all three are selected as durable matches

### Requirement: Content Extraction

For each selected URL the stage SHALL fetch the page via plain HTTP (no JavaScript rendering) and convert the response body to markdown using `trafilatura` with settings that prefer cleanliness over completeness: comments excluded, images excluded, links excluded, tables included, formatting (headings) preserved, deduplication enabled, precision favored over recall.

A page whose extracted markdown is shorter than a minimum threshold (100 characters) SHALL be dropped silently — it carries no usable content and writing it would only add noise.

#### Scenario: Successful extraction

- **WHEN** a fetched page has substantive prose
- **THEN** trafilatura returns markdown longer than the minimum threshold and the page is written

#### Scenario: Sub-threshold page dropped

- **WHEN** a fetched page yields fewer than 100 characters of extracted markdown
- **THEN** no markdown file is written for that page, and the URL is recorded in `_meta.json.urls_attempted` so the drop is auditable

#### Scenario: Plain HTTP only

- **WHEN** a site relies on client-side JavaScript to render its content
- **THEN** the stage extracts whatever the static HTML provides; it does NOT spin up a headless browser

### Requirement: Footer Capture

The stage SHALL extract the textual content of the homepage's `<footer>` element(s) separately from the trafilatura-extracted markdown and SHALL store it in `_meta.json.footer_text`. Footer text is treated as **metadata**, not page content, because it commonly contains structured facts (HQ address, postcode, Chamber of Commerce numbers) that trafilatura intentionally strips from its main-content extraction.

If the homepage has no `<footer>` element or its contents are empty after whitespace stripping, `_meta.json.footer_text` SHALL be set to `null`.

#### Scenario: Footer with address captured

- **WHEN** the homepage HTML contains `<footer>...Europalaan 100, 3526 KS Utrecht...</footer>`
- **THEN** `_meta.json.footer_text` contains "Europalaan 100, 3526 KS Utrecht" (alongside whatever other footer text is present)

#### Scenario: Footer absent

- **WHEN** the homepage has no `<footer>` element
- **THEN** `_meta.json.footer_text` is `null`

#### Scenario: Footer not duplicated into page markdown

- **WHEN** trafilatura has stripped the footer from the homepage's markdown output (its default behavior)
- **THEN** the stage does not attempt to re-inject footer text into `index.md`; the markdown stays as trafilatura produced it

### Requirement: Output File Layout

For each company processed (successfully or not), the stage SHALL produce a subdirectory at `data/content-collection/<company-id>/` containing:

- One markdown file per surviving page, named `<page-slug>.md`. The page slug is derived from the URL path: leading and trailing slashes are stripped, internal slashes are replaced with hyphens, query strings and fragments are dropped, and the result is slugified to lowercase ASCII (`/` → `index`, `/about-us` → `about-us`, `/about/team` → `about-team`, `/over-ons/` → `over-ons`, `/about?lang=en#x` → `about`).
- Exactly one `_meta.json` sidecar describing the company-level result.

`_meta.json` SHALL contain:

- All keys from the input record (`name`, `website`, plus any extra keys that flowed in).
- `status`: one of `"ok"`, `"thin"`, `"fetch_failed"`, `"upstream_failed"` (see Status Tracking).
- `pages_collected`: integer count of markdown files written.
- `urls_attempted`: array of objects `{url, slug, status: "written" | "dropped_thin" | "error", error?}`.
- `footer_text`: string or `null` (see Footer Capture).
- `pages`: object keyed by page slug, each value `{url, title, description, sitename}` extracted via `trafilatura.extract_metadata()`. Empty object for failed companies.

#### Scenario: Successful company with three pages

- **WHEN** processing `Acme B.V.` (id `acme`) collects the homepage, `/about`, and `/contact`
- **THEN** `data/content-collection/acme/` contains `_meta.json`, `index.md`, `about.md`, `contact.md`

#### Scenario: Slug derivation

- **WHEN** the selected URLs are `https://acme.example/`, `https://acme.example/about-us`, `https://acme.example/about/team`, `https://acme.example/over-ons/`
- **THEN** the resulting markdown files are `index.md`, `about-us.md`, `about-team.md`, `over-ons.md`

#### Scenario: Upstream-failed company

- **WHEN** the input record has `website: null` and `status: "failed"`
- **THEN** `data/content-collection/<id>/_meta.json` exists with `status: "upstream_failed"`, `pages_collected: 0`, `urls_attempted: []`, `footer_text: null`, `pages: {}`; no markdown files are written

### Requirement: Status Tracking

`_meta.json.status` SHALL take exactly one of these values:

- `"ok"` — at least 3 pages were collected.
- `"thin"` — between 1 and 2 pages were collected (homepage at minimum); useful but probably sparse for downstream analysis.
- `"fetch_failed"` — the homepage itself could not be fetched (DNS error, HTTP error, timeout, redirect loop); zero pages produced.
- `"upstream_failed"` — `website-resolution` did not produce a usable URL for this company; no fetch was attempted.

Per-page errors (e.g. a single 404 inside a successful crawl) SHALL be recorded in `urls_attempted` with `status: "error"` and SHALL NOT change the company-level `status`.

#### Scenario: Healthy crawl

- **WHEN** 5 pages are successfully fetched and pass the content threshold
- **THEN** `status` is `"ok"`

#### Scenario: Thin result

- **WHEN** only the homepage survives (other selected URLs all 404 or fall below threshold)
- **THEN** `status` is `"thin"` and the failed URLs are recorded in `urls_attempted` with `status: "error"` or `status: "dropped_thin"`

#### Scenario: Homepage unreachable

- **WHEN** the homepage fetch itself fails
- **THEN** `status` is `"fetch_failed"`, `pages_collected` is `0`, and the error is recorded in `urls_attempted`

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-page or per-company failures. Errors on a single page SHALL be captured in that company's `_meta.json.urls_attempted` and processing SHALL continue with the next page. Errors that prevent processing an entire company (e.g. homepage fetch failure) SHALL result in a `_meta.json` with `status: "fetch_failed"` and processing SHALL continue with the next company.

#### Scenario: Per-page error does not abort the crawl

- **WHEN** the second selected URL for `acme` returns a 404
- **THEN** `acme/_meta.json.urls_attempted` records the 404, the remaining selected URLs are still fetched, and `acme/_meta.json.status` is `"ok"` or `"thin"` based on how many pages succeeded

#### Scenario: One bad company does not block the rest

- **WHEN** processing a batch where the second company's homepage is unreachable
- **THEN** companies one and three are still produced normally; company two gets a `_meta.json` with `status: "fetch_failed"`

### Requirement: Polite Crawling

Within a single company, the stage SHALL fetch pages sequentially and SHALL sleep for a configurable interval (default 1 second) between consecutive page fetches. The stage SHALL NOT consult `robots.txt` in the MVP; this is acceptable because requests-per-host stay low and there is no aggressive recrawling.

#### Scenario: Inter-page sleep

- **WHEN** the stage fetches the second of N selected URLs for one company
- **THEN** at least the configured interval (default 1 second) has elapsed since the previous fetch

### Requirement: Out of Scope

The stage SHALL NOT:

- Render JavaScript or use a headless browser (plain HTTP only).
- Verify that page content actually describes the named company (no ownership/identity validation).
- Extract structured facts such as HQ address from the markdown (deferred to `fact-extraction`).
- Parse `sitemap.xml` or otherwise discover URLs beyond the homepage's internal links.
- Honour `robots.txt`.
- Persist raw HTML to disk (only the trafilatura-extracted markdown and footer text are stored).

#### Scenario: No JS rendering

- **WHEN** a site requires JavaScript to render its main content
- **THEN** the stage produces whatever the static HTML yields; SPAs commonly land in `"thin"` or `"fetch_failed"` status, which is acceptable

#### Scenario: No fact extraction here

- **WHEN** the homepage footer contains "Europalaan 100, 3526 KS Utrecht"
- **THEN** the stage writes that text into `_meta.json.footer_text` verbatim; it does NOT attempt to parse it into structured `{street, postcode, city}` fields
