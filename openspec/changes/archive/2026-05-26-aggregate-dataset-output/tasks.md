## 1. Modify dataset-output core logic (`core.py`)

- [x] 1.1 Redefine `_write(records: list[dict], *, out_dir: Path)` to serialize the list of records into `out_dir / "companies.json"`, implementing unique `company_id` checks (raising `RuntimeError` on duplicates).
- [x] 1.2 Modify `process()` to not call `_write` directly when called from `run()`, or modify its signature/logic so it only writes if called independently (using `_write([record], ...)`).
- [x] 1.3 Update `run()` to accumulate all successfully processed records, perform the duplicate `company_id` validation, and call `_write(accumulated_records, out_dir=out_dir)` at the end if `write` is True.

## 2. Update unit tests (`test_dataset_output.py`)

- [x] 2.1 Update test `test_cli_writes_one_json_per_company` (rename to `test_cli_writes_aggregated_json`) to verify that running the CLI/batch mode produces exactly `data/dataset-output/companies.json` containing the expected JSON array of all companies.
- [x] 2.2 Update test `test_company_id_collision_raises` to verify that duplicate company IDs in the list raise a `RuntimeError` (`test_company_id_collision_raises` -> covers Scenario: Company-id collision refuses).
- [x] 2.3 Ensure all existing tests in `test_dataset_output.py` pass with the single-file aggregation changes.

## 3. Verify and Validate

- [x] 3.1 Run the full test suite (`pytest`) and confirm all tests pass cleanly.
- [x] 3.2 Run the pipeline output stage on the workspace data (`python -m pipeline.dataset_output`) and inspect the generated `data/dataset-output/companies.json`.
- [x] 3.3 Validate the openspec change with `openspec validate` and `openspec validate --all`.
