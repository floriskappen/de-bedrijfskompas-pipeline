# pipeline-architecture Specification

## Purpose
Specify the overall architecture of the offline batch pipeline: its stage sequence, the on-disk seam between stages, the output file layout, the per-stage execution modes, and how failures propagate downstream.
## Requirements
### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `content-collection`
3. `fact-extraction` — extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
4. `content-summarization` — produces a faithful, de-marketed, English company dossier of variable length (driven by available substance, not a fixed size) intended as the input to the stage-5 theme-analytic stages.
5. theme-analytic stages that consume the `content-summarization` dossier and run independently of each other (order between them is not defined): `tagline-extraction`, `global-scoring`, and future analytic stages of the same shape (e.g. `tagging`, `ikigai-matching`). These stages produce English-only output; `tagline-extraction` derives the concise plain-language company tagline from the dossier.
6. `translation` — a fan-in stage that reads the English outputs of the stage-5 analytic stages and produces the Dutch (`nl`) for all registered translatable fields, in one batched call per company.
7. `dataset-output`

A downstream stage MUST NOT run for a given company until all stages it depends on have produced output for that company.

#### Scenario: Linear stage dependency

- **WHEN** any of `content-collection`, `content-summarization`, `fact-extraction`, any stage-5 theme-analytic stage, `translation`, or `dataset-output` runs for a company
- **THEN** the output(s) of every stage it depends on MUST already exist on disk for that company

#### Scenario: Parallel theme-analytic stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `tagline-extraction`, `global-scoring`, and other stage-5 theme-analytic stages MAY run in any order or concurrently

#### Scenario: Translation runs after all analytic stages

- **WHEN** `translation` runs for a company
- **THEN** the outputs of all stage-5 theme-analytic stages for that company MUST already exist on disk

#### Scenario: Dataset output is terminal

- **WHEN** `dataset-output` runs for a company
- **THEN** the outputs of `fact-extraction`, every stage-5 theme-analytic stage, and `translation` for that company MUST already exist on disk

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

