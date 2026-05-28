## 1. Prompt and Vocabulary

- [x] 1.1 Write `prompts/tagging.md`: system prompt describing the task, the 19 tier-1 family slugs with one-line descriptions each, prominence definitions (`core` / `supporting` / `incidental`), edge-case routing (production-line / vehicle-operators → `field-trades-operators`; management consulting → `commercial`; public administration → `policy-public-administration`; retail/call-centre/personal services → `service-hospitality`), one-entry-per-family rule, JSON output schema, and a short worked example using a company that touches multiple families (e.g. a Landlife-shaped reforestation company).

## 2. Stage Scaffold

- [x] 2.1 Create `pipeline/tagging/` package with `__init__.py`, `__main__.py`, `core.py`, `llm.py`, `frontmatter.py`, mirroring the layout of `pipeline/tagline_extraction/`.
- [x] 2.2 Implement `frontmatter.py` as a self-contained dossier-frontmatter reader (copy of the tagline-extraction equivalent — no shared helper per project rule).

## 3. LLM Client

- [x] 3.1 Implement `pipeline/tagging/llm.py` with `resolve_model()` (arg → `TAGGING_MODEL` env → `deepseek/deepseek-v4-flash`), `call()` posting to OpenRouter with JSON-object response format, retries, and `LLMError`.
- [x] 3.2 Implement parsing that validates the response: array of `{family, prominence}` objects; each `family` in the fixed 19-slug set; each `prominence` in `core`/`supporting`/`incidental`; no duplicate families. Any violation raises `ValueError` (caller maps to `LLMError`).

## 4. Stage Core

- [x] 4.1 Implement `pipeline/tagging/core.py` with `process(meta, body, *, out_dir, write, offline)` returning the record dict, status-gated on dossier `status == "ok"`, writing `data/tagging/<company-id>.json` with `name`, `website`, `status`, `model`, `capability_tags`.
- [x] 4.2 Implement `run(records, *, out_dir, write, offline, content_dir)` yielding one record per company, never raising on per-company load errors.
- [x] 4.3 Enforce name-collision refusal in `_write`.

## 5. CLI

- [x] 5.1 Implement `pipeline/tagging/__main__.py` with the standard flags `--input`, `--out-dir`, `--dry-run`, `--offline`, `--company`, `--limit`, mirroring tagline-extraction's CLI.
- [x] 5.2 Verify `python -m pipeline.tagging --dry-run --limit 1` against `data/content-summarization/` on the local test corpus.

## 6. Dataset-Output Integration

- [x] 6.1 Update `pipeline/dataset_output/` to read `data/tagging/<company-id>.json`, project `capability_tags` onto the root of the record (verbatim or `null`), and treat it as a payload block for `status: "ok"` vs `"empty"`.
- [x] 6.2 Confirm the aggregated `data/dataset-output/companies.json` carries the new `capability_tags` field for at least one company on the local test corpus.

## 7. Orchestrator Wiring

- [x] 7.1 Add `tagging` to the orchestrator's stage list as wave `4d`, dependency `content-summarization`, not a translation input, parallel-eligible with `4b`/`4c`.
- [x] 7.2 Verify a full `python -m pipeline.run` pass on the local test corpus produces `data/tagging/*.json` for every dossier with `status: ok`.

## 8. Tests — `pipeline/tagging/`

Tests live in a flat `tests/test_tagging.py` to match the codebase convention used by `test_tagline_extraction.py` and `test_global_scoring.py`.

- [x] 8.1 `tests/test_tagging.py::test_dossier_body_is_llm_input` — covers spec scenario "Dossier body is the LLM input".
- [x] 8.2 `tests/test_tagging.py::test_missing_dossier_is_upstream_failed` — covers "Missing dossier treated as upstream failure".
- [x] 8.3 `tests/test_tagging.py::test_non_ok_dossier_cascades` — covers "Non-ok dossier cascades".
- [x] 8.4 `tests/test_tagging.py::test_ok_dossier_proceeds` — covers "Ok dossier proceeds".
- [x] 8.5 `tests/test_tagging.py::test_empty_body_recorded` — covers "Empty body short-circuits to empty status".
- [x] 8.6 `tests/test_tagging.py::test_emitted_family_in_fixed_set` — covers "Emitted family is in the fixed set".
- [x] 8.7 `tests/test_tagging.py::test_out_of_vocab_family_is_llm_error` — covers "Out-of-vocabulary family is treated as LLM error".
- [x] 8.8 `tests/test_tagging.py::test_tag_has_family_and_prominence` — covers "Tag carries family and prominence".
- [x] 8.9 `tests/test_tagging.py::test_duplicate_family_is_llm_error` — covers "One entry per family".
- [x] 8.10 `tests/test_tagging.py::test_invalid_prominence_is_llm_error` — covers "Invalid prominence is an LLM error".
- [x] 8.11 `tests/test_tagging.py::test_successful_record_shape` — covers "Successful record shape".
- [x] 8.12 `tests/test_tagging.py::test_null_capability_tags_on_non_ok` — covers "Null capability_tags on non-ok status".
- [x] 8.13 `tests/test_tagging.py::test_empty_array_allowed_on_ok` — covers "Empty array allowed on ok".
- [x] 8.14 `tests/test_tagging.py::test_name_collision_refusal` — covers "Name-collision refusal".
- [x] 8.15 `tests/test_tagging.py::test_default_model` — covers "Default model".
- [x] 8.16 `tests/test_tagging.py::test_env_override` — covers "Env override".
- [x] 8.17 `tests/test_tagging.py::test_cli_end_to_end_writes_records` — covers "CLI runs the stage end-to-end".
- [x] 8.18 `tests/test_tagging.py::test_dry_run_writes_nothing` — covers "Dry-run writes nothing".
- [x] 8.19 `tests/test_tagging.py::test_offline_skips_llm` — covers "Offline skips LLM".

## 9. Tests — `dataset-output` delta

- [x] 9.1 `tests/dataset_output/test_capability_tags_projection.py::test_capability_tags_pass_through_verbatim` — covers dataset-output spec "Capability tags pass through verbatim".
- [x] 9.2 `tests/dataset_output/test_capability_tags_projection.py::test_missing_tagging_nulls_block` — covers updated "Missing source nulls the whole block" behaviour for `capability_tags`.
- [x] 9.3 `tests/dataset_output/test_capability_tags_projection.py::test_empty_array_distinct_from_null` — covers "Empty capability tags array is distinct from null".
- [x] 9.4 `tests/dataset_output/test_record_status.py::test_capability_tags_alone_is_ok` — covers "Capability tags alone is ok".
- [x] 9.5 `tests/dataset_output/test_record_status.py::test_shell_company_with_no_tags_is_empty` — covers updated "Shell company is empty" including null capability_tags.

## 10. Tests — `pipeline-architecture` delta

- [x] 10.1 `tests/pipeline_architecture/test_stage_sequence.py::test_tagging_is_wave_4d` — covers updated "Stage Sequence" requirement listing `tagging` at `4d`.
- [x] 10.2 `tests/pipeline_architecture/test_stage_sequence.py::test_tagging_depends_only_on_content_summarization` — covers updated "Dossier-derived analytic stages depend only on content-summarization".
- [x] 10.3 `tests/pipeline_architecture/test_stage_sequence.py::test_tagging_is_not_a_translation_input` — covers updated "Translation fans in over text-bearing dossier-derived analytic stages only".

## 11. Validation

- [x] 11.1 Run `openspec validate add-capability-tagging-stage --strict` and confirm a clean pass.
- [x] 11.2 Run the full test suite (`pytest`) and confirm green.
