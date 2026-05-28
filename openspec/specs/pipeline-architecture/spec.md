# pipeline-architecture Specification

## Purpose
Specify the overall architecture of the offline batch pipeline: its stage sequence, the on-disk seam between stages, the output file layout, the per-stage execution modes, and how failures propagate downstream.
## Requirements
### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages. The leading integer denotes the topological wave (the longest path from `website-resolution`); a trailing letter denotes an in-wave id for stages an orchestrator MAY schedule in parallel. Per-company gating SHALL be driven by each stage's declared dependencies, not by the wave number.

1. `website-resolution` — no upstream dependencies.
2. `content-collection` — depends on `website-resolution`.
3a. `fact-extraction` — depends on `content-collection`. Extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
3b. `content-summarization` — depends on `content-collection`. Produces a faithful, de-marketed, English company dossier of variable length (driven by available substance, not a fixed size) intended as the input to the dossier-derived analytic stages.
4a. `geocoding` — depends on `fact-extraction`. Resolves the extracted address to a WGS84 lat/lng. Fact-derived.
4b. `tagline-extraction` — depends on `content-summarization`. Derives the concise plain-language company tagline from the dossier. Dossier-derived analytic.
4c. `global-scoring` — depends on `content-summarization`. Produces the five-axis structural score. Dossier-derived analytic.
4d. `tagging` — depends on `content-summarization`. Produces the capability-family tag set from the dossier. Dossier-derived analytic. Slugs only; not a translation input.
   Future analytic stages of the same shape (e.g. `ikigai-matching`) take additional wave-4 labels (`4e`, …) as dossier-derived analytics.
5. `translation` — fan-in stage that reads the English outputs of the dossier-derived analytic stages that carry translatable text (`4b`, `4c`, and any future `4x` dossier-derived stage producing translatable text) and produces Dutch (`nl`) for all registered translatable fields, in one batched call per company. `geocoding` and `tagging` are not translation inputs (geocoding has no text; tagging emits slugs).
6. `dataset-output` — terminal fan-in stage that projects per-stage outputs into one frontend-facing record per company. Its hard dependency is `fact-extraction` (its enumeration spine); it left-joins `geocoding`, the dossier-derived analytic stages, and `translation`, treating them as absent (null) when not present rather than requiring them.

A downstream stage MUST NOT run for a given company until every stage it declares as a dependency has produced output for that company.

#### Scenario: Stage gated on declared dependencies

- **WHEN** any stage runs for a company
- **THEN** the output(s) of every stage it declares as a dependency MUST already exist on disk for that company

#### Scenario: Wave-3 stages may run in parallel

- **WHEN** `content-collection` output exists for a company
- **THEN** `fact-extraction` and `content-summarization` MAY run in any order or concurrently

#### Scenario: Geocoding depends only on fact-extraction

- **WHEN** `fact-extraction` output exists for a company
- **THEN** `geocoding` MAY run; it does NOT require `content-summarization` or any wave-4 dossier-derived stage

#### Scenario: Dossier-derived analytic stages depend only on content-summarization

- **WHEN** `content-summarization` output exists for a company
- **THEN** `tagline-extraction`, `global-scoring`, `tagging`, and any other dossier-derived analytic stage MAY run in any order or concurrently; they do NOT require `fact-extraction` or `geocoding`

#### Scenario: Translation fans in over text-bearing dossier-derived analytic stages only

- **WHEN** `translation` runs for a company
- **THEN** the outputs of all text-bearing dossier-derived analytic stages (currently `4b` and `4c`) for that company MUST already exist on disk; `geocoding` and `tagging` are NOT dependencies

#### Scenario: Dataset output depends only on the fact-extraction spine

- **WHEN** `dataset-output` runs for a company
- **THEN** a `fact-extraction` output for that company MUST already exist on disk, and `dataset-output` MUST NOT require `geocoding`, the dossier-derived analytic stages, or `translation` to exist — it joins them when present and treats them as absent (null) when not

### Requirement: Stage Seam Contract

Each stage SHALL read its input as file(s) on disk and write its output as file(s) on disk, in whatever structured format the stage's contract specifies (JSON for most stages; other formats such as markdown are permitted when the stage's output is naturally human-readable content rather than structured data). Stages SHALL NOT exchange data through in-process memory, shared globals, or direct function calls into another stage. The choice of format is a per-stage decision; the no-in-memory-handoff rule is universal.

#### Scenario: Stage reads upstream output from disk

- **WHEN** a stage begins processing a company
- **THEN** it MUST obtain its input by reading the file(s) written by its upstream stage(s) from disk

#### Scenario: Stage persists output before being considered complete

- **WHEN** a stage finishes producing a result for a company
- **THEN** the result MUST be written to disk before any downstream stage is allowed to consume it

#### Scenario: No in-memory handoff

- **WHEN** two stages run in the same process
- **THEN** the downstream stage MUST still read the upstream stage's output from disk rather than receiving it as a function argument or in-memory object

#### Scenario: Format is per-stage

- **WHEN** `content-collection` produces markdown and `content-summarization` produces JSON
- **THEN** both satisfy the seam contract; the contract does not mandate a single format across stages

### Requirement: Output File Layout

Stage outputs SHALL be stored under `data/<stage>/`, where `<stage>` matches the stage identifier from the Stage Sequence. Each stage chooses one of two layouts:

1. **Single file per company** (default): `data/<stage>/<company-id>.json` — one file per company, used by stages whose output is naturally a single structured record (e.g. `website-resolution`, the analytical stages, `dataset-output`).
2. **Subdirectory per company**: `data/<stage>/<company-id>/<page-slug>.<ext>` — one *directory* per company containing one file per logical sub-artifact, used by stages whose output is naturally multi-document (e.g. `content-collection` writing one markdown file per fetched page).

A stage MUST commit to exactly one of these layouts; mixing both within the same stage is forbidden. Aggregated layouts (a single JSONL file spanning multiple companies, per-run subdirectories like `data/<stage>/<run-id>/...`) are forbidden.

#### Scenario: Single-file stage writes one JSON per company

- **WHEN** the `website-resolution` stage finishes processing company `acme-corp`
- **THEN** its output is written to `data/website-resolution/acme-corp.json` (single-file layout)

#### Scenario: Multi-document stage writes a subdirectory per company

- **WHEN** the `content-collection` stage finishes processing company `acme-corp` and has collected three pages
- **THEN** its output is `data/content-collection/acme-corp/<page-slug>.md` × 3, with no top-level `acme-corp.json` for that stage

#### Scenario: Parallel analytical stages write to their own directories

- **WHEN** `fact-extraction` and `tagline-extraction` both process company `acme-corp`
- **THEN** they write to `data/fact-extraction/acme-corp.json` and `data/tagline-extraction/acme-corp.json` respectively, with no shared file

#### Scenario: No mixing of layouts within one stage

- **WHEN** a stage produces output for two companies
- **THEN** both companies MUST be written using the same layout (either both as single files at `data/<stage>/<id>.json`, or both as subdirectories at `data/<stage>/<id>/...`)

#### Scenario: No aggregated or per-run layouts

- **WHEN** any stage produces output
- **THEN** it MUST NOT use a JSONL file aggregating multiple companies, and MUST NOT introduce a per-run subdirectory like `data/<stage>/<run-id>/...`

### Requirement: Stage Execution Model

Every pipeline stage SHALL be implemented as a self-contained Python module that supports three execution modes:

1. **Standalone CLI**: the stage MUST be runnable from the command line as `python -m <stage-module>` (or equivalent), reading its input from disk (or the configured source for stage 1) and writing its output to disk per the Output File Layout requirement.
2. **Orchestrator-callable**: the stage MUST expose a programmatic entry point (a function) that a future pipeline orchestrator can invoke without subprocess overhead. The entry point's contract MUST match the on-disk seam — same input shape in, same output shape out — so behavior does not diverge between modes.
3. **Dry-run / no-write mode**: the stage MUST support a mode in which all logic runs (search calls, transformations, etc.) but no output files are written to disk. Dry-run mode is intended for tests; it MAY return outputs in memory to the caller.

These three modes apply to every stage in the Stage Sequence requirement, including any future analytical stages added under stage 5.

#### Scenario: Stage runs standalone from CLI

- **WHEN** a developer runs `python -m pipeline.<stage>` with the stage's expected input available
- **THEN** the stage processes the input and writes outputs to `data/<stage>/<company-id>.json` per the Output File Layout

#### Scenario: Stage callable by an orchestrator

- **WHEN** an orchestrator imports the stage's module and calls its programmatic entry point with an input record
- **THEN** the stage produces the same output it would have written to disk in CLI mode

#### Scenario: Dry-run produces no files

- **WHEN** the stage is invoked in dry-run mode against a batch of inputs
- **THEN** the stage performs its normal processing logic but writes nothing to `data/<stage>/`

#### Scenario: Behavior parity across modes

- **WHEN** the same input is processed in CLI mode, orchestrator mode, and dry-run mode
- **THEN** the resulting output record is identical in all three modes (the only difference is whether/where it is persisted)

### Requirement: Failure Propagation

Every stage SHALL emit exactly one output record per company it processes, whether the company succeeded or failed. Failure SHALL be represented as a written record carrying a failure status, never as a missing output file and never as an unhandled exception (the company-id collision hard error is the sole permitted raise). This lets `dataset-output` distinguish three states: succeeded, failed-with-reason (record present, failure status), and not-yet-run (no file).

Success statuses MAY be stage-specific (e.g. `regex_single`, `llm_fallback`), but failure statuses SHALL draw from a shared vocabulary so downstream consumers interpret them uniformly:

- `upstream_failed` — a required upstream input was missing, or its status was not a success status.
- `empty` — the upstream input existed and succeeded but carried no usable substance for this stage.
- `llm_error` — for stages that call an LLM, the call failed after retries or returned an unusable response.

A stage that gates on upstream status SHALL NOT perform expensive work (network requests, LLM calls) when the upstream input is missing or non-success; it SHALL emit `upstream_failed` directly.

#### Scenario: Failure is a record, not a gap

- **WHEN** a stage cannot produce its payload for a company (upstream missing, empty input, or LLM failure)
- **THEN** it writes an output file for that company with the corresponding failure status and an empty/null payload, rather than skipping the file or raising

#### Scenario: Upstream failure cascades without expensive work

- **WHEN** a stage's required upstream input is missing or carries a non-success status
- **THEN** the stage emits `status: upstream_failed` and performs no network requests or LLM calls for that company

#### Scenario: Missing file means not-yet-run

- **WHEN** `dataset-output` finds no output file for a company under some stage's directory
- **THEN** it interprets this as the stage not having run for that company, distinct from a record present with a failure status

### Requirement: End-to-End Orchestrator

The pipeline SHALL expose a `pipeline.run` module runnable as `python -m pipeline.run --input <path>` that drives every stage in the Stage Sequence over a single input JSON array. The input shape SHALL match `website-resolution`'s input: a JSON array of records each with at least `name`. The orchestrator SHALL invoke each stage's programmatic entry point directly; it SHALL NOT spawn `python -m` subprocesses.

Within a single run, the orchestrator SHALL process stages one at a time in dependency order, running each stage to completion across all companies before invoking the next. Within a stage, companies SHALL be processed in input order.

The orchestrator SHALL accept a `--publish` flag. When set, after `dataset-output` completes successfully, the orchestrator SHALL invoke the publish stage. If publish fails, the orchestrator SHALL exit non-zero, leaving `data/dataset-output/companies.json` in place for standalone retry.

#### Scenario: End-to-end run

- **WHEN** the operator runs `python -m pipeline.run --input seed.json`
- **THEN** every stage in the declared sequence runs to completion across all companies in `seed.json`, and `data/dataset-output/companies.json` exists

#### Scenario: Programmatic, not subprocess

- **WHEN** the orchestrator runs any stage
- **THEN** it calls that stage module's entry function directly in-process; no `python -m` subprocess is spawned

#### Scenario: Stage ordering

- **WHEN** the orchestrator runs the pipeline
- **THEN** it completes `website-resolution` for every company before starting `content-collection`, completes `content-collection` for every company before starting any wave-3 stage, and so on through the declared dependency order

#### Scenario: Publish invoked on completion

- **WHEN** `python -m pipeline.run --input seed.json --publish` reaches the end of `dataset-output` successfully
- **THEN** the orchestrator invokes `pipeline.publish`

#### Scenario: Publish failure exits non-zero

- **WHEN** the publish step fails (gh missing, auth, network)
- **THEN** the orchestrator exits non-zero and `data/dataset-output/companies.json` remains on disk

### Requirement: Resume Semantics

The orchestrator SHALL accept a `--resume` flag. When set, before invoking a stage for a given company, the orchestrator SHALL check whether that stage's output already exists for that company; if so, the orchestrator SHALL skip the (stage, company) pair without calling the stage's entry point. When `--resume` is not set, the orchestrator SHALL invoke every stage for every company; each stage's own overwrite semantics apply.

Per-stage existence SHALL be determined as follows:

- Single-file JSON stages: `data/<stage>/<company-id>.json` exists.
- Subdirectory-per-company stages: `data/<stage>/<company-id>/_meta.json` exists.
- Single-file dossier stages (markdown output, e.g. `content-summarization`): `data/<stage>/<company-id>.md` exists.

#### Scenario: Resume skips completed pairs

- **WHEN** `python -m pipeline.run --input seed.json --resume` runs and `data/fact-extraction/acme.json` already exists
- **THEN** the orchestrator does not call the `fact-extraction` entry point for `acme`

#### Scenario: Resume still calls stages whose output is missing

- **WHEN** `--resume` is set and `data/geocoding/acme.json` is missing while `data/fact-extraction/acme.json` exists
- **THEN** the orchestrator skips `fact-extraction` for `acme` but invokes `geocoding` for `acme`

#### Scenario: Default mode reprocesses everything

- **WHEN** `python -m pipeline.run --input seed.json` runs (no `--resume`)
- **THEN** every stage is invoked for every company regardless of whether prior outputs exist

#### Scenario: Subdirectory-stage existence

- **WHEN** `--resume` is checking `content-collection` for company `acme`
- **THEN** the orchestrator treats the company as completed iff `data/content-collection/acme/_meta.json` exists

#### Scenario: Dossier-stage existence

- **WHEN** `--resume` is checking `content-summarization` for company `acme`
- **THEN** the orchestrator treats the company as completed iff `data/content-summarization/acme.md` exists

