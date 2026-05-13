## 1. Sitemap discovery module

- [x] 1.1 Create `pipeline/content_collection/sitemap.py`
- [x] 1.2 Implement `discover_sitemap_url(homepage_url, *, fetch) -> str | None` — fetches `/robots.txt`, parses `Sitemap:` lines case-insensitively, returns the first advertised URL or falls back to `<homepage>/sitemap.xml`
- [x] 1.3 Implement `harvest_urls(sitemap_url, *, fetch, max_nested=3, max_urls_per_doc=500) -> list[str]` — parses the response as XML (`xml.etree.ElementTree`), matches `<loc>` by local name (namespace-agnostic), follows `<sitemapindex>` for at most `max_nested` children in declared order
- [x] 1.4 On non-XML responses, parse-error, or unrecognised root element: return `[]` silently (no exception bubbles up)
- [x] 1.5 Cap harvested URLs per leaf sitemap at `max_urls_per_doc` to bound pathological cases

## 2. Wire sitemap into the crawl

- [x] 2.1 In `core.process`, after homepage fetch succeeds, call `sitemap.discover_sitemap_url` + `sitemap.harvest_urls`
- [x] 2.2 Filter sitemap-harvested URLs through the same registered-domain check used in `crawl.extract_internal_links`
- [x] 2.3 Merge sitemap URLs with homepage-link URLs (sitemap appended after homepage links, so first-seen-wins still favours visible nav)
- [x] 2.4 Pass the merged list to `crawl.select_urls`; selection rules (tier matching, 8-cap, slug dedup) are unchanged
- [x] 2.5 Track `sitemap_consulted: bool`, `sitemap_url: str | None`, `sitemap_urls_found: int` and include them in the `_meta.json` payload (including in `_meta_skeleton` for `upstream_failed` and `fetch_failed` paths)

## 3. Tests (`tests/test_content_collection.py`)

Each test name maps to a `#### Scenario:` in the spec delta. All offline; mock `fetch.get` and provide canned sitemap XML.

- [x] 3.1 `test_sitemap_surfaces_unlinked_durable_pages` — homepage links only `/login`; `/sitemap.xml` lists `/pricing`; assert `/pricing` ends up in `urls_attempted` as `written`. Covers spec scenario "Sitemap surfaces unlinked durable pages"
- [x] 3.2 `test_sitemap_discovered_via_robots_txt` — `/robots.txt` advertises `Sitemap: /wp-sitemap.xml`; assert that URL is used and `/sitemap.xml` is NOT fetched. Covers "Sitemap discovered via robots.txt"
- [x] 3.3 `test_sitemap_index_nesting_capped` — root `<sitemapindex>` lists 5 children; assert exactly 3 are fetched, in declared order. Covers "Sitemap-index nesting"
- [x] 3.4 `test_malformed_sitemap_silently_ignored` — `/sitemap.xml` returns HTML; assert no exception, `sitemap_url: null`, `sitemap_urls_found: 0`, processing continues. Covers "Malformed sitemap silently ignored" + "Sitemap response that is HTML"
- [x] 3.5 `test_sitemap_metadata_recorded` — successful crawl; assert `sitemap_consulted: true`, `sitemap_url` matches, `sitemap_urls_found` is the count harvested. Covers "Sitemap metadata recorded"
- [x] 3.6 `test_upstream_failed_has_new_sitemap_fields` — `website: null`; assert `_meta.json` has `sitemap_consulted: false`, `sitemap_url: null`, `sitemap_urls_found: 0`. Covers updated "Upstream-failed company" scenario
- [x] 3.7 `test_robots_txt_disallow_ignored` — `/robots.txt` has both `Sitemap:` and `Disallow: /pricing`; homepage links to `/pricing`; assert `/pricing` is still fetched. Covers "robots.txt consulted only for sitemap" + "robots.txt Disallow ignored"
- [x] 3.8 `test_namespaced_sitemap_parsed` — XML uses the canonical `xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"`; assert `<loc>` URLs are still harvested. Covers "Namespaced sitemap parsed"
- [x] 3.9 `test_sitemap_url_per_doc_cap` — leaf sitemap declares 1000 URLs; assert at most 500 enter the candidate pool

## 4. Verification

- [x] 4.1 Re-run against `test-set/companies-medium.json` and confirm `autogrowth.com` flips `thin → ok` (the motivating case)
- [x] 4.2 Confirm no regression on the other 13 companies (same or improved status, identical or larger `pages_collected`)
- [x] 4.3 Update `pipeline/content_collection/README.md` to document the sitemap fallback and the three new `_meta.json` fields
