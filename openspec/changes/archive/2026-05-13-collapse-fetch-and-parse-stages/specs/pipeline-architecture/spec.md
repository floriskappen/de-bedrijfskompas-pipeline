## MODIFIED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `content-collection`
3. `content-summarization`
4. analytical stages that depend on `content-summarization` and run independently of each other (order between them is not defined): `fact-extraction`, `bullshit-scoring`, `bcorp-scoring`, and future analytical stages of the same shape (e.g. tagging, ikigai-matching)
5. `dataset-output`

A downstream stage MUST NOT run for a given company until all stages it depends on have produced output for that company.

#### Scenario: Linear stage dependency

- **WHEN** any of `content-collection`, `content-summarization`, or `dataset-output` runs for a company
- **THEN** the output of every preceding linear stage MUST already exist on disk for that company

#### Scenario: Parallel analytical stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `fact-extraction`, `bullshit-scoring`, `bcorp-scoring`, and other stage-4 analytical stages MAY run in any order or concurrently

#### Scenario: Dataset output is terminal

- **WHEN** `dataset-output` runs for a company
- **THEN** the outputs of every stage-4 analytical stage for that company MUST already exist on disk

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

- **WHEN** `fact-extraction` and `bullshit-scoring` both process company `acme-corp`
- **THEN** they write to `data/fact-extraction/acme-corp.json` and `data/bullshit-scoring/acme-corp.json` respectively, with no shared file

#### Scenario: No mixing of layouts within one stage

- **WHEN** a stage produces output for two companies
- **THEN** both companies MUST be written using the same layout (either both as single files at `data/<stage>/<id>.json`, or both as subdirectories at `data/<stage>/<id>/...`)

#### Scenario: No aggregated or per-run layouts

- **WHEN** any stage produces output
- **THEN** it MUST NOT use a JSONL file aggregating multiple companies, and MUST NOT introduce a per-run subdirectory like `data/<stage>/<run-id>/...`
