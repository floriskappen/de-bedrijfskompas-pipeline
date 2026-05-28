## ADDED Requirements

### Requirement: Input Selection

The stage SHALL read each company's input from the `content-summarization` dossier at `data/content-summarization/<company-id>.md`: the YAML frontmatter (`name`, `website`, and `status` are load-bearing) and the markdown body. Only the dossier body SHALL be fed to the LLM; the frontmatter is read for gating and record metadata, never as company substance. When the dossier file is missing, the company is treated as `upstream_failed`.

#### Scenario: Dossier body is the LLM input

- **WHEN** company `acme` has a dossier with frontmatter and a markdown body
- **THEN** the stage builds the LLM request from the body text only, and reads `name`, `website`, and `status` from the frontmatter

#### Scenario: Missing dossier treated as upstream failure

- **WHEN** no `data/content-summarization/<company-id>.md` exists for a company
- **THEN** the stage writes a record with `status: upstream_failed` and no LLM call is made

### Requirement: Upstream Status Gate

The stage SHALL inspect the dossier frontmatter `status` before any LLM call. It SHALL proceed to tagging only when that status is `ok` AND the dossier body has non-whitespace content. Any other dossier status (`upstream_failed`, `empty`, `llm_error`, or any value other than `ok`) SHALL cascade to `status: upstream_failed` on this stage's output with no LLM call. An `ok` dossier whose body is empty or whitespace-only SHALL produce `status: empty` with no LLM call (there is nothing to tag).

#### Scenario: Non-ok dossier cascades

- **WHEN** the dossier frontmatter reports `status: llm_error`
- **THEN** this stage writes `status: upstream_failed`, a null `capability_tags` payload, and makes no LLM call

#### Scenario: Ok dossier proceeds

- **WHEN** the dossier frontmatter reports `status: ok` and the body is non-empty
- **THEN** the stage proceeds to tag the company

#### Scenario: Empty body short-circuits to empty status

- **WHEN** the dossier frontmatter reports `status: ok` but the body is empty or whitespace-only
- **THEN** the stage writes `status: empty`, a null `capability_tags` payload, and makes no LLM call

### Requirement: Capability Family Vocabulary

The stage SHALL draw every emitted `family` value from this fixed set of 19 tier-1 capability slugs, and SHALL NOT emit any family outside it:

`software-engineering`, `data-ai`, `hardware-electronics`, `mechanical-civil-engineering`, `life-sciences`, `earth-environmental-sciences`, `clinical-care`, `design-creative`, `content-media`, `commercial`, `finance-accounting`, `legal-compliance`, `policy-public-administration`, `operations-supply-chain`, `people-org`, `field-trades-operators`, `education-training`, `service-hospitality`, `community-social`.

The vocabulary SHALL be embedded in the versioned prompt under `prompts/tagging.md`, including a short description per slug and explicit edge-case routing (e.g. production-line manufacturing labour and vehicle/equipment operators route to `field-trades-operators`; management and strategy consulting route to `commercial`; general public-sector administration routes to `policy-public-administration`; customer service, retail-floor, call-centre, and personal services route to `service-hospitality`).

#### Scenario: Emitted family is in the fixed set

- **WHEN** the stage produces a capability tag for any company
- **THEN** its `family` value is one of the 19 listed slugs

#### Scenario: Out-of-vocabulary family is treated as LLM error

- **WHEN** the LLM returns a tag whose `family` is not in the fixed set
- **THEN** the stage writes `status: llm_error` and `capability_tags: null` for that company, rather than emitting the unknown slug

### Requirement: Capability Tag Shape

Each emitted capability tag SHALL be an object with exactly two members: `family` (one of the fixed slugs) and `prominence` (exactly one of `core`, `supporting`, `incidental`). `core` denotes a capability the company is fundamentally built on; `supporting` denotes a capability that is real but not central; `incidental` denotes a capability mentioned in passing. At most one entry per `family` SHALL appear in a company's `capability_tags` list. The stage SHALL NOT emit any field on a tag entry other than `family` and `prominence`.

#### Scenario: Tag carries family and prominence

- **WHEN** the stage emits a capability tag
- **THEN** the tag object has exactly `family` (a valid slug) and `prominence` (one of `core`, `supporting`, `incidental`)

#### Scenario: One entry per family

- **WHEN** the LLM returns two entries with the same `family`
- **THEN** the stage writes `status: llm_error` and `capability_tags: null` rather than emitting duplicates

#### Scenario: Invalid prominence is an LLM error

- **WHEN** the LLM returns a tag with a `prominence` outside `core` / `supporting` / `incidental`
- **THEN** the stage writes `status: llm_error` and `capability_tags: null`

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/tagging/<company-id>.json` containing `name`, `website`, `status`, `model`, and `capability_tags`. The `capability_tags` field SHALL be a JSON array of capability-tag objects (possibly empty) when `status` is `ok`, and `null` otherwise. `model` SHALL be null when no LLM call was made.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is processed successfully
- **THEN** `data/tagging/acme.json` exists with `status: "ok"`, a non-null `model`, and `capability_tags` as an array of tag objects (possibly empty)

#### Scenario: Null capability_tags on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `capability_tags` is `null` (not an empty array)

#### Scenario: Empty array allowed on ok

- **WHEN** the LLM returns no applicable capabilities for an `ok` dossier
- **THEN** `capability_tags` is `[]` and `status` remains `ok`

#### Scenario: Name-collision refusal

- **WHEN** `data/tagging/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: LLM Configuration

The stage SHALL call OpenRouter's chat-completions endpoint using the model id resolved from, in order: an explicit argument to the LLM client, the `TAGGING_MODEL` environment variable, and the default `deepseek/deepseek-v4-flash`. It SHALL request JSON-object response format and retry on transport, decode, or shape failures up to a fixed cap before producing `status: llm_error`.

#### Scenario: Default model

- **WHEN** neither an explicit argument nor `TAGGING_MODEL` is set
- **THEN** the stage calls `deepseek/deepseek-v4-flash`

#### Scenario: Env override

- **WHEN** `TAGGING_MODEL=anthropic/claude-sonnet-4` is exported
- **THEN** the stage calls `anthropic/claude-sonnet-4` instead

### Requirement: Execution Modes

The stage SHALL be runnable from the command line as `python -m pipeline.tagging`, SHALL expose a programmatic entry point (`pipeline.tagging.core.run`) whose contract matches the on-disk seam, and SHALL support a dry-run mode that performs all logic but writes no output files. The CLI SHALL accept at least `--input`, `--out-dir`, `--dry-run`, `--offline`, `--company`, and `--limit` flags consistent with the other dossier-derived analytic stages. The `--offline` flag SHALL skip all LLM calls and mark every otherwise-eligible company as `status: empty`.

#### Scenario: CLI runs the stage end-to-end

- **WHEN** a developer runs `python -m pipeline.tagging`
- **THEN** the stage reads dossiers from `data/content-summarization/`, calls the LLM for `ok` dossiers, and writes one JSON file per company to `data/tagging/`

#### Scenario: Dry-run writes nothing

- **WHEN** the CLI is invoked with `--dry-run`
- **THEN** records are emitted to stdout as JSON Lines and no files are written under `data/tagging/`

#### Scenario: Offline skips LLM

- **WHEN** the CLI is invoked with `--offline`
- **THEN** every eligible company's output has `status: empty`, `model: null`, and `capability_tags: null`, with no network call made
