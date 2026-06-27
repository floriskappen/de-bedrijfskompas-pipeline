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

1. The resolved homepage is always selected. The resolved homepage is the post-redirect URL reported by the fetch (`FetchResult.url`, with query and fragment dropped); it becomes the canonical base used for internal-link extraction, sitemap discovery, favicon resolution, and same-registered-domain filtering. `normalize_homepage` preserves a single-segment locale/language root (e.g. `/nl-nl`, `/en`) on the input URL so localised sites are crawled from the right shell; any other path is reduced to `/`.
2. Internal links from the homepage are extracted: only same-registered-domain (relative to the canonical base), `http`/`https` schemes. Fragment-only, `mailto:`, `tel:`, query-only links, and links to file downloads (`.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`, etc.) are excluded.
3. The sitemap is consulted as a supplementary URL source. Discovery order: fetch `/robots.txt`; if it advertises a `Sitemap:` URL (case-insensitive), use that; otherwise fall back to `<canonical-homepage>/sitemap.xml`. URLs from `<loc>` elements are filtered by the same same-registered-domain rule **and the same binary/document extension exclusion applied to homepage links** (`.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`, etc.), then merged into the candidate pool. A `<sitemapindex>` SHALL be followed for at most 3 nested sitemaps.
4. URLs whose path matches a configured list of **durable** path patterns (English and Dutch slugs, priority-ordered: identity/mission/services first; cases/team/contact/pricing/etc. second) are selected first.
5. A URL whose slug is **address-intent** — a contact/legal/privacy/terms/imprint stem appearing anywhere in the path (e.g. `/contact-2`, `/support/contact`, `/nl/contact`, `/privacy-policy`, `/privacybeleid`, `/legal-information`, `/voorwaarden-en-condities`), or `about`/`over`/`ons` as a whole path token — that matches no durable prefix SHALL nonetheless be classified into the supporting tier so address-bearing variants are not silently skipped.
6. Within each tier, candidates SHALL be ordered first by path depth (depth-1 paths like `/contact` before depth-2 paths like `/platform/discover-qualify`), then by the matched pattern's tier-position.
7. No more than 2 URLs sharing the same tier-path prefix SHALL be selected. Address-intent variants (classified by token/stem rather than a single prefix) are exempt from this shared-prefix cap so distinct contact/legal/privacy pages are not collapsed together.
8. **Fresh-content** patterns (`/blog`, `/news`, `/nieuws`, etc.) are selected only as fallback to reach a minimum of 3 pages, and never replace a durable match.
9. Total selection MUST NOT exceed 12 URLs.

Sitemap discovery is best-effort: a missing, malformed, or non-XML response SHALL NOT abort processing — the company simply proceeds with homepage-link candidates only. The configured path patterns and address-intent vocabulary live in code, not the spec; changes to them are not breaking.

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

#### Scenario: Address-intent variant selected

- **WHEN** homepage links include `/contact-2`, `/support/contact`, `/privacy-policy`, `/legal-information`, and `/nl/contact`, none of which match a durable prefix
- **THEN** each is classified as address-intent and selected (subject to the 12-URL cap), and the shared-prefix cap does not collapse them together

#### Scenario: Canonical domain adopted after redirect

- **WHEN** the input homepage redirects to a different registered domain (e.g. `zanders.eu` → `zandersgroup.com`)
- **THEN** the post-redirect host becomes the canonical base, links on that host pass the same-registered-domain filter, and `_meta.json.canonical_homepage_url` records it

#### Scenario: Locale root preserved

- **WHEN** the input website is `https://brunel.net/nl-nl`
- **THEN** the homepage is fetched at `https://brunel.net/nl-nl` (not the global `/` shell) so Dutch contact/location links are discovered

#### Scenario: External and non-HTTP links excluded

- **WHEN** homepage links include `/about`, `https://twitter.com/acme`, `mailto:hi@acme.example`, `/flyer.pdf`, and `#mission`
- **THEN** only `/about` is considered for selection

#### Scenario: Dutch-language paths recognised

- **WHEN** a Dutch site has links to `/over-ons`, `/diensten`, and `/werken-bij`
- **THEN** all three are selected as durable matches

#### Scenario: Sitemap image and document URLs excluded

- **WHEN** `/sitemap.xml` lists `/app/uploads/2023/logo-about.jpg` and `/files/brochure.pdf` alongside `/contact`
- **THEN** the `.jpg` and `.pdf` URLs are dropped (never selected or fetched), even though `logo-about` carries an `about` token; only `/contact` is added to the candidate pool

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

For each selected URL the stage SHALL fetch via plain HTTP by default — escalating to the headless browser per the Headless Browser Fallback requirement — and convert the response body to markdown using `trafilatura` with: comments excluded, images excluded, links excluded, tables included, formatting (headings) preserved, deduplication enabled, **`favor_precision=True`**. This precision-mode output is written to `<slug>.md`. Pages whose precision-mode markdown is shorter than 100 characters SHALL be dropped silently, except address-bearing slugs (see below), whose recall surface is produced regardless.

A page is **address-intent** when its slug carries a contact/legal/privacy/terms/imprint stem anywhere in it (covering both the canonical set `{"contact", "contact-us", "over-ons", "about", "about-us", "colofon", "privacy", "disclaimer", "algemene-voorwaarden"}` and variants such as `contact-2`, `support-contact`, `nl-contact`, `privacy-policy`, `privacybeleid`, `legal-information`, `voorwaarden-en-condities`), or its slug contains `about`/`over`/`ons` as a whole token. For address-intent pages the stage SHALL additionally run a recall-mode extraction (`favor_recall=True`, same other settings) and write the result to `<slug>.recall.md`. The recall extraction has no minimum-length threshold and SHALL be attempted even when the precision-mode markdown fell below the 100-character threshold, so sparse contact/legal pages still yield a recall surface. If recall returns nothing usable, the stage SHALL omit the `.recall.md` file silently.

For the same address-intent pages the stage SHALL also harvest the page's **raw visible text** directly from the (rendered) DOM — script/style/noscript removed, block-level boundaries emitted as newlines — and write it to `<slug>.visible.txt`. This surface preserves address cards and "our offices" widgets that trafilatura drops even in recall mode. It is intended only as an address-recall surface for `fact-extraction`'s postcode anchor; it SHALL NOT replace the precision `<slug>.md` used for summarisation/embedding. If the visible text is empty, the stage SHALL omit the `.visible.txt` file silently.

#### Scenario: Successful extraction

- **WHEN** a fetched page has substantive prose
- **THEN** precision-mode markdown longer than 100 chars is written to `<slug>.md`

#### Scenario: Sub-threshold non-address page dropped

- **WHEN** a fetched page resolving to a non-address slug yields fewer than 100 characters of precision-mode markdown
- **THEN** no markdown file is written; the URL is recorded in `_meta.json.urls_attempted` with `status: "dropped_thin"`

#### Scenario: Sparse contact page still yields recall surface

- **WHEN** a page resolves to slug `contact`, its precision-mode markdown is below 100 characters, but recall-mode extraction yields a non-empty body
- **THEN** `contact.recall.md` is written even though `contact.md` is dropped as thin

#### Scenario: Recall-mode markdown emitted for address-bearing slug

- **WHEN** a page resolves to slug `colofon` and recall-mode extraction yields a non-empty body
- **THEN** `colofon.recall.md` exists in the company directory

#### Scenario: Recall-mode skipped for non-address slugs

- **WHEN** a page resolves to slug `platform`
- **THEN** only `platform.md` is written; no `platform.recall.md` or `platform.visible.txt` is produced

#### Scenario: Raw visible text persisted for address-intent page

- **WHEN** a page resolves to slug `contact` and its rendered DOM contains a visible address card `Princetonlaan 6` / `3584 CB Utrecht` that trafilatura drops
- **THEN** `contact.visible.txt` is written containing `Princetonlaan 6` and `3584 CB Utrecht`, while `contact.md` retains only the precision prose

#### Scenario: Plain HTTP is the default path

- **WHEN** a site's static HTML yields link-bearing, substantive content
- **THEN** the stage extracts from the static HTML and no headless browser is used

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
- For address-intent pages, a parallel `<page-slug>.recall.md` when recall yielded content, and a parallel `<page-slug>.visible.txt` when raw visible text was non-empty.
- Exactly one `_meta.json` sidecar.

`_meta.json` SHALL contain:

- All keys from the input record (`name`, `website`, plus any extras).
- `status`: `"ok"`, `"thin"`, `"fetch_failed"`, or `"upstream_failed"` (see Status Tracking).
- `pages_collected`: integer count of precision-mode `.md` files written.
- `urls_attempted`: array of `{url, slug, status: "written" | "dropped_thin" | "error", error?}`.
- `footer_text`: string or `null`.
- `structured_text`: string or `null` — harvested machine-readable address signals (see Structured Address Capture).
- `canonical_homepage_url`: string or `null` — the post-redirect homepage URL adopted as the canonical crawl base (query/fragment dropped). `null` only for failed companies.
- `pages`: object keyed by slug, each `{url, title, description, sitename}` from `trafilatura.extract_metadata()`. Empty for failed companies.
- `sitemap_consulted`: boolean. `false` only when the homepage was not reachable.
- `sitemap_url`: string or `null` — the sitemap actually used.
- `sitemap_urls_found`: integer — count of `<loc>` URLs harvested before tier filtering.
- `favicon_url`: string or `null` — the extracted or fallback favicon URL.

#### Scenario: Successful company with three pages

- **WHEN** processing `Acme B.V.` (id `acme`) collects the homepage, `/about`, and `/contact`
- **THEN** `data/content-collection/acme/` contains `_meta.json`, `index.md`, `about.md`, `contact.md`, and (when recall yielded content) `about.recall.md`, `contact.recall.md`

#### Scenario: Structured text recorded

- **WHEN** the homepage embeds a JSON-LD `PostalAddress`
- **THEN** `_meta.json.structured_text` carries the harvested address text; a homepage with no such signal records `structured_text: null`

#### Scenario: Upstream-failed company

- **WHEN** the input record has `website: null` and `status: "failed"`
- **THEN** `_meta.json` has `status: "upstream_failed"`, `pages_collected: 0`, empty `urls_attempted` / `pages`, `structured_text: null`, `canonical_homepage_url: null`, all sitemap fields zero/null/false; no markdown files are written

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

- Verify that page content actually describes the named company.
- Extract structured facts from the markdown or parse harvested `structured_text` into `{street, postcode, city}` fields (deferred to `fact-extraction`).
- Honour `robots.txt` `Disallow` directives.
- Persist raw HTML to disk.

#### Scenario: No fact extraction here

- **WHEN** the homepage footer contains `"Europalaan 100, 3526 KS Utrecht"`
- **THEN** the stage writes that text into `footer_text` verbatim; it does NOT parse it into structured `{street, postcode, city}` fields

#### Scenario: Raw HTML not persisted

- **WHEN** the stage harvests `structured_text` from the homepage's raw HTML
- **THEN** only the extracted text is written to `_meta.json`; the raw HTML is not saved to disk

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

### Requirement: Realistic User-Agent

Every HTTP fetch the stage issues SHALL send a realistic, current browser `User-Agent` header sourced from `fake-useragent`, rotated per fetch. When the library yields no usable value, the stage SHALL fall back to a pinned modern browser `User-Agent` string. The stage SHALL NOT send a self-identifying bot `User-Agent`.

#### Scenario: Browser User-Agent sent

- **WHEN** the stage fetches any URL
- **THEN** the request carries a browser-class `User-Agent` (e.g. a current Chrome/Firefox/Safari string), not `de-bedrijfskompas/<version>`

#### Scenario: Fallback User-Agent when library yields nothing

- **WHEN** `fake-useragent` raises or returns an empty value
- **THEN** the fetch proceeds with a pinned modern browser `User-Agent` rather than failing

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

### Requirement: Structured Address Capture

From the homepage's raw HTML (and, when headless rendering occurred, the rendered DOM), the stage SHALL harvest machine-readable address signals before trafilatura extraction discards them, and concatenate their text into `_meta.json.structured_text`. The harvested signals SHALL include: JSON-LD `<script type="application/ld+json">` blocks containing a schema.org `PostalAddress` (e.g. `streetAddress`, `postalCode`, `addressLocality`); the textual content of `<address>` elements; and microdata `itemprop` address fields. Field values SHALL be joined with whitespace so the downstream postcode anchor can land on a `street postcode city` surface.

If no such signal is present, `structured_text` SHALL be `null`. The stage SHALL NOT parse the harvested text into structured `{street, postcode, city}` fields — that is `fact-extraction`'s job.

#### Scenario: JSON-LD PostalAddress harvested

- **WHEN** the homepage HTML embeds `<script type="application/ld+json">{"@type":"Organization","address":{"@type":"PostalAddress","streetAddress":"Stadsplateau 34","postalCode":"3521 AZ","addressLocality":"Utrecht"}}</script>`
- **THEN** `structured_text` contains `"Stadsplateau 34"`, `"3521 AZ"`, and `"Utrecht"` separated by whitespace

#### Scenario: address element harvested

- **WHEN** the homepage contains `<address>Europalaan 100, 3526 KS Utrecht</address>`
- **THEN** `structured_text` contains `"Europalaan 100, 3526 KS Utrecht"`

#### Scenario: No structured signal

- **WHEN** the homepage HTML contains no JSON-LD address, `<address>` element, or address microdata
- **THEN** `structured_text` is `null`

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

