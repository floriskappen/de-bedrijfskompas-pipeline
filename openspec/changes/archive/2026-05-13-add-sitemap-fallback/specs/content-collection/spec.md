## MODIFIED Requirements

### Requirement: Page Selection

For each company with a usable website, the stage SHALL select between 1 and 8 URLs to fetch, including the resolved homepage. The selection algorithm:

1. The resolved homepage is always selected.
2. Internal links from the homepage are extracted: only same-registered-domain links, only `http`/`https` schemes. Fragment-only, `mailto:`, `tel:`, query-only links, and links to file downloads (e.g. `.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`) are excluded.
3. The stage SHALL additionally consult the site's sitemap as a **supplementary** URL source. Discovery order: fetch `/robots.txt`; if it advertises a `Sitemap:` URL (case-insensitive), use that. Otherwise fall back to `<homepage>/sitemap.xml`. URLs harvested from `<loc>` elements are filtered by the same same-registered-domain rule and merged into the candidate pool. A sitemap response that is a `<sitemapindex>` SHALL be followed for at most 3 nested sitemaps in declared order.
4. URLs whose path matches a configured list of **durable** path patterns are selected first. The patterns SHALL cover both English and Dutch slugs and SHALL be ordered by priority (identity/mission/services first; cases/team/contact/pricing/etc. second).
5. URLs whose path matches **fresh-content** patterns (e.g. `/blog`, `/news`, `/nieuws`) are selected only as fallback to bring the page count to at least 3, and never replace a durable match.
6. Total selection MUST NOT exceed 8 URLs (homepage included).

Sitemap discovery is best-effort: a missing, malformed, or non-XML sitemap response SHALL NOT abort processing — the company simply proceeds with homepage-link candidates only. The configured path patterns are an implementation detail (lives in code, not the spec); changes to them are not breaking changes.

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

#### Scenario: Sitemap surfaces unlinked durable pages

- **WHEN** the homepage links only to `/login` and `/privacy-policy`, but `/sitemap.xml` lists `/pricing` (a tier-2 durable path)
- **THEN** `/pricing` is added to the candidate pool and selected

#### Scenario: Sitemap discovered via robots.txt

- **WHEN** `/robots.txt` contains `Sitemap: https://acme.example/wp-sitemap.xml` and that file contains the site's URLs
- **THEN** `/sitemap.xml` is NOT consulted; the robots-advertised sitemap is used

#### Scenario: Sitemap-index nesting

- **WHEN** `/sitemap.xml` returns a `<sitemapindex>` listing 5 sub-sitemaps
- **THEN** at most the first 3 sub-sitemaps are fetched

#### Scenario: Malformed sitemap silently ignored

- **WHEN** `/sitemap.xml` returns HTML (e.g. an SPA shell) instead of XML
- **THEN** no exception is raised; the company proceeds with homepage-link candidates only

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
- `sitemap_consulted`: boolean. `true` when the stage attempted sitemap discovery; `false` when the homepage was not reachable (in which case sitemap lookup is skipped).
- `sitemap_url`: string or `null`. The sitemap URL actually used, or `null` when discovery failed or produced no usable URLs.
- `sitemap_urls_found`: integer. Count of URLs harvested from the sitemap before tier filtering. Zero when no sitemap was found.

#### Scenario: Successful company with three pages

- **WHEN** processing `Acme B.V.` (id `acme`) collects the homepage, `/about`, and `/contact`
- **THEN** `data/content-collection/acme/` contains `_meta.json`, `index.md`, `about.md`, `contact.md`

#### Scenario: Slug derivation

- **WHEN** the selected URLs are `https://acme.example/`, `https://acme.example/about-us`, `https://acme.example/about/team`, `https://acme.example/over-ons/`
- **THEN** the resulting markdown files are `index.md`, `about-us.md`, `about-team.md`, `over-ons.md`

#### Scenario: Upstream-failed company

- **WHEN** the input record has `website: null` and `status: "failed"`
- **THEN** `data/content-collection/<id>/_meta.json` exists with `status: "upstream_failed"`, `pages_collected: 0`, `urls_attempted: []`, `footer_text: null`, `pages: {}`, `sitemap_consulted: false`, `sitemap_url: null`, `sitemap_urls_found: 0`; no markdown files are written

#### Scenario: Sitemap metadata recorded

- **WHEN** a successful crawl consulted `/sitemap.xml` and harvested 12 URLs (of which 2 ended up in `urls_attempted` after tier filtering)
- **THEN** `_meta.json` records `sitemap_consulted: true`, `sitemap_url: "https://acme.example/sitemap.xml"`, `sitemap_urls_found: 12`

### Requirement: Polite Crawling

Within a single company, the stage SHALL fetch pages sequentially and SHALL sleep for a configurable interval (default 1 second) between consecutive page fetches. The stage MAY fetch `/robots.txt` once per company solely to discover the sitemap URL; it SHALL NOT honour any `Disallow` directives found there.

#### Scenario: Inter-page sleep

- **WHEN** the stage fetches the second of N selected URLs for one company
- **THEN** at least the configured interval (default 1 second) has elapsed since the previous fetch

#### Scenario: robots.txt consulted only for sitemap

- **WHEN** `/robots.txt` contains `Disallow: /admin` and `Sitemap: /sitemap.xml`
- **THEN** the stage uses the `Sitemap:` line for discovery and ignores the `Disallow:` line

### Requirement: Out of Scope

The stage SHALL NOT:

- Render JavaScript or use a headless browser (plain HTTP only).
- Verify that page content actually describes the named company (no ownership/identity validation).
- Extract structured facts such as HQ address from the markdown (deferred to `fact-extraction`).
- Honour `robots.txt` `Disallow` directives. `robots.txt` is fetched only to discover the sitemap URL.
- Persist raw HTML to disk (only the trafilatura-extracted markdown and footer text are stored).

#### Scenario: No JS rendering

- **WHEN** a site requires JavaScript to render its main content
- **THEN** the stage produces whatever the static HTML yields; SPAs commonly land in `"thin"` or `"fetch_failed"` status, which is acceptable

#### Scenario: No fact extraction here

- **WHEN** the homepage footer contains "Europalaan 100, 3526 KS Utrecht"
- **THEN** the stage writes that text into `_meta.json.footer_text` verbatim; it does NOT attempt to parse it into structured `{street, postcode, city}` fields

#### Scenario: robots.txt Disallow ignored

- **WHEN** `/robots.txt` contains `Disallow: /pricing` and the homepage links to `/pricing`
- **THEN** `/pricing` is still fetched per the selection rules; the stage does not consult `Disallow:`

## ADDED Requirements

### Requirement: Operational Pitfalls

The following environmental and library-quirk hazards SHALL be handled by the implementation. They are not requirements on observable behaviour but are load-bearing for any re-implementation.

- **Bogus sitemap responses.** Many SPA sites return their HTML shell on `/sitemap.xml` (same bytes as `/`). Parse the response as XML strictly; if parsing fails or the root element is not `<urlset>` / `<sitemapindex>`, treat as "no sitemap" rather than raising.
- **Namespaced sitemap XML.** Real sitemaps use the `http://www.sitemaps.org/schemas/sitemap/0.9` namespace; match `<loc>` by local name to avoid namespace-prefix fragility.
- **WordPress sitemap path.** WordPress 5.5+ serves the sitemap at `/wp-sitemap.xml`, not `/sitemap.xml`. The `robots.txt` lookup catches this; do not hard-code `/sitemap.xml` as the only entry point.
- **`<style>` and `<script>` inside `<footer>`.** Some CMSes (e.g. Squarespace) embed style or script tags inside the `<footer>` element. Naïve `text_content()` includes their bodies verbatim. Strip these descendants before extracting footer text, and preserve `tail` text (lxml's default `Element.remove()` discards the tail, which is where the actual footer text often lives).
- **trafilatura's module-level dedup LRU.** With `deduplicate=True`, trafilatura keeps a process-wide LRU of seen blocks. Tests that exercise multiple pages with similar prose MUST clear `trafilatura.deduplication.LRU_TEST` between runs, or the second invocation will silently drop content.
- **`tldextract` with reserved TLDs.** Test fixtures using hosts like `acme.example` produce empty suffix from `tldextract`. Fall back to netloc-based comparison (stripping a leading `www.`) when `tldextract` returns no suffix; do not treat empty-suffix as "no match."

#### Scenario: Sitemap response that is HTML

- **WHEN** `/sitemap.xml` returns `<!DOCTYPE html>...` (200 OK) instead of XML
- **THEN** the stage records `sitemap_url: null`, `sitemap_urls_found: 0`, and proceeds with homepage-link candidates only

#### Scenario: Namespaced sitemap parsed

- **WHEN** `/sitemap.xml` returns `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">...<url><loc>https://acme.example/about</loc></url>...</urlset>`
- **THEN** `https://acme.example/about` is harvested into the candidate pool
