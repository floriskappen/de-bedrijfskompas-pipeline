# content-collection Specification

## Purpose

Pipeline stage 2: fetch a curated subset of each company's website, extract clean markdown via trafilatura, and persist per-page markdown plus a `_meta.json` sidecar. The job is collection, not interpretation — downstream stages (`fact-extraction`, `content-summarization`) consume this output.

## Requirements

### Requirement: Input Record Shape

The stage SHALL read each record from `data/website-resolution/<company-id>.json`. A record is a JSON object with at least `name` (string, required) and `website` (string, optional). All other keys SHALL be preserved into the per-company `_meta.json`.

If `website` is `null`, missing, or empty, the stage SHALL NOT attempt any HTTP fetch and SHALL write only `_meta.json` with `status: "upstream_failed"`, preserving the upstream error context when available.

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

For each company with a usable website, the stage SHALL select between 1 and 12 URLs (homepage included):

1. The resolved homepage is always selected.
2. Internal links from the homepage are extracted: only same-registered-domain, `http`/`https` schemes. Fragment-only, `mailto:`, `tel:`, query-only links, and links to file downloads (`.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`, etc.) are excluded.
3. The sitemap is consulted as a supplementary URL source. Discovery order: fetch `/robots.txt`; if it advertises a `Sitemap:` URL (case-insensitive), use that; otherwise fall back to `<homepage>/sitemap.xml`. URLs from `<loc>` elements are filtered by the same same-registered-domain rule and merged into the candidate pool. A `<sitemapindex>` SHALL be followed for at most 3 nested sitemaps.
4. URLs whose path matches a configured list of **durable** path patterns (English and Dutch slugs, priority-ordered: identity/mission/services first; cases/team/contact/pricing/etc. second) are selected first.
5. Within each tier, candidates SHALL be ordered first by path depth (depth-1 paths like `/contact` before depth-2 paths like `/platform/discover-qualify`), then by the matched pattern's tier-position.
6. No more than 2 URLs sharing the same tier-path prefix SHALL be selected.
7. **Fresh-content** patterns (`/blog`, `/news`, `/nieuws`, etc.) are selected only as fallback to reach a minimum of 3 pages, and never replace a durable match.
8. Total selection MUST NOT exceed 12 URLs.

Sitemap discovery is best-effort: a missing, malformed, or non-XML response SHALL NOT abort processing — the company simply proceeds with homepage-link candidates only. The configured path patterns live in code, not the spec; changes to them are not breaking.

#### Scenario: Durable paths win over fresh paths

- **WHEN** homepage links include `/about`, `/team`, `/pricing`, and `/blog`
- **THEN** `/about`, `/team`, and `/pricing` are selected; `/blog` is included only if removing it would leave fewer than 3 pages

#### Scenario: Page cap enforced

- **WHEN** more than 12 candidate URLs match durable patterns
- **THEN** at most 12 URLs are fetched (homepage included)

#### Scenario: Top-level paths beat sub-pages

- **WHEN** homepage links include `/platform`, `/platform/discover-qualify`, `/platform/clarifications`, `/contact`, all matching durable patterns
- **THEN** `/platform` and `/contact` (depth 1) are selected before any `/platform/*` sub-page (depth 2)

#### Scenario: Per-prefix cap prevents sub-tree monopoly

- **WHEN** the homepage links to `/platform`, `/platform/a`, `/platform/b`, `/platform/c`, `/platform/d`, and `/contact`
- **THEN** at most 2 of the `/platform`-prefixed URLs are selected, leaving room for `/contact`

#### Scenario: External and non-HTTP links excluded

- **WHEN** homepage links include `/about`, `https://twitter.com/acme`, `mailto:hi@acme.example`, `/flyer.pdf`, and `#mission`
- **THEN** only `/about` is considered for selection

#### Scenario: Dutch-language paths recognised

- **WHEN** a Dutch site has links to `/over-ons`, `/diensten`, and `/werken-bij`
- **THEN** all three are selected as durable matches

#### Scenario: Sitemap surfaces unlinked durable pages

- **WHEN** the homepage links only to `/login` and `/privacy-policy`, but `/sitemap.xml` lists `/pricing` (a durable path)
- **THEN** `/pricing` is added to the candidate pool and selected

#### Scenario: Sitemap discovered via robots.txt

- **WHEN** `/robots.txt` contains `Sitemap: https://acme.example/wp-sitemap.xml`
- **THEN** the robots-advertised sitemap is used; `/sitemap.xml` is NOT consulted

#### Scenario: Sitemap-index nesting

- **WHEN** `/sitemap.xml` returns a `<sitemapindex>` listing 5 sub-sitemaps
- **THEN** at most the first 3 sub-sitemaps are fetched

#### Scenario: Malformed sitemap silently ignored

- **WHEN** `/sitemap.xml` returns HTML (e.g. an SPA shell) instead of XML
- **THEN** no exception is raised; the company proceeds with homepage-link candidates only

### Requirement: Content Extraction

For each selected URL the stage SHALL fetch via plain HTTP (no JavaScript rendering) and convert the response body to markdown using `trafilatura` with: comments excluded, images excluded, links excluded, tables included, formatting (headings) preserved, deduplication enabled, **`favor_precision=True`**. This precision-mode output is written to `<slug>.md`. Pages whose precision-mode markdown is shorter than 100 characters SHALL be dropped silently.

For pages whose slug is in the address-bearing set `{"contact", "over-ons", "about", "about-us"}`, the stage SHALL additionally run a recall-mode extraction (`favor_recall=True`, same other settings) and write the result to `<slug>.recall.md`. The recall extraction has no minimum-length threshold. If recall returns nothing usable, the stage SHALL omit the `.recall.md` file silently.

#### Scenario: Successful extraction

- **WHEN** a fetched page has substantive prose
- **THEN** precision-mode markdown longer than 100 chars is written to `<slug>.md`

#### Scenario: Sub-threshold page dropped

- **WHEN** a fetched page yields fewer than 100 characters of precision-mode markdown
- **THEN** no markdown file is written; the URL is recorded in `_meta.json.urls_attempted` with `status: "dropped_thin"`

#### Scenario: Recall-mode markdown emitted for address-bearing slug

- **WHEN** a page resolves to slug `contact` and recall-mode extraction yields a non-empty body
- **THEN** both `contact.md` and `contact.recall.md` exist in the company directory

#### Scenario: Recall-mode omitted when empty

- **WHEN** a page resolves to slug `about-us` and recall-mode extraction returns nothing usable
- **THEN** only `about-us.md` is written; `about-us.recall.md` is absent

#### Scenario: Recall-mode skipped for non-address slugs

- **WHEN** a page resolves to slug `platform`
- **THEN** only `platform.md` is written; no `platform.recall.md` is produced

#### Scenario: Plain HTTP only

- **WHEN** a site relies on client-side JavaScript to render its main content
- **THEN** the stage extracts whatever the static HTML yields; no headless browser is used

### Requirement: Footer Capture

The stage SHALL extract the textual content of the homepage's `<footer>` element(s) into `_meta.json.footer_text`. Footer text is metadata, not page content, because trafilatura strips footers from its main-content extraction even though they commonly contain structured facts (HQ address, postcode, KvK numbers).

Extraction SHALL preserve block-level element boundaries as `\n`: each block-level child (`<div>`, `<p>`, `<h1>`–`<h6>`, `<li>`, `<address>`, `<section>`, `<br>`, etc.) emits a newline at its boundary so the resulting text retains visual field separation. Inline-element boundaries emit a space. Horizontal whitespace runs are collapsed to a single space within a line; empty lines are dropped; `\n` is preserved as the field separator.

If the homepage has no `<footer>` element or its content is empty after stripping, `footer_text` SHALL be `null`.

#### Scenario: Footer with address captured

- **WHEN** the homepage HTML contains `<footer>...Europalaan 100, 3526 KS Utrecht...</footer>`
- **THEN** `footer_text` contains `"Europalaan 100, 3526 KS Utrecht"`

#### Scenario: Block boundaries preserved

- **WHEN** the homepage footer is `<footer><p>Smallepad 32</p><p>3811 MG Amersfoort</p><a>LinkedIn</a><a>Instagram</a></footer>`
- **THEN** `footer_text` contains `"Smallepad 32"`, `"3811 MG Amersfoort"`, `"LinkedIn"`, `"Instagram"` separated by newlines or spaces — never fused into `"LinkedInInstagram"`

#### Scenario: Footer absent

- **WHEN** the homepage has no `<footer>` element
- **THEN** `footer_text` is `null`

### Requirement: Output File Layout

For each company processed (successfully or not), the stage SHALL produce `data/content-collection/<company-id>/` containing:

- One `<page-slug>.md` per surviving page. Slug derivation: leading/trailing slashes stripped, internal slashes → hyphens, query and fragment dropped, slugified to lowercase ASCII (`/` → `index`, `/about-us` → `about-us`, `/about/team` → `about-team`, `/over-ons/` → `over-ons`).
- For pages whose slug is in `{"contact", "over-ons", "about", "about-us"}`, a parallel `<page-slug>.recall.md` when recall yielded content.
- Exactly one `_meta.json` sidecar.

`_meta.json` SHALL contain:

- All keys from the input record (`name`, `website`, plus any extras).
- `status`: `"ok"`, `"thin"`, `"fetch_failed"`, or `"upstream_failed"` (see Status Tracking).
- `pages_collected`: integer count of precision-mode `.md` files written.
- `urls_attempted`: array of `{url, slug, status: "written" | "dropped_thin" | "error", error?}`.
- `footer_text`: string or `null`.
- `pages`: object keyed by slug, each `{url, title, description, sitename}` from `trafilatura.extract_metadata()`. Empty for failed companies.
- `sitemap_consulted`: boolean. `false` only when the homepage was not reachable.
- `sitemap_url`: string or `null` — the sitemap actually used.
- `sitemap_urls_found`: integer — count of `<loc>` URLs harvested before tier filtering.
- `favicon_url`: string or `null` — the extracted or fallback favicon URL.

#### Scenario: Successful company with three pages

- **WHEN** processing `Acme B.V.` (id `acme`) collects the homepage, `/about`, and `/contact`
- **THEN** `data/content-collection/acme/` contains `_meta.json`, `index.md`, `about.md`, `contact.md`, and (when recall yielded content) `about.recall.md`, `contact.recall.md`

#### Scenario: Slug derivation

- **WHEN** the selected URLs are `https://acme.example/`, `https://acme.example/about-us`, `https://acme.example/about/team`, `https://acme.example/over-ons/`
- **THEN** the resulting precision files are `index.md`, `about-us.md`, `about-team.md`, `over-ons.md`; recall files are written only for the address-bearing slugs (`about-us`, `over-ons`)

#### Scenario: Upstream-failed company

- **WHEN** the input record has `website: null` and `status: "failed"`
- **THEN** `_meta.json` has `status: "upstream_failed"`, `pages_collected: 0`, empty `urls_attempted` / `pages`, all sitemap fields zero/null/false; no markdown files are written

#### Scenario: Sitemap metadata recorded

- **WHEN** a successful crawl consulted `/sitemap.xml` and harvested 12 URLs (2 reaching `urls_attempted` after tier filtering)
- **THEN** `_meta.json` records `sitemap_consulted: true`, `sitemap_url: "https://acme.example/sitemap.xml"`, `sitemap_urls_found: 12`

### Requirement: Status Tracking

`_meta.json.status` SHALL be exactly one of:

- `"ok"` — ≥3 pages collected.
- `"thin"` — 1 or 2 pages collected (homepage minimum).
- `"fetch_failed"` — the homepage itself could not be fetched.
- `"upstream_failed"` — `website-resolution` did not produce a usable URL; no fetch attempted.

Per-page errors inside an otherwise-successful crawl SHALL be recorded in `urls_attempted` and SHALL NOT change the company-level `status`.

#### Scenario: Healthy crawl

- **WHEN** 5 pages are fetched and pass the content threshold
- **THEN** `status` is `"ok"`

#### Scenario: Thin result

- **WHEN** only the homepage survives (other URLs 404 or fall below threshold)
- **THEN** `status` is `"thin"`; the failed URLs appear in `urls_attempted`

#### Scenario: Homepage unreachable

- **WHEN** the homepage fetch fails
- **THEN** `status` is `"fetch_failed"`, `pages_collected` is `0`, the error is recorded in `urls_attempted`

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-page or per-company failures. Per-page errors are captured in `urls_attempted` and the next page proceeds. Per-company errors (e.g. homepage fetch failure) produce `_meta.json` with `status: "fetch_failed"` and the next company proceeds.

#### Scenario: Per-page error does not abort the crawl

- **WHEN** the second selected URL for `acme` returns a 404
- **THEN** the 404 is recorded in `urls_attempted`; the remaining URLs are still fetched

#### Scenario: One bad company does not block the rest

- **WHEN** the second company's homepage is unreachable
- **THEN** companies one and three are produced normally; company two gets `status: "fetch_failed"`

### Requirement: Polite Crawling

Within a single company, the stage SHALL fetch sequentially and sleep for a configurable interval (default 1 second) between page fetches. The stage MAY fetch `/robots.txt` once per company solely to discover the sitemap URL; it SHALL NOT honour `Disallow` directives.

#### Scenario: Inter-page sleep

- **WHEN** the stage fetches the second of N selected URLs for one company
- **THEN** at least the configured interval has elapsed since the previous fetch

#### Scenario: robots.txt consulted only for sitemap

- **WHEN** `/robots.txt` contains `Disallow: /admin` and `Sitemap: /sitemap.xml`
- **THEN** the `Sitemap:` line is used; the `Disallow:` line is ignored

### Requirement: Out of Scope

The stage SHALL NOT:

- Render JavaScript / use a headless browser.
- Verify that page content actually describes the named company.
- Extract structured facts from the markdown (deferred to `fact-extraction`).
- Honour `robots.txt` `Disallow` directives.
- Persist raw HTML to disk.

#### Scenario: No fact extraction here

- **WHEN** the homepage footer contains `"Europalaan 100, 3526 KS Utrecht"`
- **THEN** the stage writes that text into `footer_text` verbatim; it does NOT parse it into structured `{street, postcode, city}` fields

#### Scenario: robots.txt Disallow ignored

- **WHEN** `/robots.txt` contains `Disallow: /pricing` and the homepage links to `/pricing`
- **THEN** `/pricing` is still fetched per the selection rules

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious environmental and library-quirk hazards. They are not requirements on observable behaviour but are load-bearing for any re-implementation:

- **Namespaced sitemap XML.** Real sitemaps use the `http://www.sitemaps.org/schemas/sitemap/0.9` namespace; match `<loc>` by local name to avoid namespace-prefix fragility.
- **WordPress sitemap path.** WordPress 5.5+ serves the sitemap at `/wp-sitemap.xml`, not `/sitemap.xml`. The `robots.txt` lookup catches this; don't hard-code `/sitemap.xml` as the only entry point.
- **`<style>` / `<script>` inside `<footer>`.** Some CMSes (Squarespace) embed these inside `<footer>`. Strip them before extracting footer text. lxml's default `Element.remove()` discards the `tail`, which is where actual footer text often lives — preserve `tail` text.
- **trafilatura's module-level dedup LRU.** With `deduplicate=True`, trafilatura keeps a process-wide LRU of seen blocks. Tests exercising multiple pages with similar prose MUST clear `trafilatura.deduplication.LRU_TEST` between runs, or content gets silently dropped.
- **`tldextract` with reserved TLDs.** Test fixtures using hosts like `acme.example` produce empty suffix. Fall back to netloc comparison (stripping leading `www.`) when `tldextract` returns no suffix; don't treat empty-suffix as "no match".

#### Scenario: Namespaced sitemap parsed

- **WHEN** `/sitemap.xml` returns `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">...<url><loc>https://acme.example/about</loc></url>...</urlset>`
- **THEN** `https://acme.example/about` is harvested into the candidate pool

### Requirement: Favicon URL Extraction

The stage SHALL extract a favicon URL from the homepage HTML. It SHALL parse `<link>` tags with `rel` values in `("icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed")`. It SHALL choose the icon closest to the target size of 512x512 (preferring size $\ge 512$ sorted ascending, then size $< 512$ sorted descending), preferring modern `rel` types as a tie-breaker. If no `<link>` tag is found, it SHALL fall back to `<homepage_url>/favicon.ico`. If the homepage fetch fails, `favicon_url` SHALL be `null`.

#### Scenario: Best candidate favicon URL selected

- **WHEN** the homepage HTML contains candidate icons of sizes `16x16`, `192x192`, `1024x1024`, and `512x512`
- **THEN** the absolute URL of the `512x512` icon is chosen

#### Scenario: Fallback icon used

- **WHEN** the homepage HTML contains no favicon links, or the homepage fetch fails
- **THEN** `favicon_url` is `<homepage_url>/favicon.ico` or `null` respectively

