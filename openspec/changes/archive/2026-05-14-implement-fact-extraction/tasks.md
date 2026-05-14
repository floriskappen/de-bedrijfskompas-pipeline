## 1. Package Scaffold

- [x] 1.1 Create `pipeline/fact_extraction/` package with `__init__.py`, `__main__.py`, `core.py`, `address.py`, `llm.py`, `prompt.py`
- [x] 1.2 Add `OPENROUTER_API_KEY` loading via `python-dotenv` (`override=False`) in `__main__.py`; expose `FACT_EXTRACTION_MODEL` env var with a small-model default
- [x] 1.3 Create `data/fact-extraction/` output directory (gitignore entry if needed)

## 2. Address Extraction (`address.py`)

- [x] 2.1 Implement postcode regex (`\d{4}\s?[A-Z]{2}`) with boundary guards (no alphanumeric continuation); normalise matches to `"DDDD LL"` uppercase with single space — covers `test_single_clean_footer_hit`, `test_lowercase_normalised`, `test_nospace_normalised`
- [x] 2.2 Implement surrounding-context capture: up to 80 chars before (street) and 40 chars after (city), stripping to nearest comma/newline boundary — covers `test_single_clean_footer_hit`
- [x] 2.3 Implement `Postbus` filter: discard candidates whose `street` starts with `Postbus`, `P.O. Box`, `Pb.` (case-insensitive, trailing punctuation-tolerant) — covers `test_postbus_stripped`
- [x] 2.4 Implement Unicode/non-breaking-space tolerance in regex matching — covers `test_nonbreaking_space_tolerated`
- [x] 2.5 Implement hint-window scanning (60 chars before/after, capped at newline): boost on `bezoekadres`, `hoofdkantoor`, `vestiging`, `vestigingsadres`, `kantooradres`, `hq`; demote on `postadres`, `correspondentieadres`, `factuuradres` — covers `test_boost_wins_without_llm`, `test_postadres_demoted`
- [x] 2.6 Implement surface ranking: `footer` candidates rank above `body` candidates at equal hint tier — covers `test_footer_beats_body`
- [x] 2.7 Implement sole-boost shortcut: if exactly one candidate carries a boost-class hint and no other does, emit directly as `regex_single` without LLM — covers `test_boost_wins_without_llm`
- [x] 2.8 Reject postcode matches embedded in email addresses or product codes (boundary guard from 2.1) — covers `test_postcode_in_email_rejected`
- [x] 2.9 Implement input-surface selection: `footer_text` first, then `contact.md` → `over-ons.md` → `about.md` → `about-us.md` in order, concatenated

## 3. LLM Client (`llm.py`, `prompt.py`)

- [x] 3.1 Implement thin `httpx`-based OpenRouter client: POST to chat completions, configurable model, JSON-mode request, retry up to 2 times on transport/decode failure
- [x] 3.2 Strip leading/trailing markdown code fences before JSON parse — covers `test_fenced_llm_json_parsed`
- [x] 3.3 Implement disambiguation prompt in `prompt.py`: receives candidate list (≤5, each with `street`, `postcode`, `city`, up to 200-char context), returns chosen index or `null`
- [x] 3.4 Implement prose-fallback prompt in `prompt.py`: receives concatenated surface text (≤2000 chars), returns `{street, postcode, city, country}` with explicit nulls
- [x] 3.5 Post-LLM postcode re-validation: if emitted `postcode` does not match postcode regex, drop to `null` (retain other fields) — covers `test_invalid_postcode_dropped`

## 4. Core Resolution Pipeline (`core.py`)

- [x] 4.1 Implement `process(meta, pages, *, out_dir, write, offline=False) -> dict`: orchestrates address.py → LLM paths, sets correct `status`, returns output schema
- [x] 4.2 Handle `upstream_failed` / `fetch_failed` input: emit `status: "upstream_failed"` immediately without extraction — covers `test_upstream_failure_propagation`
- [x] 4.3 Implement `regex_single` path: one surviving candidate, no LLM call — covers `test_single_clean_footer_hit`, `test_boost_wins_without_llm`, `test_postbus_stripped`
- [x] 4.4 Implement `regex_disambiguated` path: 2+ candidates → disambiguation LLM call; `null` response → `status: "empty"` — covers `test_two_equal_candidates_resolved`, `test_llm_declines_to_pick`
- [x] 4.5 Implement `llm_fallback` path: zero candidates → prose-extraction LLM call; all-null result still sets `status: "llm_fallback"` — covers `test_prose_only_address`, `test_fallback_yields_nothing`
- [x] 4.6 Implement `llm_error` path: catch LLM exceptions after retries, record `status: "llm_error"`, continue to next company — covers `test_llm_error_distinct_from_empty`, `test_one_llm_failure_does_not_abort_batch`
- [x] 4.7 Implement `offline` mode: skip LLM calls entirely; companies needing LLM get `status: "empty"` (or the top-ranked candidate if a sole-boost exists) — covers `test_offline_mode_short_circuits_llm`
- [x] 4.8 Implement input key pass-through: all `_meta.json` keys not in the output schema are copied verbatim — covers `test_extra_input_keys_preserved`
- [x] 4.9 Implement name-collision guard: refuse to overwrite `<id>.json` if stored `name` differs from current record — covers `test_name_collision_refusal`
- [x] 4.10 Implement `run(records, *, write, out_dir, offline=False) -> Iterator[dict]`: orchestrator-callable batch runner; `write=False` is dry-run — covers `test_dry_run_yields_without_writing`, `test_behaviour_parity_across_modes`

## 5. CLI Entry Point (`__main__.py`)

- [x] 5.1 Implement `python -m pipeline.fact_extraction`: discover all company dirs in `data/content-collection/`, call `run`, write outputs to `data/fact-extraction/`, print summary — covers `test_cli_run`
- [x] 5.2 Add `--dry-run` flag (suppresses writes) and `--offline` flag (suppresses LLM calls)
- [x] 5.3 Add `--company <id>` flag to process a single company for spot-checking

## 6. Tests — Offline (`tests/test_fact_extraction.py`)

- [x] 6.1 `test_single_clean_footer_hit`: footer with one postcode → `regex_single`, correct `{street, postcode, city, country}`
- [x] 6.2 `test_postbus_only_footer`: Postbus-only → candidate filtered; mock LLM called (fallback path)
- [x] 6.3 `test_postbus_and_bezoekadres`: Postbus + bezoekadres both present → bezoekadres wins, `regex_single`, no LLM
- [x] 6.4 `test_two_postcodes_hauptkantoor_hint`: two postcodes, one labelled `hoofdkantoor` → `regex_single` without LLM
- [x] 6.5 `test_two_equal_candidates_resolved`: two postcodes, no hints → disambiguation LLM called with those candidates; assert called with correct payload
- [x] 6.6 `test_llm_declines_to_pick`: disambiguation LLM returns `null` → `status: "empty"`
- [x] 6.7 `test_prose_only_address`: no postcode anywhere, LLM fallback returns city → `status: "llm_fallback"`, `address.city` set
- [x] 6.8 `test_fallback_yields_nothing`: LLM fallback returns all-null → `status: "llm_fallback"` (not `"empty"`)
- [x] 6.9 `test_upstream_failure_propagation`: `_meta.json.status: "upstream_failed"` → output `status: "upstream_failed"`, no LLM call
- [x] 6.10 `test_extra_input_keys_preserved`: extra key in `_meta.json` → present unchanged in output
- [x] 6.11 `test_name_collision_refusal`: existing `<id>.json` with different name → raises
- [x] 6.12 `test_llm_error_distinct_from_empty`: disambiguation LLM raises → `status: "llm_error"`, not `"empty"`
- [x] 6.13 `test_one_llm_failure_does_not_abort_batch`: second company LLM fails → first and third still produced
- [x] 6.14 `test_dry_run_yields_without_writing`: dry-run mode → yields records, no files on disk
- [x] 6.15 `test_offline_mode_short_circuits_llm`: offline flag → no LLM calls made for any company
- [x] 6.16 `test_behaviour_parity_across_modes`: same input in CLI, orchestrator, dry-run → identical output record
- [x] 6.17 `test_postcode_in_email_rejected`: surface contains `support@1234ab.example` → no candidate produced
- [x] 6.18 `test_nonbreaking_space_tolerated`: non-breaking spaces in postcode → candidate produced with normalised postcode
- [x] 6.19 `test_fenced_llm_json_parsed`: LLM returns JSON in code fences → parsed without `llm_error`
- [x] 6.20 `test_invalid_postcode_dropped`: LLM emits incomplete postcode → `postcode` null, other fields retained
- [x] 6.21 `test_postadres_demoted`: candidate preceded by `Postadres:` → ranked below non-demoted candidates
- [x] 6.22 `test_footer_beats_body`: footer candidate vs body candidate, no hints → footer ranks first
- [x] 6.23 `test_lowercase_normalised`: lowercase postcode in input → output postcode uppercased
- [x] 6.24 `test_nospace_normalised`: postcode without space in input → output postcode has single space
- [x] 6.25 `test_all_fields_present`: full address extracted → output schema complete with all four address fields
- [x] 6.26 `test_partial_address`: only city extractable → `street`, `postcode`, `country` null, `city` set
- [x] 6.27 `test_no_address_found`: extraction runs, yields nothing → `status: "empty"`, all address fields null
- [x] 6.28 `test_status_path_labelling`: prose-fallback all-null vs disambiguation decline → former is `llm_fallback`, latter is `empty`

## 7. Tests — Network (`@pytest.mark.network`)

- [x] 7.1 End-to-end against `test-set/companies.json` (small set) using real `data/content-collection/` output and real LLM: all companies produce a `data/fact-extraction/<id>.json`; no unhandled exceptions; ≥50% of companies whose `footer_text` contains a Dutch postcode pattern land in `regex_single`
- [x] 7.2 End-to-end against `test-set/companies-medium.json` (14 companies) using the same conditions: all 14 companies produce a file; no unhandled exceptions; ≥50% of companies whose `footer_text` contains a Dutch postcode pattern land in `regex_single`
- [x] 7.3 Assert both network tests are gated by `OPENROUTER_API_KEY` presence (skip if absent)

## 8. Content-collection surface upgrades (MODIFIED capabilities)

These tasks land the content-collection changes documented in the proposal's Modified Capabilities section.

- [x] 8.1 Block-aware footer extraction in `pipeline/content_collection/extract.py`: replace `text_content()` with a tree walk that emits `\n` at block-element boundaries and a space at inline boundaries, then normalises horizontal whitespace and drops empty lines — covers spec scenario "Block boundaries preserved" via `test_footer_block_boundaries_preserved`
- [x] 8.2 Bump `MAX_SELECTED_URLS` from 8 to 12 in `pipeline/content_collection/crawl.py` — covers updated spec scenario "Page cap enforced" via `test_select_urls_enforces_cap`
- [x] 8.3 Depth-first ordering within each tier in `select_urls`: pre-sort tier candidates by `(path_depth, tier_position)` so top-level paths (depth=1) land before deeper sub-pages — covers spec scenario "Top-level paths beat sub-pages" via `test_select_urls_top_level_beats_subpages`
- [x] 8.4 Per-prefix selection cap (`PER_PREFIX_CAP=2`) in `select_urls`: refuse to add a URL whose tier-path prefix already has 2 selections — covers spec scenario "Per-prefix cap prevents sub-tree monopoly" via `test_select_urls_top_level_beats_subpages` and `test_select_urls_per_prefix_cap_leaves_room_for_others`
- [x] 8.5 Add `extract_markdown_recall(html)` in `extract.py`: same trafilatura settings as the precision extractor except `favor_recall=True` instead of `favor_precision=True`
- [x] 8.6 Dual extraction in `content_collection/core.py`: for pages whose slug is in `{"contact", "over-ons", "about", "about-us"}` (constant `ADDRESS_SLUGS`), call `extract_markdown_recall` after the precision extract; write `<slug>.recall.md` when the recall body is non-empty — covers spec scenarios "Recall-mode markdown emitted for address-bearing slug" via `test_process_writes_recall_md_for_address_slugs` and "Recall-mode skipped for non-address slugs" via the same test
- [x] 8.7 Silently omit `.recall.md` when recall extraction returns empty/None — covers spec scenario "Recall-mode omitted when empty" via `test_process_omits_recall_md_when_empty`
- [x] 8.8 Update `_write_company` signature to accept an optional `recall_pages` dict and write each entry to `<slug>.recall.md`
- [x] 8.9 In `pipeline/fact_extraction/core.py` `_load_company`: for each address-bearing slug, prefer `<slug>.recall.md` over `<slug>.md` — covers fact-extraction spec scenarios "Recall-mode markdown preferred" via `test_recall_md_preferred_over_md` and "Precision markdown used when recall absent" via `test_md_used_when_no_recall_md`
- [x] 8.10 Fact-extraction street extraction: include `\n` in the trailing-whitespace strip inside `address._strip_street` so block-structured footers (street on the line above the postcode) yield the street, not an empty string
