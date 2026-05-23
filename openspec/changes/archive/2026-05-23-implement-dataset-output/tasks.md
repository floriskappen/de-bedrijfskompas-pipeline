## 1. Module scaffolding

- [x] 1.1 Create `pipeline/dataset_output/__init__.py` (empty, mirrors other stages). No `llm.py` and no `frontmatter.py` — all inputs are JSON and the stage makes no model calls.
- [x] 1.2 In `pipeline/dataset_output/core.py`, import the shared `company_id` from `pipeline.website_resolution`; define source-dir constants (`data/fact-extraction`, `data/global-scoring`, `data/tagline-extraction`, `data/translation`), the output dir `data/dataset-output`, and the load-bearing vocab: `AXES = (substance, ecology, power, embeddedness, posture)`, `LOCALES = (en, nl)`.

## 2. Projection and record assembly (`core.py`)

- [x] 2.1 Implement source loaders that read each upstream `<company-id>.json` and return its parsed dict or `None` (missing/unreadable). A non-success `status` on a source is treated as "no usable output" → that block becomes `null`.
- [x] 2.2 Implement `_assemble(...)` building the record per the Field Projection requirement: root `company_id`/`name`/`website`/`address`/`scores`, and the `en`/`nl` trees (`tagline` + per-axis `reason`). Resolve `nl` values by the flat dotted key (`translations["scores.<axis>.reason"]`, `translations["tagline"]`) — never a nested traversal.
- [x] 2.3 Implement block-level null discipline: whole block `null` when its source is absent/non-success; stable keys otherwise; `nl` mirrors `en`'s axis keys with per-field nulls. Preserve null *values* inside a present `scores` block (e.g. `no_signal`).
- [x] 2.4 Implement `_status(...)`: `upstream_failed` if the fact-extraction spine file is absent/unreadable; `empty` if spine present but `address`, `scores`, and both taglines are all null; else `ok`. Do not gate status on fact-extraction's internal address status.
- [x] 2.5 Implement `process(company_id, *, out_dir, write)` returning one record, and `run(company_ids, *, out_dir, write)` yielding one record per company without aborting the batch on a per-company error (mirror the existing stage runner pattern).
- [x] 2.6 Implement `_write(...)` to `data/dataset-output/<company-id>.json` with the name-collision hard-error guard (the sole permitted raise).

## 3. CLI (`__main__.py`)

- [x] 3.1 Create `pipeline/dataset_output/__main__.py` mirroring `pipeline/tagline_extraction/__main__.py`: enumerate companies from the fact-extraction spine dir, support `--input`/`--out-dir`/`--dry-run`/`--company`/`--limit`, print a per-company status line and a final status summary. No `--offline` flag (no LLM).

## 4. Tests (`tests/test_dataset_output.py`)

Each test below covers the named spec scenario; build small on-disk fixtures across the four source dirs in a tmp path.

- [x] 4.1 `test_pure_projection_no_model_calls` — Input Sources / "No model calls": run over a fixture and assert no network is attempted (e.g. the module exposes no llm import; processing succeeds with no API key).
- [x] 4.2 `test_one_record_per_spine_file` — Company Enumeration / "One record per fact-extraction file": 3 spine files, mixed presence of other sources → exactly 3 records.
- [x] 4.3 `test_company_without_fact_extraction_skipped` — "Company absent from the spine is not emitted": a company with only a global-scoring file → no record. (Also covers the pipeline-architecture "depends only on the fact-extraction spine" scenario.)
- [x] 4.4 `test_full_record_shape` — Output Record Shape / "Fully populated record": all four sources present → non-null `address`, all five axes with `score`+`evidence`, `en`/`nl` taglines and per-axis reasons.
- [x] 4.5 `test_neutral_data_at_root_only` — "Root holds only language-neutral data": assert score numbers/`evidence`/`address` exist only at root and never inside `en`/`nl`.
- [x] 4.6 `test_nl_reason_flat_key_lookup` — Field Projection / "Dutch reason resolved by flat dotted key": translation file keyed by `"scores.substance.reason"` populates `nl.scores.substance.reason`.
- [x] 4.7 `test_missing_scoring_nulls_block` — Null Discipline / "Missing source nulls the whole block": no global-scoring file → `scores` null and each present locale tree's `scores` null, while `tagline`/`address` unaffected.
- [x] 4.8 `test_no_signal_value_preserved` — "Null value inside a present block is preserved": `power` axis `score: null`/`evidence: "no_signal"` survives with `scores` non-null.
- [x] 4.9 `test_partial_translation_mirrors_keys` — "Partial translation mirrors keys with nulls": translation has scores but no tagline → `nl` present, per-axis reasons filled, `nl.tagline` null (not omitted).
- [x] 4.10 `test_partial_company_status_ok` — Record Status / "Partial company is ok": scores+tagline but no address → `status: "ok"`, `address: null`.
- [x] 4.11 `test_shell_company_status_empty` — "Shell company is empty": spine file present, no address/scores/tagline → `status: "empty"`, all payload blocks null.
- [x] 4.12 `test_unreadable_spine_file_upstream_failed` — Record Status: an unreadable/corrupt fact-extraction file → `status: "upstream_failed"`.
- [x] 4.13 `test_excluded_content_dropped` — Excluded Content / "Internal artefacts are dropped": fact-extraction fixture with `footer_text`/`urls_attempted`/sitemap fields and upstream `model`/`status` → none appear in the record.
- [x] 4.14 `test_cli_writes_one_json_per_company` — Layout and Execution / "CLI writes one JSON per company": `run(write=True)` writes `data/dataset-output/<id>.json` per company.
- [x] 4.15 `test_dry_run_writes_nothing` — "Dry-run writes nothing": `write=False` yields records but creates no file.
- [x] 4.16 `test_company_id_collision_raises` — "Company-id collision refuses": pre-existing file with a different `name` → raises.
- [x] 4.17 `test_one_failure_does_not_abort_batch` — one company with a corrupt source still lets the rest of the batch produce records.

## 5. Verification

- [x] 5.1 Run `python -m pipeline.dataset_output --dry-run` against the existing `data/` test-set companies and eyeball a couple of records for shape correctness.
- [x] 5.2 Run the full suite (`pytest -m "not network"`) and confirm green.
