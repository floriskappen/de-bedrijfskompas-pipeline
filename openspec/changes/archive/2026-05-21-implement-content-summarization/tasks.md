## 1. Package Scaffold

- [x] 1.1 Create `pipeline/content_summarization/` package with `__init__.py`, `__main__.py`, `core.py`, `llm.py`
- [x] 1.2 Create `prompts/` directory and add the versioned dossier prompt file `prompts/content-summarization.md`, loaded by name (no inline prompt strings in code)
- [x] 1.3 Add `OPENROUTER_API_KEY` loading via `python-dotenv` (`override=False`) in `__main__.py`; expose `CONTENT_SUMMARIZATION_MODEL` env var defaulting to `deepseek/deepseek-v4-flash`
- [x] 1.4 Ensure `data/content-summarization/` output directory exists (gitignore entry if needed)

## 2. Input Assembly (pure functions in `core.py`)

- [x] 2.1 Implement company-input loader: read `_meta.json` (`name`, `website`, `status`) plus precision `<slug>.md` pages from `data/content-collection/<id>/`; exclude `<slug>.recall.md` — covers `test_recall_files_excluded`
- [x] 2.2 Implement deterministic page ordering: `index` first, then remaining slugs alphabetically, each body prefixed with its slug — covers `test_deterministic_page_order`
- [x] 2.3 Implement 24000-char truncation of the concatenated input before the LLM call — covers `test_oversized_input_truncated`
- [x] 2.4 Implement source-language detection for the `source_language` frontmatter field

## 3. LLM Client and Prompt Loading

- [x] 3.1 Implement thin `httpx`-based OpenRouter client in `llm.py`: POST to chat completions, configurable model, low temperature (~0.2), retry up to 2 times on transport failure, raise `LLMError` after retries
- [x] 3.2 Load the dossier prompt from `prompts/content-summarization.md` by name — covers `test_prompt_loaded_from_file`
- [x] 3.3 Honour the `CONTENT_SUMMARIZATION_MODEL` override over the DeepSeek default — covers `test_model_override_honoured`
- [x] 3.4 Strip conversational preamble/epilogue and surrounding markdown code fences from model output before persisting — covers `test_conversational_wrapper_stripped`
- [x] 3.5 Author the prompt content: variable length, two-directional faithfulness (no external facts; reject placeholder/template/sample/listing noise), English normalization, dedup, claim-vs-fact attribution, dynamic per-company structure

## 4. Core Resolution and Output (`core.py`)

- [x] 4.1 Implement `process(meta, pages, *, out_dir, write, offline=False) -> dict`: assembles input, calls the LLM, builds the frontmatter + body, sets `status`, returns the output record
- [x] 4.2 Handle `upstream_failed` / `fetch_failed` input: emit `status: upstream_failed`, empty body, no LLM call — covers `test_upstream_failure_propagated`
- [x] 4.3 Handle no-usable-content case: `status: empty`, empty body, no LLM call — covers `test_empty_when_no_content`
- [x] 4.4 Handle LLM failure: catch `LLMError` after retries, emit `status: llm_error`, empty body, continue batch — covers `test_llm_error_recorded`, `test_one_llm_failure_does_not_abort_batch`
- [x] 4.5 Implement `ok` path: write YAML frontmatter (`name`, `website`, `status`, `source_language`, `model`) + dossier body to `data/content-summarization/<id>.md` — covers `test_dossier_written_with_frontmatter`
- [x] 4.6 Implement name-collision guard: refuse to overwrite `<id>.md` if stored frontmatter `name` differs from current record — covers `test_name_collision_refusal`
- [x] 4.7 Implement `offline` mode: skip LLM entirely; companies that would need it get `status: empty` — covers `test_offline_mode_short_circuits_llm`
- [x] 4.8 Implement `run(records, *, write, out_dir, offline=False) -> Iterator[dict]`: orchestrator-callable batch runner; `write=False` is dry-run — covers `test_dry_run_yields_without_writing`, `test_behaviour_parity_across_modes`

## 5. CLI Entry Point (`__main__.py`)

- [x] 5.1 Implement `python -m pipeline.content_summarization`: discover all company dirs in `data/content-collection/`, call `run`, write to `data/content-summarization/`, print summary — covers `test_cli_run_offline`
- [x] 5.2 Add `--dry-run` (suppress writes) and `--offline` (suppress LLM) flags
- [x] 5.3 Add `--company <id>` flag to process a single company for spot-checking

## 6. Tests — Offline plumbing (`tests/test_content_summarization.py`)

- [x] 6.1 `test_recall_files_excluded`: dir with `about.md` + `about.recall.md` → only `about.md` contributes
- [x] 6.2 `test_deterministic_page_order`: `portfolio`/`index`/`about` → input ordered `index`, `about`, `portfolio`, each slug-prefixed
- [x] 6.3 `test_oversized_input_truncated`: >24000-char input → truncated to 24000 before the (mocked) LLM call; dossier still produced
- [x] 6.4 `test_prompt_loaded_from_file`: prompt text originates from `prompts/content-summarization.md`, not a code literal
- [x] 6.5 `test_model_override_honoured`: `CONTENT_SUMMARIZATION_MODEL` set → that model id is sent to the client
- [x] 6.6 `test_conversational_wrapper_stripped`: mocked LLM returns body wrapped in a ` ```markdown ` fence and a "Here is..." preamble → only the body is written
- [x] 6.7 `test_dossier_written_with_frontmatter`: success → `<id>.md` opens with YAML frontmatter containing `name`, `website`, `status`, `source_language`, `model`
- [x] 6.8 `test_name_collision_refusal`: existing `<id>.md` with different frontmatter `name` → raises
- [x] 6.9 `test_upstream_failure_propagated`: `_meta.json.status: upstream_failed` → `status: upstream_failed`, empty body, no LLM call
- [x] 6.10 `test_empty_when_no_content`: status `ok` but no precision pages → `status: empty`, no LLM call
- [x] 6.11 `test_llm_error_recorded`: mocked LLM raises after retries → `status: llm_error`, empty body
- [x] 6.12 `test_one_llm_failure_does_not_abort_batch`: second company's LLM fails → first and third still produced
- [x] 6.13 `test_offline_mode_short_circuits_llm`: offline flag → no LLM calls; companies needing one get `status: empty`
- [x] 6.14 `test_dry_run_yields_without_writing`: dry-run → records yielded, no files on disk
- [x] 6.15 `test_behaviour_parity_across_modes`: same input in CLI, orchestrator, dry-run → identical output record
- [x] 6.16 `test_env_key_not_overridden`: exported `OPENROUTER_API_KEY` + differing `.env` value → exported value used
- [x] 6.17 `test_detect_language_dutch_vs_english`: Dutch-dominant text → `nl`, English text → `en` (deterministic, offline)

## 7. Tests — Network / quality eval (`@pytest.mark.network`)

These assert dossier *content* against the real LLM on real `content-collection/` output; gated by `OPENROUTER_API_KEY`. Deterministic where possible (language detection), LLM-as-judge or proxy heuristics for the rest.

- [x] 7.1 `test_source_language_normalised`: dossier for a Dutch-source company is detected as English; `source_language` records the source — Dossier Content "Source language normalised"
- [x] 7.2 `test_marketing_collapsed_to_substance`: a marketing-heavy company yields a short dossier stating plain substance, no padded marketing — Dossier Content "Marketing collapsed to substance"
- [x] 7.3 `test_cross_page_duplication_removed`: a company with content repeated across pages → information stated once — Dossier Content "Cross-page duplication removed"
- [x] 7.4 `test_no_external_facts_and_claims_attributed`: an aspirational mission claim is recorded as a stated claim, not asserted fact, and a fact absent from source (e.g. founding year) is not supplied — Dossier Content "Claim attributed, not asserted" + Faithfulness "No external facts added"
- [x] 7.5 `test_filler_and_sample_data_excluded`: placeholder/unrelated-template pages and sample/mockup data → none of it appears in or is treated as the company's own info — Faithfulness "Filler and unrelated template excluded" + "Sample data not treated as fact"
- [x] 7.7 `test_bulk_listing_not_reproduced`: a listing-heavy company → dossier conveys the offering without reproducing the listing — Faithfulness "Bulk listing not reproduced"
- [x] 7.9 `test_no_scoring_emitted`: marketing-heavy source → de-marketed dossier with no score/rating — Out of Scope "No scoring emitted"
- [x] 7.10 `test_end_to_end_corpus`: run against `test-set/companies.json` and `companies-medium.json` — every company produces a `data/content-summarization/<id>.md`, no unhandled exceptions; spot-check dossiers align with the test-set `notes` ground truth (Land Life reads mission-driven; Gravity reads money-first)
- [x] 7.11 `test_cli_run_offline`: `python -m pipeline.content_summarization --offline` over populated `data/content-collection/` exercises CLI discovery end to end (offline, no LLM)
