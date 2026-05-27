## ADDED Requirements

### Requirement: Favicon URL Extraction

The stage SHALL extract a favicon URL from the homepage HTML. It SHALL parse `<link>` tags with `rel` values in `("icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed")`. It SHALL choose the icon closest to the target size of 512x512 (preferring size $\ge 512$ sorted ascending, then size $< 512$ sorted descending), preferring modern `rel` types as a tie-breaker. If no `<link>` tag is found, it SHALL fall back to `<homepage_url>/favicon.ico`. If the homepage fetch fails, `favicon_url` SHALL be `null`.

#### Scenario: Best candidate favicon URL selected
- **WHEN** the homepage HTML contains candidate icons of sizes `16x16`, `192x192`, `1024x1024`, and `512x512`
- **THEN** the absolute URL of the `512x512` icon is chosen

#### Scenario: Fallback icon used
- **WHEN** the homepage HTML contains no favicon links, or the homepage fetch fails
- **THEN** `favicon_url` is `<homepage_url>/favicon.ico` or `null` respectively

## MODIFIED Requirements

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
