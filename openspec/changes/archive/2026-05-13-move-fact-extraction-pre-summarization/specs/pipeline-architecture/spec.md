## MODIFIED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `content-collection`
3. `fact-extraction` — extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
4. `content-summarization` — produces a compact prose summary intended as input to the stage-5 theme-analytic stages.
5. theme-analytic stages that depend on `content-summarization` and run independently of each other (order between them is not defined): `bullshit-scoring`, `bcorp-scoring`, and future analytic stages of the same shape (e.g. `tagging`, `ikigai-matching`).
6. `dataset-output`

A downstream stage MUST NOT run for a given company until all stages it depends on have produced output for that company.

#### Scenario: Linear stage dependency

- **WHEN** any of `content-collection`, `content-summarization`, `fact-extraction`, any stage-5 theme-analytic stage, or `dataset-output` runs for a company
- **THEN** the output(s) of every stage it depends on MUST already exist on disk for that company

#### Scenario: Parallel theme-analytic stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `bullshit-scoring`, `bcorp-scoring`, and other stage-5 theme-analytic stages MAY run in any order or concurrently

#### Scenario: Dataset output is terminal

- **WHEN** `dataset-output` runs for a company
- **THEN** the output of `fact-extraction` and the outputs of every stage-5 theme-analytic stage for that company MUST already exist on disk
