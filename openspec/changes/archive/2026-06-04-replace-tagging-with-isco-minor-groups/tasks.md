## 1. Tagging Vocabulary and Parser

- [x] 1.1 Replace `pipeline.tagging.llm.FAMILIES` with an ISCO-08 minor-group code vocabulary, exposed as `ISCO_MINOR_GROUPS` or equivalent, with all 130 fixed 3-digit string codes.
- [x] 1.2 Update the tagging LLM parser to require `capability_tags` entries shaped exactly as `{ "isco_code": <code>, "prominence": <enum>, "confidence": <enum> }`.
- [x] 1.3 Validate `isco_code` against the fixed vocabulary and duplicate entries by `isco_code`; cover with `test_emitted_isco_code_in_fixed_set`, `test_out_of_vocab_isco_code_is_llm_error`, and `test_duplicate_isco_code_is_llm_error`.
- [x] 1.4 Validate `prominence` and required `confidence`; cover with `test_tag_has_isco_code_prominence_confidence`, `test_invalid_prominence_is_llm_error`, and `test_invalid_confidence_is_llm_error`.
- [x] 1.5 Update null/empty/non-ok handling tests to assert the new tag shape where relevant: `test_successful_record_shape`, `test_empty_array_allowed_on_ok`, `test_null_capability_tags_on_non_ok`, and `test_name_collision_refusal`.

## 2. Tagging Prompt and Inference Rules

- [x] 2.1 Rewrite `prompts/tagging.md` to target ISCO-08 minor groups, listing the 130 codes grouped by sub-major group and asking for `isco_code`, `prominence`, and `confidence`.
- [x] 2.2 Preserve the "who does the company need to hire?" / "serving a sector is not staffing it" rule; cover with `test_serving_sector_not_staffing_sector_prompt_rule`.
- [x] 2.3 Add prompt guidance that ordinary internal admin, sales, management, finance, legal, HR, and clerical functions are omitted unless they are part of the company's actual product, service, or operating model; cover with `test_ordinary_business_functions_omitted_prompt_rule`.
- [x] 2.4 Update prompt-loading assertions in `test_prompt_loaded_from_file` to check for `isco_code`, `confidence`, and representative ISCO codes such as `251`, `532`, and `833`.

## 3. Dataset Output Projection

- [x] 3.1 Keep dataset-output projection as a verbatim pass-through for tagging's `capability_tags` array; do not derive major groups, sub-major groups, UI domains, or labels.
- [x] 3.2 Update dataset-output tag fixture shapes to `{ isco_code, prominence, confidence }`.
- [x] 3.3 Cover pass-through and shape scenarios with `test_capability_tags_pass_through_verbatim`, `test_full_record_shape`, `test_neutral_data_at_root_only`, and `test_capability_tags_alone_is_ok`.
- [x] 3.4 Preserve null and empty-array discipline; cover with `test_missing_tagging_nulls_block`, `test_empty_array_distinct_from_null`, and `test_shell_company_with_no_tags_is_empty`.

## 4. Architecture and Documentation Touchpoints

- [x] 4.1 Update `pipeline/tagging/__init__.py` and code docstrings that describe the old 19-family slug vocabulary.
- [x] 4.2 Ensure `pipeline-architecture` behavior remains unchanged: tagging still depends only on `content-summarization` and is still not a translation input; cover with `test_tagging_is_wave_4d`, `test_tagging_depends_only_on_content_summarization`, and `test_tagging_is_not_a_translation_input`.
- [x] 4.3 Preserve orchestrator and dependency scenarios with existing tests: `test_run_end_to_end_on_test_set`, `test_run_calls_stages_in_process`, `test_run_completes_stage_before_next`, `test_run_resume_skips_completed_pairs`, `test_run_resume_still_runs_missing_stages`, `test_run_default_reprocesses_everything`, `test_run_subdirectory_stage_existence`, and `test_run_dossier_stage_existence`.

## 5. Verification

- [x] 5.1 Run focused tests for tagging, dataset output, pipeline architecture, and orchestration: `pytest tests/test_tagging.py tests/test_dataset_output.py tests/dataset_output tests/pipeline_architecture tests/test_run.py`.
- [x] 5.2 Run `openspec validate replace-tagging-with-isco-minor-groups --strict`.
