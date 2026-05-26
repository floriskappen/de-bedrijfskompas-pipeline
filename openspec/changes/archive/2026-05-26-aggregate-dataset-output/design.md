## Context

The `dataset-output` stage currently writes one JSON file per company at `data/dataset-output/<company-id>.json`. The front-end needs to display the map and list containing all company data, so loading individual files is highly inefficient. We need to aggregate all company records into a single JSON file `data/dataset-output/companies.json`.

## Goals / Non-Goals

**Goals:**
- Write a single JSON file `data/dataset-output/companies.json` containing an array of all company records.
- Keep the internal record format identical to the current `dataset-output` schema.
- Assert and enforce uniqueness of `company_id` values in the final aggregated output.

**Non-Goals:**
- Incremental updates or database-like upserts to the shared file; a run of the stage always writes the entire collection from scratch.
- Cross-company statistical scoring or rankings in this stage.

## Decisions

**Decision 1: Batch collection and final write in `run()`**
We will gather all company records during the batch run and write the final array to `data/dataset-output/companies.json` once, rather than writing inside `process()` per company.
- *Alternative considered*: Incrementally loading, parsing, updating, and writing the shared file in `process()`.
- *Why this choice*: Incremental updates require repeated file I/O and deserialization/serialization, leading to bad performance and file contention. A final single write is clean, atomic, and efficient.

**Decision 2: Single-company `--company` CLI argument behavior**
When the CLI is called with `--company <id>`, the output file `companies.json` will be written containing only that single company's record.
- *Alternative considered*: Merging the single company's updated record into the existing `companies.json`.
- *Why this choice*: In-place merging is error-prone. Regenerating the entire pipeline is fast and deterministic, making in-place modifications unnecessary.

## Risks / Trade-offs

- [Risk] Combined JSON size grows too large. → [Mitigation] The target database is hundreds of companies, keeping the final JSON size under 1MB. If scale grows, gzip/brotli compression on the web server handles it easily.
- [Risk] Slug collisions generate duplicate company IDs. → [Mitigation] Enforce uniqueness of `company_id` at the end of aggregation and raise a hard error on duplicate IDs.
