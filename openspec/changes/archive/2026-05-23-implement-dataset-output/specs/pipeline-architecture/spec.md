## MODIFIED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages, executed in order:

1. `website-resolution`
2. `content-collection`
3. `fact-extraction` — extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
4. `content-summarization` — produces a faithful, de-marketed, English company dossier of variable length (driven by available substance, not a fixed size) intended as the input to the stage-5 theme-analytic stages.
5. theme-analytic stages that consume the `content-summarization` dossier and run independently of each other (order between them is not defined): `tagline-extraction`, `global-scoring`, and future analytic stages of the same shape (e.g. `tagging`, `ikigai-matching`). These stages produce English-only output; `tagline-extraction` derives the concise plain-language company tagline from the dossier.
6. `translation` — a fan-in stage that reads the English outputs of the stage-5 analytic stages and produces the Dutch (`nl`) for all registered translatable fields, in one batched call per company.
7. `dataset-output` — the terminal fan-in stage that projects the per-stage outputs into one frontend-facing record per company.

A downstream stage MUST NOT run for a given company until the stages it depends on have produced output for that company. Each stage's dependencies are as given by the scenarios below; `dataset-output` is a fan-in stage whose only hard dependency is `fact-extraction` (its enumeration spine), joining the stage-5 analytic outputs and `translation` when present rather than requiring them.

#### Scenario: Linear stage dependency

- **WHEN** any of `content-collection`, `content-summarization`, `fact-extraction`, any stage-5 theme-analytic stage, or `translation` runs for a company
- **THEN** the output(s) of every stage it depends on MUST already exist on disk for that company

#### Scenario: Parallel theme-analytic stages

- **WHEN** `content-summarization` output exists for a company
- **THEN** `tagline-extraction`, `global-scoring`, and other stage-5 theme-analytic stages MAY run in any order or concurrently

#### Scenario: Translation runs after all analytic stages

- **WHEN** `translation` runs for a company
- **THEN** the outputs of all stage-5 theme-analytic stages for that company MUST already exist on disk

#### Scenario: Dataset output depends only on the fact-extraction spine

- **WHEN** `dataset-output` runs for a company
- **THEN** a `fact-extraction` output for that company MUST already exist on disk, and `dataset-output` MUST NOT require the stage-5 analytic stages or `translation` to exist — it joins them when present and treats them as absent (null) when not
