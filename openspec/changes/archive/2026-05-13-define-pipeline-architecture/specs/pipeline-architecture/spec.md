## ADDED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `page-fetching`
3. `html-parsing`
4. `content-summarization`
5. analytical stages that depend on `content-summarization` and run independently of each other (order between them is not defined): `fact-extraction`, `bullshit-scoring`, `bcorp-scoring`, and future analytical stages of the same shape (e.g. tagging, ikigai-matching)
6. `dataset-output`

A downstream stage MUST NOT run for a given company until all stages it depends on have produced output for that company.

#### Scenario: Linear stage dependency

- **WHEN** any of `page-fetching`, `html-parsing`, `content-summarization`, or `dataset-output` runs for a company
- **THEN** the output of every preceding linear stage MUST already exist on disk for that company

#### Scenario: Parallel analytical stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `fact-extraction`, `bullshit-scoring`, `bcorp-scoring`, and other stage-5 analytical stages MAY run in any order or concurrently

#### Scenario: Dataset output is terminal

- **WHEN** `dataset-output` runs for a company
- **THEN** the outputs of every stage-5 analytical stage for that company MUST already exist on disk

### Requirement: Stage Seam Contract

Each stage SHALL read its input as JSON file(s) from disk and write its output as JSON file(s) to disk. Stages SHALL NOT exchange data through in-process memory, shared globals, or direct function calls into another stage.

#### Scenario: Stage reads upstream output from disk

- **WHEN** a stage begins processing a company
- **THEN** it MUST obtain its input by reading the JSON file(s) written by its upstream stage(s)

#### Scenario: Stage persists output before being considered complete

- **WHEN** a stage finishes producing a result for a company
- **THEN** the result MUST be written as a JSON file on disk before any downstream stage is allowed to consume it

#### Scenario: No in-memory handoff

- **WHEN** two stages run in the same process
- **THEN** the downstream stage MUST still read the upstream stage's output from disk rather than receiving it as a function argument or in-memory object

### Requirement: Output File Layout

Stage outputs SHALL be stored at `data/<stage>/<company-id>.json`, one file per company per stage. The `<stage>` segment MUST match the stage identifier from the Stage Sequence (e.g. `page-fetching`, `bullshit-scoring`).

#### Scenario: Stage writes a single company output

- **WHEN** the `page-fetching` stage finishes processing company `acme-corp`
- **THEN** its output is written to `data/page-fetching/acme-corp.json`

#### Scenario: Parallel analytical stages write to their own directories

- **WHEN** `fact-extraction` and `bullshit-scoring` both process company `acme-corp`
- **THEN** they write to `data/fact-extraction/acme-corp.json` and `data/bullshit-scoring/acme-corp.json` respectively, with no shared file

#### Scenario: One file per company

- **WHEN** any stage processes company `acme-corp`
- **THEN** exactly one JSON file at `data/<stage>/acme-corp.json` represents that stage's output for that company (no aggregated JSONL, no per-run subdirectories)
