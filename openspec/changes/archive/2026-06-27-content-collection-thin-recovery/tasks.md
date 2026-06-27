## 1. Shallow-link fallback selection (`crawl.py`)

- [x] 1.1 In `select_urls`, after durable (tier 1–2) and fresh-content (tier 3) selection, when `len(selected) < MIN_PAGES_BEFORE_TIER_3`, fill remaining slots with the shallowest same-domain internal links not already selected or excluded (path-depth 1 first, then depth 2), up to `MAX_SELECTED_URLS`. Do not displace a durable/fresh match.
- [x] 1.2 Add `test_select_urls_shallow_link_fallback_recovers_nonstandard_path` — homepage links `/learn`, `/learn/roadmaps`, `/knowledge` (no tier match), only homepage selected → fallback selects `/learn` + `/knowledge` (depth 1) before depth-2 (covers *Non-standard path recovered by fallback*).
- [x] 1.3 Add `test_select_urls_shallow_link_fallback_does_not_displace_durable` — `/about` (durable) + `/learn` (non-standard), below minimum → `/about` selected first, `/learn` fills a remaining slot only after durable/fresh tiers (covers *Fallback does not displace durable matches*).
- [x] 1.4 Add `test_select_urls_shallow_link_fallback_skipped_when_minimum_met` — durable tiers already select ≥3 → no shallow-link fallback selection, no generic links added (covers *Fallback skipped when minimum already met*).
- [x] 1.5 Confirm `test_select_urls_tier3_fallback` still passes (fresh-content fallback unchanged; shallow-link runs after it).

## 2. Headless sub-page rendering (`render.py` + `core.py`)

- [x] 2.1 Generalise `render.render_homepage` to `render.render_page(url)` (the homepage is one URL); keep the existing `FetchResult` contract, navigation timeout, and graceful-failure behaviour. Keep a thin `render_homepage` wrapper or update its single caller.
- [x] 2.2 In `core.process`, propagate a JS-site flag when the homepage was rendered headlessly (the existing `<1-link` / anti-bot trigger fired). When the flag is set, fetch selected sub-pages via `render.render_page` instead of `fetch.get`, reusing one Playwright browser instance across the company's sub-pages. Static-HTML sites keep the plain-HTTP sub-page path.
- [x] 2.3 Add `test_js_site_subpages_fetched_headlessly` — homepage rendered headlessly (link-less) + 2 sub-pages selected → sub-pages fetched via the renderer (assert renderer called per sub-page), not `fetch.get` (covers *JS-site sub-pages fetched headlessly*).
- [x] 2.4 Confirm existing headless tests still pass: `test_headless_triggered_on_429`, `test_headless_triggered_on_linkless_homepage`, `test_headless_skipped_when_static_homepage_usable`, `test_headless_failure_degrades_gracefully` (covers *Anti-bot status triggers headless*, *Link-less homepage triggers headless*, *Usable static homepage skips headless*, *Headless failure degrades gracefully*).

## 3. Substantial-content status gate (`core.py`)

- [x] 3.1 In `core.process`, relax the status gate: a 1–2 page crawl whose total written-markdown length ≥ `MIN_SUBSTANTIAL_CONTENT_CHARS` (default 2000) is `status: "ok"`; below it, 1–2 pages stay `"thin"`. ≥3 pages remain `"ok"` unchanged. Name the constant in `crawl.py` or `core.py` alongside the other `Final` thresholds.
- [x] 3.2 Add `test_process_substantial_single_page_is_ok` — only the homepage survives, its markdown ≥ 2000 chars → `status: "ok"` (covers *Substantial single-page brochure site*).
- [x] 3.3 Update `test_process_thin_status` — only the homepage survives AND its markdown is below `MIN_SUBSTANTIAL_CONTENT_CHARS` → `status: "thin"` (covers *Thin result*).
- [x] 3.4 Confirm `test_process_ok_status` (≥3 pages) and `test_process_fetch_failed_homepage` still pass (covers *Healthy crawl*, *Homepage unreachable*).

## 4. Verify end-to-end

- [x] 4.1 Run `pytest tests/test_content_collection.py -m "not network"` — all green.
- [x] 4.2 Run the full offline suite `pytest tests/ -m "not network"` — no regressions.
- [x] 4.3 Live check: re-crawl a few previously-thin companies of each kind — a JS-shell (`andmore`, `kenter`) and a non-standard-path site — and confirm they now reach `status: "ok"` (or at least gain pages vs. before).
