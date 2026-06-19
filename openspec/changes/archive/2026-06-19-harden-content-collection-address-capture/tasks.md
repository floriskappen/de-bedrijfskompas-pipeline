## 1. Dependencies & environment

- [x] 1.1 Add `fake-useragent` and `playwright` to `pyproject.toml` dependencies; `pip install -e .`
- [x] 1.2 Document the one-time `playwright install chromium` step (README or content_collection/README.md) and confirm it runs in the project venv
- [x] 1.3 Verify imports load lazily so a missing Chromium binary does not break module import

## 2. Realistic User-Agent (content-collection fetch)

- [x] 2.1 Replace the static bot `USER_AGENT` in `pipeline/content_collection/fetch.py` with a per-fetch `fake-useragent` value; pin a modern fallback UA when the library yields nothing
- [x] 2.2 Test `test_fetch_sends_browser_user_agent` — asserts a browser-class UA, not `de-bedrijfskompas/*` (Scenario: Browser User-Agent sent)
- [x] 2.3 Test `test_fetch_falls_back_to_pinned_ua` — `fake-useragent` raising/empty still fetches with a pinned UA (Scenario: Fallback User-Agent when library yields nothing)

## 3. Headless browser fallback (content-collection)

- [x] 3.1 Add a Playwright/Chromium homepage renderer with a navigation timeout; on success return rendered HTML for the existing extract/select path
- [x] 3.2 Wire the trigger in `core.process`: escalate to headless when the homepage fetch returns 4xx/5xx/429/timeout, or returns 200 with `< MIN_HOMEPAGE_LINKS` internal `<a>` links (default 1)
- [x] 3.3 Treat headless failure (timeout, nav error, missing binary) as a normal fetch failure recorded in `urls_attempted`; never raise out of the batch
- [x] 3.4 Test `test_headless_triggered_on_429` (Scenario: Anti-bot status triggers headless)
- [x] 3.5 Test `test_headless_triggered_on_linkless_homepage` (Scenario: Link-less homepage triggers headless)
- [x] 3.6 Test `test_headless_skipped_when_static_homepage_usable` (Scenario: Usable static homepage skips headless)
- [x] 3.7 Test `test_headless_failure_degrades_gracefully` (Scenario: Headless failure degrades gracefully) — mock the renderer; no real browser in tests

## 4. Structured address capture (content-collection)

- [x] 4.1 Add a harvester in `pipeline/content_collection/extract.py` that pulls JSON-LD `PostalAddress`, `<address>` text, and address microdata from raw HTML, joining values with whitespace into `structured_text`
- [x] 4.2 Call the harvester in `core.process` against the homepage (raw or rendered) HTML; set `_meta.json.structured_text` (string or `null`); include it in the `_meta_skeleton`
- [x] 4.3 Test `test_structured_text_from_jsonld` (Scenario: JSON-LD PostalAddress harvested)
- [x] 4.4 Test `test_structured_text_from_address_element` (Scenario: address element harvested)
- [x] 4.5 Test `test_structured_text_null_when_absent` (Scenario: No structured signal)
- [x] 4.6 Test `test_meta_records_structured_text` and update upstream-failed test for `structured_text: null` (Scenarios: Structured text recorded, Upstream-failed company)

## 5. Widen address slugs & keep sparse address pages (content-collection)

- [x] 5.1 Update `ADDRESS_SLUGS` in `core.py` to the widened set; add `/contact-us`, `/colofon`, `/privacy`, `/disclaimer`, `/algemene-voorwaarden` to the crawl tier-path lists in `crawl.py`
- [x] 5.2 For address-bearing slugs, attempt recall extraction even when precision markdown is below threshold; write `<slug>.recall.md` though `<slug>.md` is dropped
- [x] 5.3 Test `test_sparse_contact_page_yields_recall` (Scenario: Sparse contact page still yields recall surface)
- [x] 5.4 Test `test_recall_emitted_for_colofon` (Scenario: Recall-mode markdown emitted for address-bearing slug)
- [x] 5.5 Test `test_non_address_subthreshold_dropped` and `test_recall_skipped_for_non_address_slug` (Scenarios: Sub-threshold non-address page dropped, Recall-mode skipped for non-address slugs)

## 6. fact-extraction: structured surface & all-page scanning

- [x] 6.1 In `address.extract_candidates`, scan `structured_text` first (surface `structured`), then `footer_text`, then every collected page (`body`); update `_rank_key` so `structured > footer > body`
- [x] 6.2 In `core._load_company`, read `structured_text` from `_meta.json`, apply recall-preference over the widened address-slug set, and pass all collected pages to extraction
- [x] 6.3 Widen the LLM-fallback surface slug list in `core._build_fallback_surface` to the widened address-slug set
- [x] 6.4 Test `test_structured_text_anchored` (Scenario: Structured signal anchored first)
- [x] 6.5 Test `test_postcode_on_non_address_page_anchored` (Scenario: Postcode on a non-address page anchored)
- [x] 6.6 Test `test_structured_beats_footer_beats_body` (Scenario: Structured beats footer beats body)
- [x] 6.7 Re-run existing fact-extraction regex/ranking/fallback tests to confirm no regression (Scenarios: Single clean footer hit, Postbus stripped, Boost wins without LLM, Postadres demoted, fallback scenarios)

## 8. Follow-up: remaining real misses (live-audit driven)

- [x] 8.1 Relax `address._POSTCODE_RE` to `\d{4}[ \t\xa0]*[A-Z]{2}` (repeated horizontal whitespace, no line-break span); keep uppercase guard. Tests `test_postcode_multiple_whitespace_tolerated`, `test_postcode_does_not_span_newline`
- [x] 8.2 Add `crawl.is_address_intent_slug` (token/stem) and extend `crawl._classify` so unmatched contact/legal/privacy variants classify as tier 2; exempt them from the per-prefix cap. Tests `test_is_address_intent_slug`, `test_select_urls_classifies_address_variants`
- [x] 8.3 Preserve locale-root paths in `crawl.normalize_homepage`. Test `test_normalize_homepage_locale_roots`
- [x] 8.4 Adopt post-redirect `FetchResult.url` as canonical base in `core.process` (links/sitemap/favicon/same-domain) and record `_meta.json.canonical_homepage_url`. Test `test_canonical_homepage_url_adopted_after_redirect`
- [x] 8.5 Add `extract.extract_visible_text`; in `core.process` write `<slug>.visible.txt` for address-intent pages. Tests `test_extract_visible_text_*`, `test_visible_txt_written_for_address_pages`
- [x] 8.6 Use `is_address_intent_slug` for recall in `content_collection.core`; mirror the predicate in `fact_extraction.core`; load `<slug>.visible.txt` and recall-only pages in `_load_company`; feed visible text to `extract_candidates` as `body`; widen `_build_fallback_surface` to address-intent variants (excluding visible text). Tests `test_visible_txt_recovers_dropped_address`, `test_fallback_surface_includes_address_intent_variants`
- [x] 8.7 Apply the homepage binary/document extension exclusion to sitemap `<loc>` URLs too (`crawl.has_excluded_extension`), so images/PDFs never consume a page slot or get fetched as junk "pages" (found live: zanders fetched a 165 KB JPEG via an `about`-token sitemap image). Test `test_has_excluded_extension`

## 7. Spec sync & end-to-end verification

- [x] 7.1 Run the full test suite (`pytest`): content-collection (94) and fact-extraction suites green; only 2 pre-existing non-deterministic `@pytest.mark.network` LLM-judgment tests (global_scoring, content_summarization — untouched stages) fail intermittently
- [x] 7.2 Re-run content-collection → fact-extraction → geocoding for the Utrecht set and confirm the address-success count rises materially from the 48/123 baseline
- [x] 7.3 Spot-check recovered companies (e.g. Channable via UA/headless+JSON-LD) now carry an exact `address` and geocode to `match_quality: "exact"`
