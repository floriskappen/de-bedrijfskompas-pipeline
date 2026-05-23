## 1. Module scaffolding

- [x] 1.1 Create `pipeline/global_scoring/` with `__init__.py`, `core.py`, `llm.py`, `frontmatter.py`, `__main__.py` (mirroring `tagline_extraction`).
- [x] 1.2 Add the versioned prompt `prompts/global-scoring.md`: transcribe the five axis definitions, readability ordering, and per-axis silence rules from `docs/GLOBAL_SCORING_FRAMEWORK.md`; instruct a 0–100 score (or `no_signal`/null) + `evidence` level + `reason` per axis; mandate writing each `reason.en` first then translating to `reason.nl`; forbid any composite score and any quoting of source text; return a JSON object keyed by the five axes.

## 2. Local LLM client (`llm.py`)

- [x] 2.1 Implement a self-contained OpenRouter client that returns a validated five-axis object; strip code fences / chatty preamble before parsing; default to the DeepSeek v4 Flash model, override via `GLOBAL_SCORING_MODEL`, low temperature.
- [x] 2.2 Validate the parsed object: all five axis keys (`substance`, `ecology`, `power`, `embeddedness`, `posture`) present; each `score` an int 0–100 or `null`; each `evidence` in `{well_evidenced, partial, no_signal}`; each `reason.en`/`reason.nl` a non-empty string; `score: null` iff `evidence: no_signal`. Raise `LLMError` on transport failure, unparseable JSON, or any validation failure.
- [x] 2.3 Test `test_model_override_honoured` (env var selects model) → *Scenario: Model override honoured*.
- [x] 2.4 Test `test_malformed_response_is_error` (non-JSON / missing axis / bad evidence value → `LLMError`) → *Scenario: Malformed response is an error*.
- [x] 2.5 Test `test_inconsistent_score_evidence_normalized` (numeric score with `no_signal` → kept as `partial`; null score with `partial` → forced `no_signal`; company not discarded) → *Scenario: Inconsistent score and evidence are normalized, not rejected*.

## 3. Frontmatter reader (`frontmatter.py`)

- [x] 3.1 Implement a small parser that reads `status`, `name`, `website` and returns the markdown body, with no YAML dependency.
- [x] 3.2 Test `test_frontmatter_parsed` (status/name/website extracted, body separated) → supports *Scenario: Dossier body is the LLM input*.

## 4. Core: input, gate, generation, status (`core.py`)

- [x] 4.1 Implement `process(meta, body, *, out_dir, write, offline)` and `run(records, ...)` batch generator, mirroring the sibling stages' shape.
- [x] 4.2 Feed only the dossier body to the LLM; read `name`/`website`/`status` from frontmatter. Test `test_dossier_body_is_llm_input` → *Scenario: Dossier body is the LLM input*.
- [x] 4.3 Gate on frontmatter `status == ok`. Test `test_non_ok_dossier_cascades` (`llm_error` dossier → `upstream_failed`, no LLM call, `scores: null`) → *Scenario: Non-ok dossier cascades*. Test `test_ok_dossier_proceeds` → *Scenario: Ok dossier proceeds*.
- [x] 4.4 Treat a missing dossier file as `upstream_failed`. Test `test_missing_dossier_upstream_failed` → *Scenario: Missing dossier treated as upstream failure*.
- [x] 4.5 Map outcomes to `status` (`ok`/`upstream_failed`/`empty`/`llm_error`). Test `test_empty_body_recorded` (frontmatter ok, blank body → `empty`, no call) → *Scenario: Empty body recorded*. Test `test_llm_error_recorded` → *Scenario: LLM error recorded*.
- [x] 4.6 Catch per-company LLM/transport/decode errors so the batch continues. Test `test_one_llm_failure_does_not_abort_batch` → *Scenario: One LLM failure does not abort batch*.
- [x] 4.7 Test `test_prompt_loaded_from_file` (instruction text comes from `prompts/`, not a literal) → *Scenario: Prompt loaded from versioned file*.

## 5. Output writer (`core.py`)

- [x] 5.1 Write one JSON per company at `data/global-scoring/<company-id>.json` with `name`, `website`, `status`, `model`, `scores`; `scores` is the five-axis object on `ok`, else `null`; `model` null when no call was made.
- [x] 5.2 Test `test_successful_record_shape` (`ok`, non-null model, all five axis entries) → *Scenario: Successful record shape*.
- [x] 5.3 Test `test_all_five_axes_present` (mocked ok response → `scores` keys are exactly the five axes) → *Scenario: All five axes present*.
- [x] 5.4 Test `test_no_composite_score` (record has no overall/total/average/weighted key) → *Scenario: No composite score*.
- [x] 5.5 Test `test_null_scores_on_non_ok` → *Scenario: Null scores on non-ok status*.
- [x] 5.6 Refuse to overwrite a file whose stored `name` differs (raise). Test `test_name_collision_refusal` → *Scenario: Name-collision refusal*.

## 6. Per-axis entry shape (mocked-response unit tests)

- [x] 6.1 Test `test_evidenced_axis_has_numeric_score` (well_evidenced/partial axis → int 0–100 + non-empty bilingual reason) → *Scenario: Evidenced axis carries a numeric score*.
- [x] 6.2 Test `test_no_signal_axis_has_null_score` (no_signal axis → `score: null`, reason still explains in en/nl) → *Scenario: No-signal axis carries a null score*.

## 7. CLI (`__main__.py`)

- [x] 7.1 Implement `main(argv)` discovering `.md` dossiers under `data/content-summarization/`, with `--input`, `--out-dir`, `--dry-run`, `--offline`, `--company`, `--limit`; load `.env` with `override=False`.
- [x] 7.2 Test `test_cli_run_offline` (one JSON per dossier, no network) → *Scenario: CLI run*.
- [x] 7.3 Test `test_dry_run_yields_without_writing` → *Scenario: Dry-run yields without writing*.
- [x] 7.4 Test `test_offline_mode_short_circuits_llm` (offline → `status: empty`, no call) → *Scenario: Offline mode short-circuits LLM*.
- [x] 7.5 Test `test_behaviour_parity_across_modes` (dry-run record == written record) → covers Execution-Modes parity.
- [x] 7.6 Test `test_env_key_not_overridden` (exported `OPENROUTER_API_KEY` wins over `.env`) → *Scenario: Exported API key not overridden*.

## 8. Out-of-scope guard

- [x] 8.1 Test `test_only_five_axis_profile_emitted` (record carries the five axes only; no tagline/tags/match/composite keys) → *Scenario: Only the five-axis profile emitted*.

## 9. Content-quality tests (network-marked, against the test-set)

- [x] 9.1 Test `test_power_silence_is_unknown` (dossier with no ownership/governance detail → `power` is `no_signal`/`null`, not a low number) → *Scenario: Power silence is unknown, not penalised*.
- [x] 9.2 Test `test_substance_vagueness_counts_against` (dossier that never says concretely what the company does → low numeric `substance`, not `no_signal`) → *Scenario: Substance vagueness counts against*.
- [x] 9.3 Test `test_reason_explains_rather_than_quotes` (reasons contain no verbatim dossier/website quotation) → *Scenario: Reason explains rather than quotes*.
- [x] 9.4 Test `test_bilingual_parity` (each axis `reason.en` and `reason.nl` non-empty, same meaning) → *Scenario: Bilingual parity*.

## 10. Spec deltas (no code)

- [x] 10.1 On archive, the `pipeline-architecture` rename (`bcorp-scoring` → `global-scoring`) folds into the canonical spec. Confirm no source file references `bcorp-scoring` (grep) — only the spec does today.

## 11. Verification & prompt iteration

- [x] 11.1 Run the full suite (`pytest`, excluding `network` for the offline run) and confirm every scenario above has a passing named test.
- [x] 11.2 Run `python -m pipeline.global_scoring --offline` over `data/content-summarization/`, then live `--company` runs against the test set; eyeball scores + bilingual reasons for a known-strong company (Land Life), a money-first one (Gravity), and a thin dossier (e.g. `co-health`). Iterate `prompts/global-scoring.md` against the test-set notes until the axis scores and silence handling read sensibly before scaling.
