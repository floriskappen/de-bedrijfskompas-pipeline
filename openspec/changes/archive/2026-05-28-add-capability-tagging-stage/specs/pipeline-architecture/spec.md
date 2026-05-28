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
