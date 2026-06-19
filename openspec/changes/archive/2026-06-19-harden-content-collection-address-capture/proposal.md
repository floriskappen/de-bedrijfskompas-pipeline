## Why

The frontend is a map, so a company with no exact coordinates shows nothing — yet a recent Utrecht run left 75 of 123 companies without a usable postal address. Diagnosis shows most failures are collection, not extraction: anti-bot blocks (custom bot User-Agent → 403/429), JS-rendered homepages whose links never appear in raw HTML, and addresses living in JSON-LD / `<address>` blocks that trafilatura strips. This change hardens the collection so far more companies reach geocoding with an exact street + postcode.

## What Changes

- **Realistic browser User-Agent** on every fetch via `fake-useragent` (rotating), replacing the static `de-bedrijfskompas/0.1` bot UA. (Verified: Channable returns 429 to the bot UA, 200 to a browser UA.)
- **Headless fallback (Playwright)** invoked *only* when httpx fails (4xx/429/timeout) or returns a homepage with ~0 internal `<a>` links (JS-rendered SPA); the rendered DOM then re-enters the normal crawl/extract path. Headless stays off the hot path for sites that don't need it.
- **Structured-address harvest** from the raw HTML before trafilatura runs: JSON-LD schema.org `PostalAddress`, the `<address>` tag, and microdata, captured into a new `structured_text` field in `_meta.json`.
- **Keep address-bearing pages even when "thin"** and always recall-extract them; widen the address-slug set (add `contact-us`, `colofon`, `privacy`, `disclaimer`, `algemene-voorwaarden`).
- **fact-extraction scans the new `structured_text` as a high-priority surface** (`structured`, ranked above footer/body) and scans **all** collected pages for postcodes, not just four hardcoded slugs — no new parsing logic; the existing postcode-anchor regex does the work.
- **Address-intent URL classification** — contact/legal/privacy address pages whose slug is a *variant* (`/contact-2`, `/support/contact`, `/nl/contact`, `/privacy-policy`, `/privacybeleid`, `/legal-information`, `/voorwaarden-en-condities` …) are now recognised by path token/stem and selected (as tier 2) instead of being silently skipped by the prefix-only classifier.
- **Canonical homepage adoption** — after the homepage fetch, the post-redirect `FetchResult.url` becomes the canonical base for link extraction, sitemap discovery, favicon, and same-domain filtering (recovering sites that moved domain, e.g. `zanders.eu` → `zandersgroup.com`); recorded as `canonical_homepage_url` in `_meta.json`. `normalize_homepage` also preserves a single-segment locale root (`/nl-nl`) so localised sites crawl from the right shell.
- **Raw visible-text surface** — for address-intent pages the stage persists a `<slug>.visible.txt` extracted directly from the rendered DOM (block-break walk), capturing address cards that trafilatura drops even in recall mode. fact-extraction scans it as a `body` surface for the postcode anchor only (kept out of the LLM-fallback surface).
- **Relaxed postcode whitespace** — the anchor regex tolerates runs of horizontal whitespace/NBSP between digits and letters (`3526  KV`), while still requiring an uppercase letter pair and never spanning a line break.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `content-collection`: realistic/rotating User-Agent; Playwright fallback for failed or link-less fetches; structured-address (`structured_text`) capture from raw HTML; widened address-slug set retained even when thin; address-intent URL classification by path token/stem; canonical post-redirect homepage adoption with `canonical_homepage_url`; locale-root preservation in `normalize_homepage`; raw `<slug>.visible.txt` surface for address-intent pages.
- `fact-extraction`: a new `structured` candidate surface scanned ahead of footer/body; postcode scanning across all collected pages rather than a fixed slug list; raw visible-text surfaces fed to the anchor as `body`; address-intent slug variants recognised for recall preference and the LLM-fallback surface; postcode regex tolerant of repeated horizontal whitespace.

## Impact

- **Stages**: `content-collection` (fetch, crawl, extract, core), `fact-extraction` (address candidate sourcing).
- **Dependencies**: add `fake-useragent` and `playwright` (plus a one-time `playwright install chromium`).
- **Boundary**: stages stay self-contained — content-collection *captures* structured text; fact-extraction *parses* it.
- **Out of scope**: companies that publish no address anywhere (e.g. bol, amulet, quantib) remain unrecoverable here; they need the deferred external name+city registry/geocoder lookup.
