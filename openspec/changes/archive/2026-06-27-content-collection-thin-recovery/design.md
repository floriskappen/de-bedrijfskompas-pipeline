## Context

`content-collection` fetches a homepage (plain HTTP, escalating to a headless browser as fallback), selects 1–12 URLs via a fixed durable-path tier vocabulary, fetches each sub-page via plain HTTP, and extracts markdown (dropping pages < 100 chars). 30 companies remain `status: "thin"` after re-crawl; investigation isolated three recoverable causes: JS-SPAs whose sub-pages return empty shells via plain HTTP, sites whose pages live on non-standard paths the tier list misses, and small-but-complete sites mislabeled "thin" by the 3-page gate.

## Goals / Non-Goals

**Goals:** recover the JS-shell and non-standard-path thin companies, and stop mislabeling substantial single-page brochure sites.

**Non-Goals:** fixing wrong-URL / bot-wall `fetch_failed` companies (separate, needs website re-resolution); changing the 100-char per-page drop threshold or the output schema; broadening the durable-path vocabulary by hand (whack-a-mole).

## Decisions

### Decision 1: site-wide headless for JS-sites, detected once
Detect the JS-site signal once on the homepage — if `render_homepage` was invoked (the existing `<1 internal link` / anti-bot trigger fired) — and propagate a flag so sub-pages are fetched headlessly too. **Alternative:** per-page plain-HTTP→headless fallback on every sub-page. Rejected: it doubles requests on every site and most are static; site-wide detection bounds headless cost to the ~8 detected JS-sites. Sub-page renders reuse one Playwright instance across the company's pages to amortise launch cost.

### Decision 2: shallow-link fallback as a 4th selection tier
When durable (tier 1–2) plus fresh-content (tier 3) selection leaves fewer than the minimum, fill remaining slots with the shallowest same-domain internal links not already selected (path-depth 1 first, then 2), up to the 12-URL cap. It runs last, so durable/news matches always win. **Alternative:** expand the durable path vocabulary. Rejected: the list is already broad and non-standard paths (`/learn`, `/knowledge`, `/profit-model`) keep appearing — a path-agnostic fallback is general.

### Decision 3: substantial-content "ok" via a character threshold on written pages
A 1–2 page crawl whose total written-markdown length ≥ `MIN_SUBSTANTIAL_CONTENT_CHARS` (named in spec) is `status: "ok"`. The threshold is ~20× the per-page drop threshold (100), i.e. a real page's worth of substance; below it, 1–2 pages stay `"thin"`. **Alternative:** lower the 3-page threshold. Rejected: 3 pages is a genuine diversity signal; a single page shouldn't always be "ok" regardless of content.

### Decision 4: generalise the renderer to an arbitrary URL
`render.render_homepage` becomes `render.render_page(url)` (the homepage is just one URL); the homepage `<1-link` trigger and anti-bot trigger remain. Keeps one render entry point and lets sub-pages use it under Decision 1.

## Risks / Trade-offs

- **[Headless sub-page crawl is slow on JS-sites]** ~seconds/page × up to 12 pages. → Mitigation: only JS-sites incur it; the inter-page sleep and 12-URL cap still apply.
- **[Shallow-link fallback fetches low-value pages (`/login`, `/cart`)]** → Mitigation: existing extension + same-domain filters apply; the 100-char markdown drop silently discards thin/low-value pages, so the cost is a wasted fetch, not bad content. (A small negative-slug set may be added in spec if noise is high.)
- **[Substantial-threshold false-positive on a 1-page shell]** → Mitigation: the threshold is on *written* markdown (pages that passed the 100-char gate); an empty shell with 0 written pages stays `fetch_failed`/`thin`. Safe.
