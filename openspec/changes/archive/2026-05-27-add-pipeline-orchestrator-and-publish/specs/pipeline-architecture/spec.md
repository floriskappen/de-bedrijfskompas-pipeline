## ADDED Requirements

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
