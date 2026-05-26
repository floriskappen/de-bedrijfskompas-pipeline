## 1. Module scaffolding

- [ ] 1.1 Create `pipeline/geocoding/` with `__init__.py`, `core.py`, `pdok.py`, `address.py`, `__main__.py` (mirroring `fact_extraction` shape; no shared cross-stage helpers beyond `company_id`).
- [ ] 1.2 Add `data/geocoding/` to `.gitignore` if `data/` is not already covered globally.

## 2. PDOK client (`pdok.py`)

- [ ] 2.1 Implement a self-contained HTTPS client against `https://api.pdok.nl/bzk/locatieserver/search/v3_1/free` using only stdlib (`urllib.request`) or the same HTTP library `website-resolution` uses; default 5s timeout, single attempt.
- [ ] 2.2 Implement three tier-query builders (`exact`, `postcode_centroid`, `city_centroid`) using strict `fq=` filters per the spec; each returns `latlng` parsed from `centroide_ll` (`POINT(<lng> <lat>)` → `{ "lat": ..., "lng": ... }`) or `None` on `numFound: 0`.
- [ ] 2.3 Raise a typed `PDOKError` on transport failure / non-2xx / unparseable response so `core.py` can map it to `status: "lookup_error"`.
- [ ] 2.4 Test `test_centroide_ll_parsed_lng_lat_swap` (verify the WKT parser produces lat ≈ 52.08, lng ≈ 5.17 for `POINT(5.17259687 52.08263581)`) → *Scenario: Successful exact hit*.
- [ ] 2.5 Test `test_pdok_error_propagated` (mock transport raises → `PDOKError`) → *Scenario: PDOK error distinct from empty*.

## 3. Address preparation (`address.py`)

- [ ] 3.1 Implement `prepare(address)` returning a struct with `postcode_no_space`, `huisnummer` (int or None), `city` (str or None), and a `skip_reason` (`"non_nl"` / `"no_anchor"` / None).
- [ ] 3.2 House-number regex: `re.search(r"\b(\d+)\b", street)` left-to-right; suffix letters ignored.
- [ ] 3.3 Test `test_postcode_space_stripped` → *Scenario: Postcode space stripped*.
- [ ] 3.4 Test `test_house_number_parsed` (`"Cambridgelaan 771"` → `771`) → *Scenario: House number parsed from street*.
- [ ] 3.5 Test `test_suffix_letter_ignored` (`"Europalaan 100a"` → `100`) → *Scenario: Suffix letter ignored*.
- [ ] 3.6 Test `test_non_nl_skip_reason` (`country: "BE"` → `skip_reason: "non_nl"`) → *Scenario: Non-NL skipped without HTTP*.
- [ ] 3.7 Test `test_no_anchor_skip_reason` (`postcode: None, city: None` → `skip_reason: "no_anchor"`) → *Scenario: No usable anchor skipped without HTTP*.

## 4. Core: input gating, tier orchestration, status (`core.py`)

- [ ] 4.1 Implement `process(fact_record, *, out_dir, write, offline, client)` and `run(records, ...)` batch generator, mirroring sibling stages' shape.
- [ ] 4.2 Gate on fact-extraction success-status set `{regex_single, regex_disambiguated, llm_fallback}`. Non-success → emit `upstream_failed`, no HTTP.
- [ ] 4.3 Apply `address.prepare` before any HTTP; on `skip_reason` → emit `status: "empty"`, no HTTP.
- [ ] 4.4 Iterate tiers `exact` → `postcode_centroid` → `city_centroid`, skipping a tier whose required inputs are unavailable; stop at first hit.
- [ ] 4.5 Map outcomes to `status` (`ok` / `empty` / `upstream_failed` / `lookup_error`).
- [ ] 4.6 Catch per-company errors so a single failure does not abort the batch.
- [ ] 4.7 Test `test_upstream_success_proceeds` → *Scenario: Upstream success proceeds*.
- [ ] 4.8 Test `test_upstream_non_success_cascades` (no HTTP made) → *Scenario: Upstream non-success cascades*.
- [ ] 4.9 Test `test_extra_input_keys_preserved` (`source` round-trips) → *Scenario: Extra input keys preserved*.
- [ ] 4.10 Test `test_exact_tier_hits` (mock tier 1 returns hit, tiers 2 & 3 not called) → *Scenario: Exact tier hits*.
- [ ] 4.11 Test `test_exact_falls_through_to_postcode` → *Scenario: Exact tier falls through to postcode tier*.
- [ ] 4.12 Test `test_postcode_falls_through_to_city` → *Scenario: Postcode tier falls through to city tier*.
- [ ] 4.13 Test `test_all_tiers_empty_yields_empty_status` → *Scenario: All tiers empty*.
- [ ] 4.14 Test `test_tier_skipped_when_input_unavailable` (no huisnummer → `exact` not queried) → *Scenario: Tier skipped when input unavailable*.
- [ ] 4.15 Test `test_non_nl_emits_empty_without_http` → *Scenario: Non-NL skipped without HTTP*.
- [ ] 4.16 Test `test_no_anchor_emits_empty_without_http` → *Scenario: No usable anchor skipped without HTTP*.
- [ ] 4.17 Test `test_lookup_error_recorded` → *Scenario: PDOK error distinct from empty*.
- [ ] 4.18 Test `test_one_failure_does_not_abort_batch` → *Scenario: One PDOK failure does not abort batch*.

## 5. Output writer (`core.py`)

- [ ] 5.1 Write one JSON per company at `data/geocoding/<company-id>.json` matching the Output Schema (`name`, `website`, `latlng`, `match_quality`, `source`, `status`, plus carried-through input keys).
- [ ] 5.2 Enforce the `latlng` / `match_quality` / `source` non-null-together invariant before write (assert in code, regression-test).
- [ ] 5.3 Refuse to overwrite a file whose stored `name` differs (raise).
- [ ] 5.4 Test `test_successful_write_shape` (record carries the expected keys with proper types) → *Scenario: Successful exact hit* / *Successful write*.
- [ ] 5.5 Test `test_all_null_together_on_failure` (any non-ok status → latlng/match_quality/source all null) → *Scenario: All-null when no lookup succeeds*.
- [ ] 5.6 Test `test_name_collision_refusal` → *Scenario: Name-collision refusal*.

## 6. CLI (`__main__.py`)

- [ ] 6.1 Implement `main(argv)` discovering `.json` files under `data/fact-extraction/`, with `--input`, `--out-dir`, `--dry-run`, `--offline`, `--company`, `--limit`; load `.env` with `override=False` (matches sibling stages).
- [ ] 6.2 Test `test_cli_run` (with mocked PDOK client, produces one JSON per fact-extraction file) → *Scenario: CLI run*.
- [ ] 6.3 Test `test_dry_run_yields_without_writing` → *Scenario: Dry-run yields without writing*.
- [ ] 6.4 Test `test_offline_mode_short_circuits_http` (offline → `status: empty`, no HTTP call) → *Scenario: Offline mode short-circuits HTTP*.
- [ ] 6.5 Test `test_behaviour_parity_across_modes` (dry-run record == written record for the same input) → covers Execution-Modes parity.

## 7. Out-of-scope guard

- [ ] 7.1 Test `test_non_nl_not_queried_globally` (with `country: "BE"`, no fallback HTTP to Nominatim or anything else) → *Scenario: Non-NL not queried globally*.
- [ ] 7.2 Test `test_no_response_cache_persisted` (running the stage twice still hits the (mocked) client both times — no on-disk cache silently appears).

## 8. `dataset-output` projection

- [ ] 8.1 Extend `pipeline/dataset_output/core.py` to load `data/geocoding/<id>.json` alongside the existing sources; add `GEOCODING_DIR` constant.
- [ ] 8.2 Project `latlng` and `match_quality` at the root per the updated Field Projection requirement.
- [ ] 8.3 Update `_assemble` (and any block-null helpers) so `latlng` and `match_quality` are nulled together when geocoding is absent or non-success.
- [ ] 8.4 Update Record-Status `empty` check to include `latlng` in the "every payload block null" predicate.
- [ ] 8.5 Test `test_dataset_output_fully_populated_includes_latlng` → *Scenario: Fully populated record*.
- [ ] 8.6 Test `test_dataset_output_latlng_match_quality_move_together` → *Scenario: latlng and match_quality move together*.
- [ ] 8.7 Test `test_dataset_output_geocoding_non_success_nulls_block` → *Scenario: Geocoding non-success nulls the latlng block*.
- [ ] 8.8 Test `test_dataset_output_latlng_alone_is_ok` (only geocoding present → status `ok`) → *Scenario: Latlng alone is ok*.
- [ ] 8.9 Test `test_dataset_output_shell_company_empty_with_latlng_null` → *Scenario: Shell company is empty*.

## 9. Pipeline-architecture wave renumbering — non-spec text

- [ ] 9.1 Update `pipeline/website_resolution/__init__.py` docstring: `Pipeline stage 1` → `Pipeline stage 1` (unchanged, confirm only).
- [ ] 9.2 Update `pipeline/content_collection/__init__.py` docstring: `Pipeline stage 2` → unchanged, confirm only.
- [ ] 9.3 Update `pipeline/fact_extraction/__init__.py` docstring: `Pipeline stage 3` → `Pipeline stage 3a`.
- [ ] 9.4 Update `pipeline/content_summarization/__init__.py` docstring: `Pipeline stage 4` → `Pipeline stage 3b`; replace `every stage-5 theme-analytic stage consumes` with `every wave-4 dossier-derived analytic stage consumes`.
- [ ] 9.5 Update `pipeline/tagline_extraction/__init__.py` docstring: `Pipeline stage 5` → `Pipeline stage 4b`.
- [ ] 9.6 Update `pipeline/global_scoring/__init__.py` docstring: `Pipeline stage 5` → `Pipeline stage 4c`.
- [ ] 9.7 Update `pipeline/website_resolution/README.md` heading: `pipeline stage 1` (unchanged, confirm only).
- [ ] 9.8 Update `pipeline/content_collection/README.md` heading + line 68 reference: `pipeline stage 2` (unchanged) and `fact-extraction (stage 3)` → `fact-extraction (stage 3a)`.
- [ ] 9.9 Update `openspec/specs/fact-extraction/spec.md` Purpose: `Pipeline stage 3:` → `Pipeline stage 3a:` (canonical-spec edit; Purpose is not a delta-able requirement).
- [ ] 9.10 Grep the repo (`stage [0-9]`, `stage-5`) post-edit and confirm no stale labels remain outside `openspec/changes/archive/`.

## 10. Verification & live test run

- [ ] 10.1 Run the full suite (`pytest`, excluding `network`-marked tests) and confirm every Scenario above has a passing named test.
- [ ] 10.2 Run `python -m pipeline.geocoding` over the existing `data/fact-extraction/` against live PDOK; spot-check a known address (Cambridgelaan 771 → ≈ 52.0826, 5.1726) lands as `match_quality: "exact"`.
- [ ] 10.3 Run `python -m pipeline.dataset_output` and verify the resulting record carries `latlng` and `match_quality` at the root for the spot-checked company.
- [ ] 10.4 Run `openspec validate add-geocoding-stage --strict` and `openspec validate` (full) — both clean.
