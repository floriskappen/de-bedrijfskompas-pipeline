## Context

The pipeline today is nine self-contained stages, each callable as `python -m pipeline.<stage>`. There is no orchestrator and no hosted output. To move past the per-stage development phase and start running real input lists, we need both — and they sit naturally as one change because the orchestrator is what calls publish at the end.

The `pipeline-architecture` capability already mandates: file-on-disk seams between stages, an "orchestrator-callable" programmatic entry point per stage, failure-as-record (no exceptions, no missing files for failed companies), and per-company gating on declared dependencies. The orchestrator inherits these — it does not relax them.

## Goals / Non-Goals

**Goals:**
- One command that runs the full pipeline from an input list to `data/dataset-output/companies.json`.
- A hosted, versioned output the frontend can fetch at build time.
- Resumability after a transient failure mid-run, without re-doing completed companies.

**Non-Goals:**
- Intra-wave concurrency (the architecture spec permits it; we do not take it yet).
- Ephemeral / tempdir runs that leave no intermediates on disk.
- Distribution across machines or any kind of work-queue model.
- Automatic schema-version inference from the record shape.

## Decisions

### Decision 1: Sequential execution, one stage at a time
- **Choice**: The orchestrator runs every stage to completion across all companies before moving to the next stage, in the dependency order declared in `pipeline-architecture`.
- **Alternatives**: Streaming companies through stages as a DAG; intra-wave concurrency.
- **Rationale**: Simplest mental and operational model. LLM and HTTP rate-limiting concerns concentrate at one stage at a time. Concurrency is a clean future change once we have observed the real bottlenecks.

### Decision 2: `--resume` is implemented in the orchestrator, not in each stage
- **Choice**: Before calling a stage's entry point for a given company, the orchestrator checks whether the stage's declared output already exists for that company; if so, it skips. Per-stage CLI semantics (overwrite by default) are unchanged.
- **Alternatives**: Thread a `resume` flag through each stage's `process()`.
- **Rationale**: Keeps resume logic in one place. Avoids touching the nine existing stage modules. Each stage's output layout (single file vs. subdirectory) is encoded in a small orchestrator-side dict, not duplicated across stages.

### Decision 3: Persistent `./data/` only — no `--ephemeral` mode
- **Choice**: Intermediates are always written to `./data/<stage>/...` per the existing on-disk seam. There is no in-memory or tempdir mode.
- **Alternatives**: An `--ephemeral` mode that runs the pipeline against a tempdir and cleans up.
- **Rationale**: Cross-run resumability (the killer feature for multi-hour runs that hit a transient LLM error) requires persistence. The architectural seam stays intact. Disk usage is acceptable at the scale we expect (low MB per company).

### Decision 4: Publish is its own stage, not a flag on `dataset-output`
- **Choice**: A new `pipeline.publish` module reads `data/dataset-output/companies.json` and uploads. The orchestrator's `--publish` flag invokes it as a final step.
- **Alternatives**: Bake upload into `dataset-output`.
- **Rationale**: Decouples "produce the dataset" from "ship the dataset". Re-publish without re-running the pipeline; run the pipeline locally without ever touching auth or the network. Keeps `dataset-output` testable in isolation.

### Decision 5: GitHub Releases as the hosting target
- **Choice**: Each publish creates a Release on this pipeline repo, with `companies.json` and `manifest.json` as assets. Upload via `gh release create`.
- **Alternatives**: Object store (R2/S3/B2); committing the JSON into the frontend repo.
- **Rationale**: Free, no extra infrastructure, built-in version history, atomic publish via release creation. The pipeline repo is private; the frontend will use a fine-grained PAT to read. When/if the repo flips public, the frontend can simplify to anonymous fetches — forward-compatible.

### Decision 6: Tag format = ISO 8601 UTC with `:` → `-`
- **Choice**: Release tag and name are `YYYY-MM-DDTHH-MM-SSZ` (e.g. `2026-05-27T14-30-00Z`), generated at publish time. Asset filenames are the fixed names `companies.json` and `manifest.json`.
- **Alternatives**: Semver-ish (`v2026.05.27-1430`); monotonic run numbers.
- **Rationale**: Lexicographically sortable, unambiguous, encodes "when" in the name itself. Fixed asset filenames simplify the frontend's fetch logic.

### Decision 7: Manifest carries metadata, dataset stays pure
- **Choice**: `manifest.json` holds `generated_at`, `pipeline_git_sha`, `company_count`, `schema_version` (constant, initially `1`). `companies.json` is unchanged — only the records.
- **Alternatives**: Embed metadata at the root of `companies.json`.
- **Rationale**: Keeps the data file's shape stable and matched to the `dataset-output` spec. The frontend reads the manifest first to display "data as of …" and to refuse incompatible schema versions.

### Decision 8: Publish failure exits non-zero; data stays in place
- **Choice**: If publish fails (no `gh`, auth, network), the orchestrator exits non-zero. `data/dataset-output/companies.json` is left intact, and the user retries via `python -m pipeline.publish` standalone.
- **Alternatives**: Best-effort / log-and-exit-zero; or treat publish as required for run success.
- **Rationale**: The expensive work (the pipeline run) has already succeeded; publish is cheap to retry. Loud exit-code is right for CI but not destructive.

## Risks / Trade-offs

- **[Risk]** Sequential execution will be slow on large input lists (one stage finishes for every company before the next stage starts).
  - **Mitigation**: Accepted for v1; intra-wave concurrency is a clean follow-up change.
- **[Risk]** Two pipeline runs in the same UTC second would collide on tag name.
  - **Mitigation**: Accepted; second-level granularity is more than enough for the expected publish cadence.
- **[Risk]** `schema_version` is manual and easy to forget when the dataset-output record shape changes.
  - **Mitigation**: Document the bump-on-shape-change rule in the publish spec; consider a follow-up change for automatic detection if it bites.
- **[Risk]** Per-stage output-existence check in `--resume` could go stale if a stage's output layout changes.
  - **Mitigation**: Centralize the per-stage existence rule in one orchestrator-side helper; covered by tests.
