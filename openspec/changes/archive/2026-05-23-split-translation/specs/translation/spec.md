## ADDED Requirements

### Requirement: Target Registry

The stage SHALL maintain an explicit, enumerated list of translation targets. Each target is a `(source-stage, field-path)` pair: `source-stage` is the stage whose `data/<source-stage>/` output directory is read; `field-path` is a dotted path into that stage's JSON record, where a `*` segment matches all dictionary keys at that level. The registered targets are:

- `tagline-extraction` / `tagline` — the English tagline string
- `global-scoring` / `scores.*.reason` — the English reason string for each of the five axes

Adding a translatable field from a new stage requires adding one line to this registry.

#### Scenario: Target registry is enumerated

- **WHEN** the stage runs
- **THEN** it translates exactly the fields declared in the registry — no auto-discovery of `en` keys in upstream JSON

#### Scenario: Wildcard path expands over all axis keys

- **WHEN** the target path `scores.*.reason` is resolved against a `global-scoring` record
- **THEN** it yields one `en` string for each axis key present in `scores` (`substance`, `ecology`, `power`, `embeddedness`, `posture`)

### Requirement: Input Selection

The stage SHALL derive the set of companies to process from the registered source-stage output directories (`data/<source-stage>/`). For each company-id that appears in at least one source directory it SHALL attempt to resolve and translate every registered target. When a source file is missing or its status is not `ok`, the targets from that source are silently skipped for that company; the stage still processes targets available from other sources.

#### Scenario: Company absent from one source

- **WHEN** company `acme` has a `data/global-scoring/acme.json` but no `data/tagline-extraction/acme.json`
- **THEN** the stage translates the global-scoring targets only and writes a record for `acme`

#### Scenario: Company absent from all sources

- **WHEN** no source-stage output exists for company `acme`
- **THEN** the stage writes a record for `acme` with `status: upstream_failed` and no LLM call

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/translation/<company-id>.json` containing `name`, `website`, `status`, `model`, and `translations`. The `translations` field SHALL be an object keyed by flat target-path strings (e.g. `"tagline"`, `"scores.substance.reason"`) each mapping to `{"nl": "<Dutch text>"}` when `status` is `ok`, and `null` otherwise. `model` SHALL be null when no LLM call was made.

A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is translated successfully
- **THEN** `data/translation/acme.json` exists with `status: "ok"`, a non-null `model`, and `translations` carrying a `{"nl": "..."}` entry for each resolved target

#### Scenario: Null translations on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `translations` is `null`

#### Scenario: Name-collision refusal

- **WHEN** `data/translation/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: LLM Generation

The stage SHALL produce all Dutch translations for one company in a single LLM call via OpenRouter, batching every resolved `en` string from all targets together. The prompt SHALL be loaded from a versioned file under `prompts/`; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `TRANSLATION_MODEL` environment variable. A response that cannot be parsed into a mapping of all submitted strings to non-empty Dutch strings SHALL be treated as an LLM error.

#### Scenario: All targets batched into one call

- **WHEN** company `acme` has 6 resolved targets (1 tagline + 5 axis reasons)
- **THEN** all 6 English strings are submitted in a single LLM call and all 6 Dutch strings are returned together

#### Scenario: Model override honoured

- **WHEN** `TRANSLATION_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Malformed response is an error

- **WHEN** the model returns a response that cannot be parsed into Dutch strings for all submitted targets
- **THEN** the company's record is written with `status: llm_error` and `translations: null`

### Requirement: Status Tracking

The `status` field SHALL take exactly one value, each tied to a distinct outcome:

- `ok` — at least one target was resolved and translated.
- `upstream_failed` — no source-stage output exists or is `ok` for this company; no LLM call is made.
- `empty` — source files are present and `ok` but no target fields contain translatable text; no LLM call is made. The offline mode short-circuit also yields this status.
- `llm_error` — the LLM call failed after retries or returned an unparseable response.

#### Scenario: Partial sources still yield ok

- **WHEN** one source stage returned `llm_error` for `acme` and another returned `ok` with translatable targets
- **THEN** the translation record for `acme` is `status: ok` covering the available targets

#### Scenario: LLM error recorded

- **WHEN** the LLM call fails after retries
- **THEN** the record is written with `status: llm_error` and `translations: null`

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company failures other than the name-collision case. LLM, transport, and decode failures SHALL be caught and recorded as `status: llm_error` on the affected company; the batch continues.

#### Scenario: One failure does not abort the batch

- **WHEN** the third company's LLM call times out
- **THEN** the other companies still produce records and company three gets `status: llm_error`

### Requirement: Execution Modes

The stage SHALL support the modes required by `pipeline-architecture`:

1. **CLI**: `python -m pipeline.translation` reads source-stage output directories and writes `data/translation/`.
2. **Orchestrator-callable**: a programmatic entry point yields each output record; on-disk behaviour is identical to CLI.
3. **Dry-run** suppresses writes only (the LLM is still called). A separate **offline** mode short-circuits the LLM call entirely, emitting `status: empty` for companies that would have required one.

#### Scenario: CLI run

- **WHEN** `python -m pipeline.translation` runs with source-stage dirs populated
- **THEN** each company with at least one resolvable target produces a `data/translation/<id>.json`

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made and companies that would need one receive `status: empty`

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious hazards:

- **`.env` precedence.** A local `.env` MUST NOT override an already-exported `OPENROUTER_API_KEY`. Use `python-dotenv` with `override=False`.
- **JSON response coercion.** Models frequently wrap JSON output in a code fence or preamble; the stage MUST strip these and parse the embedded object.

#### Scenario: Exported API key not overridden

- **WHEN** `OPENROUTER_API_KEY` is exported in the environment and a local `.env` defines a different value
- **THEN** the exported value is used
