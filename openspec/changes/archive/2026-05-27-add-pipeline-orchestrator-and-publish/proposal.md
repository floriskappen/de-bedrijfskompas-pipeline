## Why

Stages run individually today via `python -m pipeline.<stage>`; there is no end-to-end entry point. Running on a real input list requires nine manual invocations in dependency order. Additionally, the terminal `companies.json` lives only on the developer's disk — the frontend cannot pull it at build time. We need both an orchestrator that drives the full pipeline from one input file and a publication step that uploads the result to a versioned, frontend-reachable location.

## What Changes

- **New `pipeline.run` orchestrator**: takes a JSON input list (same shape as `website-resolution`'s `--input`) and runs every stage in declared dependency order, sequentially. Supports `--resume` to skip companies whose stage output already exists, and `--publish` to invoke the publish stage on completion.
- **New `publish` stage**: reads `data/dataset-output/companies.json`, builds a `manifest.json` sidecar (generated-at timestamp, pipeline git sha, company count, schema version), and uploads both to a GitHub Release of the pipeline repo via the `gh` CLI. Release tag and name follow ISO 8601 UTC with `:` → `-` (e.g. `2026-05-27T14-30-00Z`).
- **`pipeline-architecture` gains**: an orchestrator entry point requirement, resume semantics, and acknowledgement that publication is a dataset-level concern that runs after the per-company stage pipeline.

## Capabilities

### New Capabilities

- `publish`: read the terminal `companies.json`, mint a manifest, and upload both as a versioned GitHub Release.

### Modified Capabilities

- `pipeline-architecture`: add the end-to-end orchestrator entry point and resume semantics.

## Impact

- **New code**: `pipeline/run.py` (orchestrator) and `pipeline/publish/` (stage module + CLI).
- **New runtime dependency**: the `gh` CLI on whichever host runs publish (no Python package added).
- **No changes to existing nine stage modules**: the orchestrator calls each stage's existing programmatic entry point.
- **Frontend (separate repo, out of scope)**: will need a fine-grained PAT to read releases from this private repo and a two-step fetch (find latest release → download named asset by id).
- **Non-goals**: intra-wave concurrency, ephemeral / tempdir runs, automatic schema-version bumping.
