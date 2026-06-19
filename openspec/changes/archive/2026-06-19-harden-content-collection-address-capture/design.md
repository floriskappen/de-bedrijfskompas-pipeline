## Context

`content-collection` fetches each company site with httpx and a static bot User-Agent, extracts markdown via trafilatura, and writes per-page `.md` plus `_meta.json`. `fact-extraction` then anchors a Dutch-postcode regex over `footer_text` and four hardcoded page slugs. A Utrecht run left 75/123 companies with no usable address. The failures cluster into three collection-side causes: anti-bot status codes (custom UA → 403/429), JS-rendered homepages whose links never appear in raw HTML (so only the homepage is collected), and addresses that live only in JSON-LD / `<address>` blocks trafilatura discards.

## Goals / Non-Goals

**Goals:**
- Recover addresses blocked by anti-bot responses and by JS rendering.
- Preserve machine-readable structured addresses (JSON-LD/`<address>`/microdata) that the current markdown path throws away.
- Reuse the existing postcode-anchor machinery in fact-extraction — no new address-parsing logic.
- Keep the headless engine off the hot path: only sites that need it pay for it.

**Non-Goals:**
- External name+city registry/geocoder lookup (deferred; the only fix for sites that publish no address at all).
- Changing the geocoding stage, the postcode regex itself, or the LLM fallback prompt.
- Full JS crawling: headless renders the homepage to recover links/DOM; subsequent pages still use httpx where they respond.

## Decisions

**Realistic rotating UA via `fake-useragent`.** A static bot UA earns 403/429 (Channable: 429→200 under a browser UA). `fake-useragent` yields real, current browser strings and auto-refreshes; rotation also softens per-host pattern-blocking. Alternative — pin one Chrome string — works today but goes stale and needs manual bumps. The UA is chosen once per fetch in `fetch.get`.

**Playwright headless as a triggered fallback, not the default.** ~85% of sites work with httpx + a real UA, and a browser per company is slow and heavy. So headless fires only when (a) httpx returns 4xx/429/5xx/timeout, or (b) the homepage renders ~0 internal `<a>` links (SPA signal). The rendered HTML then re-enters the existing `extract_internal_links` → `select_urls` → crawl path unchanged. Alternative — always headless — rejected on cost; alternative — never headless — leaves the SPA bucket unrecovered.

**Capture structured address as text, parse it downstream (Option B).** Only `content-collection` sees raw HTML, so it harvests JSON-LD `PostalAddress`, `<address>`, and microdata into a new `structured_text` field on `_meta.json`. `fact-extraction` treats `structured_text` as a new candidate surface (`structured`) ranked above footer/body, so the existing postcode regex extracts it with no new parser. This keeps the stage boundary clean (collect vs. interpret) and avoids polluting the semantically-distinct `footer_text`. Alternative — append to `footer_text` — rejected as it conflates two surfaces.

**Widen address slugs and scan all collected pages.** The fixed `{contact, over-ons, about, about-us}` set misses `contact-us`, `colofon`, `privacy`, `disclaimer`, `algemene-voorwaarden` (where Dutch sites park their registered address), and the address sometimes sits on `index`/`careers`. Address-bearing slugs are retained even when markdown is "thin" (contact pages are often sparse forms) and always recall-extracted; fact-extraction scans every collected page for a postcode, not a fixed slug list.

**Address-intent classification by path token/stem, not a fixed slug list.** A live audit showed usable addresses still missed because address pages carry slug *variants* the prefix-only tier matcher never classified: `/contact-2`, `/support/contact`, `/nl/contact`, `/contact-ons`, `/privacy-policy`, `/privacybeleid`, `/legal-information`, `/voorwaarden-en-condities`. `is_address_intent_slug` recognises contact/legal/privacy/terms/imprint stems anywhere in the slug, plus `about`/`over`/`ons` as whole tokens (stems would over-match `discover-qualify`). Unmatched variants now classify as tier 2 (alongside `/contact`) so they enter normal selection and are recall- and visible-text-extracted. The same predicate drives recall preference and the LLM-fallback surface. Stages stay self-contained, so content-collection and fact-extraction each keep their own copy of the predicate, kept in sync by hand. The audit confirmed the page-budget cap was *not* the cause — every missed company collected well under the 12-page limit — so a reserved address-page pre-pass (which would reorder tier-1 identity pages ahead of address pages) was rejected as unnecessary risk.

**Adopt the post-redirect URL as the canonical base; preserve locale roots.** Sites that moved domain (`zanders.eu` → `zandersgroup.com`) or redirect `/` to a locale path surfaced useful pages on a host the input URL never reached, and the same-domain filter then rejected them. After a successful homepage fetch the stage adopts `FetchResult.url` (query/fragment dropped) as the base for link extraction, sitemap discovery, favicon, and same-domain filtering, recording both the input `website` and the resolved `canonical_homepage_url`. The registered-domain filter still bounds the crawl to the resolved host. `normalize_homepage` additionally preserves a single-segment locale/language root (`/nl-nl`, `/en`) so a localised homepage (e.g. `brunel.net/nl-nl`) is crawled from its Dutch shell where the Dutch contact links live.

**Persist a raw visible-text surface for address-intent pages (recall-only).** trafilatura — even in recall mode — classifies address cards and "our offices" widgets as boilerplate and drops them, so a plainly-visible address (`Princetonlaan 6, 3584 CB Utrecht`) can be absent from both `.md` and `.recall.md`. For address-intent pages the stage walks the rendered `<body>` directly (script/style stripped, block boundaries → newlines) into `<slug>.visible.txt`. fact-extraction feeds it to the postcode anchor as a `body`-ranked surface but excludes it from the LLM-fallback surface, because raw text is noisy (nav, forms, cookie banners) and would only add noise to the prose prompt. It never replaces the precision markdown used for summarisation/embedding.

**Relax postcode whitespace to repeated horizontal whitespace.** Visible-text surfaces sometimes render the postcode gap as several spaces/NBSPs (`3526  KV  Utrecht`), which the single-optional-whitespace regex missed. The class becomes `[ \t\xa0]*` — repeated, but horizontal only: the digit/letter pair never spans a line break in practice, and allowing newlines would match a stray 4-digit line end above a 2-uppercase line start (e.g. a year above `NL`). The uppercase-letter-pair guard is kept, so year+word false positives stay rejected.

## Risks / Trade-offs

- **Playwright is a heavy dependency** (browser binaries via `playwright install chromium`) → keep it import-lazy and fallback-only; document the install step; a missing browser degrades to httpx-only, not a crash.
- **`fake-useragent` reaches out / can return stale data** → it ships a bundled fallback list; pin a sane default UA if the library yields nothing.
- **Headless is slow and can hang** → enforce a navigation timeout and treat a headless failure as a normal fetch failure (record and move on).
- **More aggressive UA / rendering edges toward unwelcome scraping** → preserve polite crawling (inter-page sleep, low volume, no login-walled content); honor the existing per-company URL cap.
- **Keeping thin address pages adds noise** → bounded to the address-slug set only, and recall extraction already exists for them.
