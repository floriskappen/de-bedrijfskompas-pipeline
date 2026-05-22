## MODIFIED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `content-collection`
3. `fact-extraction` — extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
4. `content-summarization` — produces a faithful, de-marketed, English company dossier of variable length (driven by available substance, not a fixed size) intended as the input to the stage-5 theme-analytic stages.
5. theme-analytic stages that consume the `content-summarization` dossier and run independently of each other (order between them is not defined): `tagline-extraction`, `bcorp-scoring`, and future analytic stages of the same shape (e.g. `tagging`, `ikigai-matching`). Because the dossier is already de-marketed, these stages read it rather than the raw page text; `tagline-extraction` derives the concise plain-language company tagline from the dossier.
6. `dataset-output`

A downstream stage MUST NOT run for a given company until all stages it depends on have produced output for that company.

#### Scenario: Linear stage dependency

- **WHEN** any of `content-collection`, `content-summarization`, `fact-extraction`, any stage-5 theme-analytic stage, or `dataset-output` runs for a company
- **THEN** the output(s) of every stage it depends on MUST already exist on disk for that company

#### Scenario: Parallel theme-analytic stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `tagline-extraction`, `bcorp-scoring`, and other stage-5 theme-analytic stages MAY run in any order or concurrently

#### Scenario: Dataset output is terminal

- **WHEN** `dataset-output` runs for a company
- **THEN** the output of `fact-extraction` and the outputs of every stage-5 theme-analytic stage for that company MUST already exist on disk

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

## ADDED Requirements

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
