## 1. Implement Orchestrator

- [x] 1.1 Create `pipeline/run.py` exposing `python -m pipeline.run` with `--input`, `--resume`, `--publish` flags.
- [x] 1.2 Implement sequential stage-by-stage driver: for each stage in dependency order, iterate companies in input order and call the stage's programmatic entry point in-process (no subprocess).
- [x] 1.3 Implement per-stage output-existence helper (single-file vs `<id>/_meta.json` for subdirectory stages) and gate `--resume` on it.
- [x] 1.4 Invoke `pipeline.publish` after `dataset-output` when `--publish` is set; surface publish failure as a non-zero exit from the orchestrator.

## 2. Implement Publish Stage

- [x] 2.1 Create `pipeline/publish/` module with `core.py` (manifest build, tag derivation, gh invocation) and `__main__.py` (CLI with `--dry-run`).
- [x] 2.2 Read `data/dataset-output/companies.json`; exit non-zero with a clear error if missing or malformed.
- [x] 2.3 Build `manifest.json` with `generated_at` (ISO 8601 UTC, second precision), `pipeline_git_sha` (from `git rev-parse HEAD`), `company_count`, `schema_version` (constant `1`).
- [x] 2.4 Derive tag from `generated_at` (replace `:` with `-`) and call `gh release create <tag> companies.json manifest.json --title <tag> --notes <summary>`.
- [x] 2.5 Detect missing `gh`, unauthenticated `gh`, and tag-collision failure modes and exit non-zero in each.
- [x] 2.6 Implement `--dry-run` that prints the intended tag and manifest body to stdout, performs no upload, writes no files.

## 3. Tests — Orchestrator

- [x] 3.1 `test_run_end_to_end_on_test_set` — orchestrator drives all stages over `test-set/companies.json` (covers Scenario: End-to-end run).
- [x] 3.2 `test_run_calls_stages_in_process` — assert no subprocess is spawned (e.g. monkeypatch `subprocess.run` / `Popen` to raise) (covers Scenario: Programmatic, not subprocess).
- [x] 3.3 `test_run_completes_stage_before_next` — observe stage call order on a small input (covers Scenario: Stage ordering).
- [x] 3.4 `test_run_resume_skips_completed_pairs` — pre-populate `data/fact-extraction/<id>.json`, run with `--resume`, assert fact-extraction entry point is not called for that id (covers Scenario: Resume skips completed pairs).
- [x] 3.5 `test_run_resume_still_runs_missing_stages` — `fact-extraction` present, `geocoding` absent; `--resume` skips the first and invokes the second (covers Scenario: Resume still calls stages whose output is missing).
- [x] 3.6 `test_run_default_reprocesses_everything` — pre-populate outputs; without `--resume`, every stage is invoked (covers Scenario: Default mode reprocesses everything).
- [x] 3.7 `test_run_subdirectory_stage_existence` — for `content-collection`, existence is keyed on `<id>/_meta.json` not `<id>.json` (covers Scenario: Subdirectory-stage existence).
- [x] 3.8 `test_run_publish_on_completion` — with `--publish`, orchestrator invokes publish (mock the publish entry) after dataset-output (covers Scenario: Publish invoked on completion).
- [x] 3.9 `test_run_publish_failure_exits_nonzero` — publish entry raises; orchestrator returns non-zero and `data/dataset-output/companies.json` remains (covers Scenario: Publish failure exits non-zero).

## 4. Tests — Publish

- [x] 4.1 `test_publish_missing_input_exits_nonzero` — no `companies.json`; no `gh` call made (covers Scenario: Missing input).
- [x] 4.2 `test_publish_malformed_input_exits_nonzero` — invalid JSON; no `gh` call made (covers Scenario: Malformed input).
- [x] 4.3 `test_publish_manifest_shape` — frozen clock, fake git sha, asserted manifest contents (covers Scenario: Manifest matches data).
- [x] 4.4 `test_publish_release_tag_format` — frozen clock at `2026-05-27T14:30:00Z`; assert derived tag is `2026-05-27T14-30-00Z` and `gh release create` is called with the two fixed asset filenames (covers Scenario: Standard release).
- [x] 4.5 `test_publish_tag_collision_exits_nonzero` — `gh` exits non-zero with a tag-exists error; publish exits non-zero (covers Scenario: Tag collision).
- [x] 4.6 `test_publish_gh_missing_exits_nonzero` — `which gh` returns nothing; publish exits before manifest generation (covers Scenario: gh not installed).
- [x] 4.7 `test_publish_gh_unauthenticated_exits_nonzero` — `gh auth status` returns non-zero; publish exits non-zero and `companies.json` is unchanged (covers Scenario: gh not authenticated).
- [x] 4.8 `test_publish_dry_run_no_side_effects` — `--dry-run` prints tag and manifest to stdout, no `gh` calls, no files written (covers Scenario: Dry-run).
- [x] 4.9 `test_publish_standalone_invocation` — happy path under mocked `gh`; release created with two assets (covers Scenario: Standalone invocation).

## 5. Verification

- [x] 5.1 Run the full test suite via `pytest` and confirm all tests pass.
- [x] 5.2 Run `python -m pipeline.run --input test-set/companies.json` end-to-end against the test set and inspect `data/dataset-output/companies.json`.
- [x] 5.3 Run `python -m pipeline.publish --dry-run` and confirm the manifest and tag look right.
- [x] 5.4 Run a real publish against the pipeline repo and confirm the release contains `companies.json` and `manifest.json` under the expected tag.
