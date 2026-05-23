## 1. Strip Dutch from tagline-extraction

- [x] 1.1 Edit `prompts/tagline-extraction.md`: remove the Dutch instruction, change the output format to `{"en": "<tagline>"}` only
- [x] 1.2 Edit `pipeline/tagline_extraction/llm.py`: update the response validator to require only a non-empty `en` string (drop `nl` check)
- [x] 1.3 Edit `pipeline/tagline_extraction/core.py`: update `_record` default tagline to `{"en": null}` and successful tagline shape to `{"en": string}`
- [x] 1.4 Update `tests/test_tagline_extraction.py` (if it exists): remove `nl` assertions, add `test_tagline_en_only_shape` confirming `tagline` has `en` and no `nl` key; add `test_null_tagline_on_non_ok` confirming null shape is `{"en": null}`; add `test_malformed_response_missing_en` confirming `llm_error` when `en` is absent

## 2. Strip Dutch from global-scoring

- [x] 2.1 Edit `prompts/global-scoring.md`: remove the Dutch translation instruction; change reason output format in the schema block to `"reason": {"en": "..."}` only
- [x] 2.2 Edit `pipeline/global_scoring/llm.py`: update `_validate_axis` to require only non-empty `reason.en` (drop `reason.nl` check); drop the `nl` key from the reason normalization/validation path
- [x] 2.3 Edit `pipeline/global_scoring/core.py`: update any default reason shape references to `{"en": null}` (no `nl`)
- [x] 2.4 Update `tests/test_global_scoring.py`: remove `nl` assertions from reason checks; update `test_inconsistent_score_evidence_normalized` to reflect en-only reason shape; add `test_reason_en_only` confirming `reason` has `en` and no `nl` key

## 3. New translation stage

- [x] 3.1 Create `pipeline/translation/__init__.py` (empty, mirrors other stages)
- [x] 3.2 Create `pipeline/translation/frontmatter.py` (copy verbatim from `pipeline/tagline_extraction/frontmatter.py`)
- [x] 3.3 Create `prompts/translation.md`: instruct the model to translate a JSON dict of English strings `{key: en_text, ...}` to Dutch, returning `{key: nl_text, ...}` with the same keys; preserve tone and meaning, no additions or omissions, plain language
- [x] 3.4 Create `pipeline/translation/llm.py`: define `TRANSLATION_TARGETS = [("tagline-extraction", "tagline"), ("global-scoring", "scores.*.reason")]`; implement `resolve_targets(record, targets)` expanding `*` wildcards; implement `call(messages)` and `_validate_response(raw, expected_keys)`; `resolve_model()` reads `TRANSLATION_MODEL` env var with DeepSeek V4 Flash as default
- [x] 3.5 Create `pipeline/translation/core.py`: implement `_resolve_company_targets(company_id, targets, source_dirs)` that reads each source stage output and extracts `en` strings at each target path; implement `build_messages(targets_dict)` using the versioned prompt; implement `process(record, *, out_dir, write, offline)` and `run(records, *, out_dir, write, offline)` following the fan-in pattern; implement `_record(...)` with `translations: null` on non-ok; implement `_write(...)` with name-collision guard
- [x] 3.6 Create `pipeline/translation/__main__.py`: derives company list by scanning registered source-stage output dirs; calls `run()`; mirrors `pipeline/tagline_extraction/__main__.py` structure

## 4. Tests for translation stage

- [x] 4.1 Create `tests/test_translation.py` with offline tests covering:
  - `test_target_registry_enumerated` — registry contains exactly the declared targets, no others
  - `test_wildcard_path_expands` — `scores.*.reason` resolves to 5 `en` strings from a global-scoring fixture
  - `test_company_absent_from_one_source` — missing tagline-extraction file → global-scoring targets still translated, status ok
  - `test_company_absent_from_all_sources` — all sources missing → status `upstream_failed`, no LLM call
  - `test_successful_record_shape` — `data/translation/acme.json` has status ok, non-null model, `translations` with expected flat keys
  - `test_null_translations_on_non_ok` — non-ok status → `translations: null`
  - `test_name_collision_refusal` — existing file with different `name` raises
  - `test_partial_sources_still_yield_ok` — one source `llm_error`, one source ok → status ok with partial keys
  - `test_malformed_response_is_error` — unparseable LLM response → status `llm_error`
  - `test_one_failure_does_not_abort_batch` — one company LLM error, others succeed
  - `test_offline_mode` — no LLM call, status `empty`
