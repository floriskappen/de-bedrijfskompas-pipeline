## Why

The front-end needs to display the map and lists for all companies simultaneously. Querying dozens of individual company JSON files results in excessive network round-trips and increased loading latency. Consolidating all projected records into a single aggregated JSON file allows the front-end to fetch the complete dataset in one request.

## What Changes

- **BREAKING**: Modify the `dataset-output` stage to output all projected company records into a single JSON file (`data/dataset-output/companies.json`) as a JSON list, instead of writing individual per-company files under `data/dataset-output/<company-id>.json`.
- Modify CLI output to display summary of all aggregated companies.
- Update `dataset-output` unit tests to verify the single-file array output structure instead of multiple files.
- Validate that all company IDs in the final aggregated list are unique.

## Capabilities

### New Capabilities

*(None)*

### Modified Capabilities

- `dataset-output`: Update output file layout requirement to write a single array of records to `data/dataset-output/companies.json`.

## Impact

- `pipeline/dataset_output/core.py`: Modify output writer to aggregate results and write them to `data/dataset-output/companies.json`.
- `pipeline/dataset_output/__main__.py`: Modify CLI execution to aggregate and write.
- `tests/test_dataset_output.py`: Update tests to assert single file output and list contents.
