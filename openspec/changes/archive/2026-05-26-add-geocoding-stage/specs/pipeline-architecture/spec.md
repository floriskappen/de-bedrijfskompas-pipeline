## MODIFIED Requirements

### Requirement: Stage Sequence

The pipeline SHALL be composed of the following stages. The leading integer denotes the topological wave (the longest path from `website-resolution`); a trailing letter denotes an in-wave id for stages an orchestrator MAY schedule in parallel. Per-company gating SHALL be driven by each stage's declared dependencies, not by the wave number.

1. `website-resolution` — no upstream dependencies.
2. `content-collection` — depends on `website-resolution`.
3a. `fact-extraction` — depends on `content-collection`. Extracts structured facts (e.g. HQ address) that require verbatim content rather than a summary.
3b. `content-summarization` — depends on `content-collection`. Produces a faithful, de-marketed, English company dossier of variable length (driven by available substance, not a fixed size) intended as the input to the dossier-derived analytic stages.
4a. `geocoding` — depends on `fact-extraction`. Resolves the extracted address to a WGS84 lat/lng. Fact-derived.
4b. `tagline-extraction` — depends on `content-summarization`. Derives the concise plain-language company tagline from the dossier. Dossier-derived analytic.
4c. `global-scoring` — depends on `content-summarization`. Produces the five-axis structural score. Dossier-derived analytic.
   Future analytic stages of the same shape (e.g. `tagging`, `ikigai-matching`) take additional wave-4 labels (`4d`, `4e`, …) as dossier-derived analytics.
5. `translation` — fan-in stage that reads the English outputs of the dossier-derived analytic stages (`4b`, `4c`, and any future `4x` dossier-derived stage) and produces Dutch (`nl`) for all registered translatable fields, in one batched call per company. `geocoding` is not a translation input.
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
- **THEN** `tagline-extraction`, `global-scoring`, and any other dossier-derived analytic stage MAY run in any order or concurrently; they do NOT require `fact-extraction` or `geocoding`

#### Scenario: Translation fans in over dossier-derived analytic stages only

- **WHEN** `translation` runs for a company
- **THEN** the outputs of all dossier-derived analytic stages (`4b`, `4c`, …) for that company MUST already exist on disk; `geocoding` is NOT a dependency

#### Scenario: Dataset output depends only on the fact-extraction spine

- **WHEN** `dataset-output` runs for a company
- **THEN** a `fact-extraction` output for that company MUST already exist on disk, and `dataset-output` MUST NOT require `geocoding`, the dossier-derived analytic stages, or `translation` to exist — it joins them when present and treats them as absent (null) when not

### Requirement: Stage Execution Model

Every pipeline stage SHALL be implemented as a self-contained Python module that supports three execution modes:

1. **Standalone CLI**: the stage MUST be runnable from the command line as `python -m <stage-module>` (or equivalent), reading its input from disk (or the configured source for `website-resolution`, the only stage without upstream files) and writing its output to disk per the Output File Layout requirement.
2. **Orchestrator-callable**: the stage MUST expose a programmatic entry point (a function) that a future pipeline orchestrator can invoke without subprocess overhead. The entry point's contract MUST match the on-disk seam — same input shape in, same output shape out — so behavior does not diverge between modes.
3. **Dry-run / no-write mode**: the stage MUST support a mode in which all logic runs (search calls, transformations, etc.) but no output files are written to disk. Dry-run mode is intended for tests; it MAY return outputs in memory to the caller.

These three modes apply to every stage in the Stage Sequence requirement, including any future wave-4 analytic stages.

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
