## MODIFIED Requirements

### Requirement: End-to-End Orchestrator

The pipeline SHALL expose a `pipeline.run` module runnable as `python -m pipeline.run --input <path>` that drives every stage in the Stage Sequence over a single input JSON array. The input shape SHALL match `website-resolution`'s input: a JSON array of records each with at least `name`. The orchestrator SHALL invoke each stage's programmatic entry point directly; it SHALL NOT spawn `python -m` subprocesses.

Within a single run, the orchestrator SHALL process stages one at a time in dependency order, running each stage to completion across all companies before invoking the next. Within a stage, companies SHALL be yielded in input order; a stage MAY process companies concurrently.

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

## ADDED Requirements

### Requirement: Intra-Stage LLM Concurrency

An LLM-using stage (`fact-extraction`, `content-summarization`, `tagline-extraction`, `global-scoring`, `tagging`, `translation`) MAY process companies concurrently within a bounded pool; the pool size SHALL be capped per stage and overridable via a `<STAGE>_CONCURRENCY` environment variable. Records SHALL be yielded in input order regardless of completion order, and per-company failure isolation SHALL be preserved: a failed LLM call yields a failure-status record and SHALL NOT abort the batch.

#### Scenario: Concurrent processing yields in input order

- **WHEN** a stage processes a batch concurrently and a later company's LLM call completes before an earlier company's
- **THEN** the stage still yields the earlier company's record first

#### Scenario: Per-company failure does not abort a concurrent batch

- **WHEN** one company's LLM call fails after retries while other companies' calls are in flight
- **THEN** the failed company is yielded with a failure status and the remaining companies' records are still yielded in input order

### Requirement: Rate-Limit-Aware Retries

An LLM-using stage's retry loop SHALL wait with exponential backoff and jitter before retrying on 429 or 5xx responses, honouring a `Retry-After` header when the provider sends one, rather than retrying immediately. Backoff applies across the per-stage concurrency pool: concurrent requests that share an API key and are rate-limited together SHALL not retry in lockstep.

#### Scenario: Rate-limit retry backs off

- **WHEN** the provider returns 429 for a request
- **THEN** the stage waits (exponential backoff with jitter, honouring `Retry-After` if present) before retrying, rather than retrying immediately

#### Scenario: Concurrent retries do not fire in lockstep

- **WHEN** several in-flight requests in a stage all receive 429 within the same window
- **THEN** their retries are spaced by jittered backoff rather than retrying simultaneously
