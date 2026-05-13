## Context

Today the content-collection stage discovers candidate URLs purely by extracting `<a href>` links from the homepage. Empirical run against `test-set/companies-medium.json` (14 companies) shows this misses durable pages on at least 1 site (`autogrowth.com`: `/pricing` lives in the sitemap but isn't linked from the visible homepage nav). The stage currently lists "sitemap parsing" as a non-goal; the data now justifies revisiting that.

The stage already has the right shape for adding a supplementary URL source: link extraction (`crawl.extract_internal_links`) and selection (`crawl.select_urls`) are separate. We need a third feeder that produces additional candidate URLs, merged into the same pool before selection.

## Goals / Non-Goals

**Goals:**
- Convert sites whose durable pages are sitemap-only-discoverable from `thin` to `ok`, without changing behaviour on sites that already had homepage-link coverage.
- Add at most one extra HTTP request per company in the common case (`/sitemap.xml` direct); at most two when `robots.txt` is consulted first; at most a small bounded number when a sitemap index nests.
- Keep the new code isolated behind one module (`sitemap.py`) so the change is reversible.

**Non-Goals:**
- Honouring `robots.txt` `Disallow`. Out of scope here, as it was for the parent spec.
- Using sitemap URLs that don't match a configured tier path. Tier matching remains the gate.
- Caching sitemap responses across runs. Adds variance for marginal gain.
- Following sitemap-index nesting more than one level deep (real-world sitemaps rarely nest deeper, and we cap candidates at the existing 8-URL hard cap regardless).

## Decisions

### Discovery order

1. Fetch `/robots.txt` from the homepage host. Parse `Sitemap:` lines (case-insensitive). Use the first one found.
2. If no `Sitemap:` directive, fall back to `<homepage>/sitemap.xml`.
3. If both miss (HTTP error, non-XML body, empty document), the company gets `sitemap_consulted: true`, `sitemap_url: null`, `sitemap_urls_found: 0`. Selection proceeds with homepage links only.

Rationale: `robots.txt` is the canonical pointer per the Sitemaps protocol; many WordPress sites use `/wp-sitemap.xml` (apertas.nl) which `/sitemap.xml` would miss but `robots.txt` correctly advertises.

### XML parsing

Use `xml.etree.ElementTree` from the stdlib. Match the `<loc>` element under any namespace by local-name. This handles both `<urlset>` (a leaf sitemap with page URLs) and `<sitemapindex>` (a parent index pointing at child sitemaps).

When the response parses as `<sitemapindex>`, fetch up to **3** nested sitemaps in declared order. Sites with more than 3 sub-sitemaps almost always split by content type (posts vs pages vs taxonomies); the first few page-oriented ones are sufficient. Cap is a constant in `sitemap.py`, listed in the spec's Operational Pitfalls.

### Merge semantics

`sitemap.py` returns a `list[str]` of absolute URLs. The orchestrator filters them through the same registered-domain check that `extract_internal_links` uses, then concatenates with the homepage-link list. Selection (`crawl.select_urls`) is unchanged — it still applies tier matching, slug dedup, and the 8-URL cap.

Result: sitemap URLs compete with homepage URLs through the same tier ranking. If both `/about` (tier 1, from homepage) and `/about` (tier 1, from sitemap) appear, they slugify identically and the first-seen wins via the existing collision rule.

### New `_meta.json` fields

- `sitemap_consulted: bool` — true unless homepage fetch failed (we never reach sitemap discovery in that case).
- `sitemap_url: str | null` — the discovered sitemap URL actually used.
- `sitemap_urls_found: int` — total URLs harvested from the sitemap before tier filtering.

Additive only. Downstream stages that don't know about these fields ignore them.

### Trafilatura, sleep, error handling

No changes. Sitemap fetches use the existing `fetch.get` and respect the same timeout/retry policy. Sitemap-discovery HTTP errors are silent (logged via the `sitemap_url: null` signal) and never abort processing.

## Risks / Trade-offs

- **Sitemap drift / staleness** → sitemaps are often auto-generated and may include orphaned URLs. Tier-path matching limits damage: an orphaned `/blog/old-post` still has to match a tier path (`/blog`), and we cap to 8 URLs total. Acceptable.
- **Bogus sitemaps** → Some hosts serve HTML on `/sitemap.xml` (saw this in the diagnosis: `appic.nl` returns the SPA shell for everything). Mitigation: try to parse as XML; if it isn't, treat as "no sitemap found" and continue. No exception bubbles up.
- **Extra HTTP request budget** → 1–4 extra requests per company on the slow path. Well within rate-limit comfort given 14 companies and 1 s inter-page sleep already.
- **Spec section reorder** → The "Page Selection" requirement gains a sub-bullet about sitemap as a candidate source, and the Out-of-Scope clause "Parse sitemap.xml or otherwise discover URLs beyond the homepage's internal links" is dropped. Both are localized edits; no other spec sections are affected.

## Migration Plan

Additive change, no migration. Stale `_meta.json` files written by the previous version simply lack the new fields; downstream stages don't depend on them. Re-running the stage against `data/website-resolution/` overwrites with the new shape.

## Open Questions

- **Should we limit total sitemap URLs harvested before merging?** A pathological sitemap with 50k URLs would burn time matching against tier paths. Pragmatic cap: harvest at most 500 URLs per sitemap (per leaf, not per company). Cheap defensive bound, not yet a spec requirement.
- **Should `sitemap_consulted: false` be its own status?** No — `status` reflects the company-level result. `sitemap_consulted` is a metadata flag for evaluating how often the new path actually fires.
