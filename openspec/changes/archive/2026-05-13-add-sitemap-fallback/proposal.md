# Proposal: Add sitemap fallback to content-collection

## Why

On the 14-company medium test set, 1 site (`autogrowth.com`) ships durable pages (`/pricing`) that exist in `/sitemap.xml` but aren't linked from the homepage's visible nav. Today this lands in `status: "thin"`. The current spec explicitly excludes sitemap parsing as a non-goal, but empirical data now shows it converts at least ~7% of cases from `thin` to `ok` for free, and the implementation is bounded (one extra HTTP request per company, simple XML parse).

## What Changes

- Probe each company's sitemap as a **supplementary** URL source after homepage-link extraction:
  1. Fetch `/robots.txt`; if it names a `Sitemap:` URL, use that.
  2. Otherwise try `/sitemap.xml`.
  3. If the response is a sitemap index, fetch up to N nested sitemaps.
- Merge sitemap-discovered URLs into the candidate pool that feeds tier-based selection. Tier matching and the 8-URL cap apply unchanged.
- Record in `_meta.json`: `sitemap_consulted: bool`, `sitemap_url: str | null`, `sitemap_urls_found: int`.
- Drop the "no sitemap parsing" line from the canonical spec's Out-of-Scope section.

Not in scope:
- Honoring `robots.txt` `Disallow` directives (still out of scope per the existing spec).
- Using sitemap URLs that do *not* match a configured tier path — sitemap is a discovery aid, not a license to fetch arbitrary pages.

## Capabilities

### New Capabilities

*(none)*

### Modified Capabilities

- `content-collection`: page selection gains sitemap as a supplementary URL source; `_meta.json` gains three new fields; Out-of-Scope drops the no-sitemap clause.

## Impact

- **Code**: new `pipeline/content_collection/sitemap.py`; small additions in `crawl.py` (merge URLs) and `core.py` (call sitemap, populate new `_meta.json` fields).
- **Dependencies**: no new dependencies — XML parsing via the stdlib `xml.etree.ElementTree` is sufficient for `<loc>` extraction.
- **Downstream stages**: `_meta.json` schema additions are purely additive and ignored by existing consumers.
- **Test set**: `autogrowth.com` expected to flip `thin → ok`. No regression risk for the other 13.
- **Spec**: one canonical requirement amended (Page Selection), one Out-of-Scope clause removed.
