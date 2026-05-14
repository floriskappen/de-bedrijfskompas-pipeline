## MODIFIED Requirements

### Requirement: Page Selection

For each company with a usable website, the stage SHALL select between 1 and 12 URLs to fetch, including the resolved homepage. The selection algorithm:

1. The resolved homepage is always selected.
2. Internal links from the homepage are extracted: only same-registered-domain links, only `http`/`https` schemes. Fragment-only, `mailto:`, `tel:`, query-only links, and links to file downloads (e.g. `.pdf`, `.zip`, `.jpg`, `.png`, `.mp4`) are excluded.
3. The stage SHALL additionally consult the site's sitemap as a **supplementary** URL source. Discovery order: fetch `/robots.txt`; if it advertises a `Sitemap:` URL (case-insensitive), use that. Otherwise fall back to `<homepage>/sitemap.xml`. URLs harvested from `<loc>` elements are filtered by the same same-registered-domain rule and merged into the candidate pool. A sitemap response that is a `<sitemapindex>` SHALL be followed for at most 3 nested sitemaps in declared order.
4. URLs whose path matches a configured list of **durable** path patterns are selected first. The patterns SHALL cover both English and Dutch slugs and SHALL be ordered by priority (identity/mission/services first; cases/team/contact/pricing/etc. second).
5. Within each tier, candidates SHALL be ordered first by path depth (top-level paths like `/contact` before deeper sub-pages like `/platform/discover-qualify`), then by the tier-internal priority of the matched pattern. Top-level paths typically carry the canonical content for their topic; deeper sub-pages are variants that should not displace coverage of other topics.
6. No more than 2 URLs sharing the same tier-path prefix SHALL be selected. Without this cap a sub-tree like `/platform/*` can fill the entire slate and crowd out other tier-1/tier-2 paths (`/contact`, `/about`) that downstream stages depend on.
7. URLs whose path matches **fresh-content** patterns (e.g. `/blog`, `/news`, `/nieuws`) are selected only as fallback to bring the page count to at least 3, and never replace a durable match.
8. Total selection MUST NOT exceed 12 URLs (homepage included).

Sitemap discovery is best-effort: a missing, malformed, or non-XML sitemap response SHALL NOT abort processing — the company simply proceeds with homepage-link candidates only. The configured path patterns are an implementation detail (lives in code, not the spec); changes to them are not breaking changes.

#### Scenario: Durable paths win over fresh paths

- **WHEN** homepage links include `/about`, `/team`, `/pricing`, and `/blog`
- **THEN** `/about`, `/team`, and `/pricing` are selected; `/blog` is selected only if removing it would leave fewer than 3 pages

#### Scenario: Page cap enforced

- **WHEN** more than 12 candidate URLs match durable patterns
- **THEN** at most 12 URLs are fetched (including the homepage)

#### Scenario: Top-level paths beat sub-pages

- **WHEN** homepage links include `/platform`, `/platform/discover-qualify`, `/platform/clarifications`, `/contact`, all matching durable tier-1/tier-2 patterns
- **THEN** `/platform` and `/contact` (depth 1) are selected before any `/platform/*` sub-page (depth 2), regardless of where the patterns sit in the tier list

#### Scenario: Per-prefix cap prevents sub-tree monopoly

- **WHEN** the homepage links to `/platform`, `/platform/a`, `/platform/b`, `/platform/c`, `/platform/d`, and `/contact`, all matching durable patterns
- **THEN** at most 2 of the `/platform`-prefixed URLs are selected, leaving room for `/contact`

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

### Requirement: Content Extraction

For each selected URL the stage SHALL fetch the page via plain HTTP (no JavaScript rendering) and convert the response body to markdown using `trafilatura` with settings that prefer cleanliness over completeness: comments excluded, images excluded, links excluded, tables included, formatting (headings) preserved, deduplication enabled, precision favoured over recall. This **precision-mode** output is written to `<slug>.md` and is the canonical surface for downstream LLM-driven stages (summarisation, embeddings) where fewer tokens with higher signal-to-noise is the right trade-off.

A page whose extracted precision-mode markdown is shorter than a minimum threshold (100 characters) SHALL be dropped silently — it carries no usable content and writing it would only add noise.

For pages whose slug is in `{"contact", "over-ons", "about", "about-us"}` — the canonical surfaces for company address content — the stage SHALL additionally run a second trafilatura extraction in **recall mode** (`favor_recall=True`, same other settings) and write the result to `<slug>.recall.md`. Recall mode retains structured side-blocks (address cards, "Our offices" sections, contact widgets) that precision mode classifies as boilerplate and strips. fact-extraction prefers this file when present because its postcode anchor is regex-based: it benefits from more surface, not less. The recall extraction SHALL NOT apply the minimum-length threshold — even a short recall output is preserved if it contains anything, since address blocks are inherently terse.

If recall extraction returns no usable text (empty / `None`) the stage SHALL silently omit the `.recall.md` file; absence is interpreted by fact-extraction as "no recall surface available, fall back to the precision file".

#### Scenario: Successful extraction

- **WHEN** a fetched page has substantive prose
- **THEN** trafilatura returns precision-mode markdown longer than the minimum threshold and `<slug>.md` is written

#### Scenario: Sub-threshold page dropped

- **WHEN** a fetched page yields fewer than 100 characters of precision-mode markdown
- **THEN** no markdown file is written for that page, and the URL is recorded in `_meta.json.urls_attempted` so the drop is auditable

#### Scenario: Recall-mode markdown emitted for address-bearing slug

- **WHEN** a page resolves to slug `contact` and recall-mode extraction yields a non-empty markdown body
- **THEN** both `contact.md` (precision) and `contact.recall.md` (recall) exist in the company directory

#### Scenario: Recall-mode omitted when empty

- **WHEN** a page resolves to slug `about-us` and recall-mode extraction returns nothing usable
- **THEN** only `about-us.md` is written; `about-us.recall.md` is absent

#### Scenario: Recall-mode skipped for non-address slugs

- **WHEN** a page resolves to slug `platform` (not in the address-bearing set)
- **THEN** only `platform.md` is written; no `platform.recall.md` is produced, even if a recall extraction would have yielded content

#### Scenario: Plain HTTP only

- **WHEN** a site relies on client-side JavaScript to render its content
- **THEN** the stage extracts whatever the static HTML provides; it does NOT spin up a headless browser

### Requirement: Footer Capture

The stage SHALL extract the textual content of the homepage's `<footer>` element(s) separately from the trafilatura-extracted markdown and SHALL store it in `_meta.json.footer_text`. Footer text is treated as **metadata**, not page content, because it commonly contains structured facts (HQ address, postcode, Chamber of Commerce numbers) that trafilatura intentionally strips from its main-content extraction.

Extraction SHALL preserve block-level element boundaries as newlines: each block-level child of the footer (`<div>`, `<p>`, `<h1>`–`<h6>`, `<li>`, `<address>`, `<section>`, `<br>`, etc.) emits a `\n` at its boundary so the resulting text retains the visual field separation the HTML author intended. Naïve `text_content()` concatenation MUST NOT be used: it fuses sibling inline elements (`<a>LinkedIn</a><a>Instagram</a>` becomes `LinkedInInstagram`) and erases the line breaks that the downstream postcode anchor relies on to delimit street / postcode / city fields. Within a single block, horizontal whitespace runs SHALL be collapsed to a single space; empty lines SHALL be dropped; vertical whitespace (`\n`) SHALL be preserved as field separators.

If the homepage has no `<footer>` element or its contents are empty after stripping, `_meta.json.footer_text` SHALL be set to `null`.

#### Scenario: Footer with address captured

- **WHEN** the homepage HTML contains `<footer>...Europalaan 100, 3526 KS Utrecht...</footer>`
- **THEN** `_meta.json.footer_text` contains "Europalaan 100, 3526 KS Utrecht" (alongside whatever other footer text is present)

#### Scenario: Block boundaries preserved

- **WHEN** the homepage footer is `<footer><p>Smallepad 32</p><p>3811 MG Amersfoort</p><div>Volg ons</div><a>LinkedIn</a><a>Instagram</a></footer>`
- **THEN** `_meta.json.footer_text` contains the substrings `"Smallepad 32"`, `"3811 MG Amersfoort"`, `"Volg ons"`, `"LinkedIn"`, `"Instagram"` separated by newlines — never fused into `"LinkedInInstagram"` or similar

#### Scenario: Footer absent

- **WHEN** the homepage has no `<footer>` element
- **THEN** `_meta.json.footer_text` is `null`

#### Scenario: Footer not duplicated into page markdown

- **WHEN** trafilatura has stripped the footer from the homepage's markdown output (its default behavior)
- **THEN** the stage does not attempt to re-inject footer text into `index.md`; the markdown stays as trafilatura produced it

### Requirement: Output File Layout

For each company processed (successfully or not), the stage SHALL produce a subdirectory at `data/content-collection/<company-id>/` containing:

- One precision-mode markdown file per surviving page, named `<page-slug>.md`. The page slug is derived from the URL path: leading and trailing slashes are stripped, internal slashes are replaced with hyphens, query strings and fragments are dropped, and the result is slugified to lowercase ASCII (`/` → `index`, `/about-us` → `about-us`, `/about/team` → `about-team`, `/over-ons/` → `over-ons`, `/about?lang=en#x` → `about`).
- For pages whose slug is in the address-bearing set `{"contact", "over-ons", "about", "about-us"}`, a parallel `<page-slug>.recall.md` file when recall-mode extraction yielded usable content (see Content Extraction).
- Exactly one `_meta.json` sidecar describing the company-level result.

`_meta.json` SHALL contain:

- All keys from the input record (`name`, `website`, plus any extra keys that flowed in).
- `status`: one of `"ok"`, `"thin"`, `"fetch_failed"`, `"upstream_failed"` (see Status Tracking).
- `pages_collected`: integer count of precision-mode markdown files written. The recall-mode variant files are not counted separately; they accompany an already-counted precision file.
- `urls_attempted`: array of objects `{url, slug, status: "written" | "dropped_thin" | "error", error?}`.
- `footer_text`: string or `null` (see Footer Capture).
- `pages`: object keyed by page slug, each value `{url, title, description, sitename}` extracted via `trafilatura.extract_metadata()`. Empty object for failed companies.
- `sitemap_consulted`: boolean. `true` when the stage attempted sitemap discovery; `false` when the homepage was not reachable (in which case sitemap lookup is skipped).
- `sitemap_url`: string or `null`. The sitemap URL actually used, or `null` when discovery failed or produced no usable URLs.
- `sitemap_urls_found`: integer. Count of URLs harvested from the sitemap before tier filtering. Zero when no sitemap was found.

#### Scenario: Successful company with three pages

- **WHEN** processing `Acme B.V.` (id `acme`) collects the homepage, `/about`, and `/contact`
- **THEN** `data/content-collection/acme/` contains `_meta.json`, `index.md`, `about.md`, `contact.md`, and (when recall extraction yielded content) `about.recall.md`, `contact.recall.md`

#### Scenario: Slug derivation

- **WHEN** the selected URLs are `https://acme.example/`, `https://acme.example/about-us`, `https://acme.example/about/team`, `https://acme.example/over-ons/`
- **THEN** the resulting precision-mode files are `index.md`, `about-us.md`, `about-team.md`, `over-ons.md`; recall-mode files (when content is present) are `about-us.recall.md` and `over-ons.recall.md`. The `about-team` slug is not address-bearing, so no `about-team.recall.md` is written.

#### Scenario: Upstream-failed company

- **WHEN** the input record has `website: null` and `status: "failed"`
- **THEN** `data/content-collection/<id>/_meta.json` exists with `status: "upstream_failed"`, `pages_collected: 0`, `urls_attempted: []`, `footer_text: null`, `pages: {}`, `sitemap_consulted: false`, `sitemap_url: null`, `sitemap_urls_found: 0`; no markdown files (precision or recall) are written

#### Scenario: Sitemap metadata recorded

- **WHEN** a successful crawl consulted `/sitemap.xml` and harvested 12 URLs (of which 2 ended up in `urls_attempted` after tier filtering)
- **THEN** `_meta.json` records `sitemap_consulted: true`, `sitemap_url: "https://acme.example/sitemap.xml"`, `sitemap_urls_found: 12`
