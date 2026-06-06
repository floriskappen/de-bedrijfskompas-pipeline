## Why

The output `companies.json` has no notion of when a company record first appeared or when it last changed. The frontend cannot show "new" or "recently updated" companies, and we have no way to detect record churn over time.

## What Changes

- Add `created_at` and `updated_at` (ISO 8601 UTC, second precision) to each record in `data/dataset-output/companies.json`.
- `created_at` is set once, the first time a company appears in the output, and is preserved on subsequent runs.
- `updated_at` is refreshed whenever the record's content (excluding the timestamps themselves) differs from the previously emitted record for that company.
- Persist per-company timestamps in a sidecar under `data/dataset-output/` so the lifecycle survives across pipeline runs.

## Capabilities

### Modified Capabilities
- `dataset-output`: output record shape gains `created_at` / `updated_at`, and the stage gains a persistence requirement for tracking record lifecycle across runs.

## Impact

- `dataset-output` stage: new sidecar read/write, new fields in each record, content-equality check to decide whether to bump `updated_at`.
- `publish` stage: no behavior change, but consumers of `companies.json` (frontend) gain two new fields per record.
- `schema_version` in `publish` manifest should bump (record shape changes).
