## 1. Module scaffolding

- [x] 1.1 Create `pipeline/tagline_extraction/` with `__init__.py`, `core.py`, `llm.py`, `frontmatter.py`, `__main__.py`.
- [x] 1.2 Add the versioned prompt `prompts/tagline-extraction.md`: instruct one plain-language tagline whose spine is "who pays them and for what", no jargon/marketing adjectives, one sentence (second only as a caveat for thin/contradictory dossiers), returning a JSON object `{"en": ..., "nl": ...}` with the `nl` a faithful rendering of the `en`.

## 2. Local LLM client (`llm.py`)

- [x] 2.1 Implement a self-contained OpenRouter client that returns a parsed `{en, nl}` object; strip code fences / chatty preamble before parsing; raise `LLMError` on transport failure, unparseable JSON, or missing/empty `en`/`nl`. Default to the DeepSeek model, override via `TAGLINE_EXTRACTION_MODEL`.
- [x] 2.2 Test `test_model_override_honoured` (env var selects model) → *Scenario: Model override honoured*.
- [x] 2.3 Test `test_malformed_response_is_error` (non-JSON / missing `nl` → `LLMError`) → *Scenario: Malformed response is an error*.

## 3. Frontmatter reader (`frontmatter.py`)

- [x] 3.1 Implement a small parser that reads `status`, `name`, `website` and returns the markdown body, with no YAML dependency.
- [x] 3.2 Test `test_frontmatter_parsed` (status/name/website extracted, body separated) → supports *Scenario: Dossier body is the LLM input*.

## 4. Core: input, gate, generation, status (`core.py`)

- [x] 4.1 Implement `process(meta, body, *, out_dir, write, offline)` and `run(records, ...)` batch generator, mirroring the sibling stages' shape.
- [x] 4.2 Feed only the dossier body to the LLM; read `name`/`website`/`status` from frontmatter. Test `test_dossier_body_is_llm_input` → *Scenario: Dossier body is the LLM input*.
- [x] 4.3 Gate on frontmatter `status == ok`. Test `test_non_ok_dossier_cascades` (`llm_error` dossier → `upstream_failed`, no LLM call) → *Scenario: Non-ok dossier cascades*. Test `test_ok_dossier_proceeds` → *Scenario: Ok dossier proceeds*.
- [x] 4.4 Treat a missing dossier file as `upstream_failed`. Test `test_missing_dossier_upstream_failed` → *Scenario: Missing dossier treated as upstream failure*.
- [x] 4.5 Map outcomes to `status` (`ok`/`upstream_failed`/`empty`/`llm_error`). Test `test_empty_body_recorded` (frontmatter ok, blank body → `empty`, no call) → *Scenario: Empty body recorded*. Test `test_llm_error_recorded` → *Scenario: LLM error recorded*.
- [x] 4.6 Catch per-company LLM/transport/decode errors so the batch continues. Test `test_one_llm_failure_does_not_abort_batch` → *Scenario: One LLM failure does not abort batch*.
- [x] 4.7 Test `test_prompt_loaded_from_file` (instruction text comes from `prompts/`, not a literal) → *Scenario: Prompt loaded from versioned file*.

## 5. Output writer (`core.py`)

- [x] 5.1 Write one JSON per company at `data/tagline-extraction/<company-id>.json` with `name`, `website`, `status`, `model`, `tagline`; `tagline` is `{en, nl}` strings on `ok`, else `{null, null}`; `model` null when no call was made.
- [x] 5.2 Test `test_successful_record_shape` (`ok`, non-null model, non-empty en/nl) → *Scenario: Successful record shape*.
- [x] 5.3 Test `test_null_taglines_on_non_ok` → *Scenario: Null taglines on non-ok status*.
- [x] 5.4 Refuse to overwrite a file whose stored `name` differs (raise). Test `test_name_collision_refusal` → *Scenario: Name-collision refusal*.

## 6. CLI (`__main__.py`)

- [x] 6.1 Implement `main(argv)` discovering `.md` dossiers under `data/content-summarization/`, with `--input`, `--out-dir`, `--dry-run`, `--offline`, `--company`, `--limit`; load `.env` with `override=False`.
- [x] 6.2 Test `test_cli_run_offline` (one JSON per dossier, no network) → *Scenario: CLI run*.
- [x] 6.3 Test `test_dry_run_yields_without_writing` → *Scenario: Dry-run yields without writing*.
- [x] 6.4 Test `test_offline_mode_short_circuits_llm` (offline → `status: empty`, no call) → *Scenario: Offline mode short-circuits LLM*.
- [x] 6.5 Test `test_behaviour_parity_across_modes` (dry-run record == written record) → covers Execution-Modes parity.
- [x] 6.6 Test `test_env_key_not_overridden` (exported `OPENROUTER_API_KEY` wins over `.env`) → *Scenario: Exported API key not overridden*.

## 7. Out-of-scope guard

- [x] 7.1 Test `test_no_scoring_emitted` (record carries only a tagline; no score/rating/rank keys) → *Scenario: No scoring emitted*.

## 8. Content-quality tests (network-marked, against the test-set)

- [x] 8.1 Test `test_honest_revenue_relationship_comes_through` (B2B agency dossier → tagline conveys who pays, not vague fog) → *Scenario: Honest revenue relationship comes through*.
- [x] 8.2 Test `test_bilingual_parity` (en and nl both non-empty, same meaning) → *Scenario: Bilingual parity*.
- [x] 8.3 Test `test_thin_dossier_gets_caveat` (offering-less dossier → caveat sentence) → *Scenario: Thin dossier gets a caveat sentence*.
- [x] 8.4 Test `test_no_marketing_language` (promotion-heavy dossier → no marketing adjectives) → *Scenario: No marketing language*.

## 9. Spec deltas (no code)

- [x] 9.1 On archive, the `pipeline-architecture` rename (`bullshit-scoring` → `tagline-extraction`) and Failure-Propagation requirement, and the `content-summarization` Out-of-Scope reword, fold into the canonical specs. Confirm no source file references `bullshit-scoring` (grep) — none exist today.

## 10. Verification

- [x] 10.1 Run the full suite (`pytest`, excluding `network` for the offline run) and confirm every scenario above has a passing named test.
- [x] 10.2 Run `python -m pipeline.tagline_extraction --offline` over `data/content-summarization/`, then one live `--company` run, and eyeball the `en`/`nl` taglines for Gravity, Brainial, and one thin dossier (e.g. `co-health`).
