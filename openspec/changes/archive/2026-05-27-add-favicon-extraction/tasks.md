## 1. Implement Favicon Extraction in content-collection

- [x] 1.1 Implement favicon extraction and ranking logic in `pipeline/content_collection/extract.py`.
- [x] 1.2 Update `pipeline/content_collection/core.py` to call the extraction logic, save `favicon_url` in the metadata, and default to `null` on fetch failure.
- [x] 1.3 Add unit tests in `tests/test_content_collection.py` (`test_favicon_url_ranking_and_selection` and `test_favicon_fallback_and_null_status`) to verify `Scenario: Best candidate favicon URL selected` and `Scenario: Fallback icon used`.

## 2. Implement Favicon Projection in dataset-output

- [x] 2.1 Update `pipeline/dataset_output/core.py` to project `favicon_url` from the fact-extraction payload to the root of the output record.
- [x] 2.2 Add unit tests in `tests/test_dataset_output.py` (`test_dataset_output_includes_favicon_url`) to verify `Scenario: Fully populated record` output shape.

## 3. Verification

- [x] 3.1 Run the full test suite via `pytest` to confirm all tests pass successfully.
- [x] 3.2 Execute the pipeline stages on the test-set to manually inspect the generated `companies.json` file.
