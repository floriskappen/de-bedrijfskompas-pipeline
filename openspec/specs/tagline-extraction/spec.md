# tagline-extraction Specification

## Purpose
TBD - created by archiving change add-tagline-extraction-stage. Update Purpose after archive.
## Requirements
### Requirement: Input Selection

The stage SHALL read each company's input from the `content-summarization` dossier at `data/content-summarization/<company-id>.md`: the YAML frontmatter (`name`, `website`, and `status` are load-bearing) and the markdown body. Only the dossier body SHALL be fed to the LLM; the frontmatter is read for gating and record metadata, never as company substance. When the dossier file is missing, the company is treated as `upstream_failed`.

#### Scenario: Dossier body is the LLM input

- **WHEN** company `acme` has a dossier with frontmatter and a markdown body
- **THEN** the stage builds the LLM request from the body text only, and reads `name`, `website`, and `status` from the frontmatter

#### Scenario: Missing dossier treated as upstream failure

- **WHEN** no `data/content-summarization/<company-id>.md` exists for a company
- **THEN** the stage writes a record with `status: upstream_failed` and no LLM call is made

### Requirement: Upstream Status Gate

The stage SHALL inspect the dossier frontmatter `status` before any LLM call. It SHALL proceed to generation only when that status is `ok`. Any other dossier status (`upstream_failed`, `empty`, `llm_error`, or any value other than `ok`) SHALL cascade to `status: upstream_failed` on this stage's output with no LLM call.

#### Scenario: Non-ok dossier cascades

- **WHEN** the dossier frontmatter reports `status: llm_error`
- **THEN** this stage writes `status: upstream_failed`, null taglines, and makes no LLM call

#### Scenario: Ok dossier proceeds

- **WHEN** the dossier frontmatter reports `status: ok` and the body is non-empty
- **THEN** the stage proceeds to generate the tagline

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/tagline-extraction/<company-id>.json` containing `name`, `website`, `status`, `model`, and `tagline`. The `tagline` field SHALL be an object with `en` and `nl` string members when `status` is `ok`, and `{"en": null, "nl": null}` otherwise. `model` SHALL be null when no LLM call was made.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is processed successfully
- **THEN** `data/tagline-extraction/acme.json` exists with `status: "ok"`, a non-null `model`, and `tagline` carrying non-empty `en` and `nl` strings

#### Scenario: Null taglines on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `tagline` is `{"en": null, "nl": null}`

#### Scenario: Name-collision refusal

- **WHEN** `data/tagline-extraction/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Tagline Content

The `en` tagline SHALL be a plain-language description a non-technical reader understands at a glance, and the `nl` tagline SHALL be its faithful Dutch rendering of the same meaning. It SHALL convey what the company actually does and who it is for, with the honest who-pays-for-what relationship coming through rather than the company's mission or self-description — but it SHALL NOT be forced into a fixed "[customer] pays [company]" template; the verb SHALL fit the company (a product company "makes"/"sells", a service company is "hired by"/"paid by"). It SHALL name the core activity rather than enumerate the full product list. It SHALL NOT repeat the company's own name, which is displayed alongside the tagline; it SHALL open with what the company does or a short descriptor (e.g. "A digital consultancy hired by…", "Sells…", "Makes…"). It SHALL use no jargon, no marketing adjectives (e.g. "innovative", "leading", "cutting-edge"), and add no facts absent from the dossier. It SHALL be one sentence; a second sentence is permitted only when the dossier is too thin or self-contradictory to convey the core in one, and that second sentence SHALL state the limitation (e.g. "However, no specific offerings are listed at the time of analysis").

#### Scenario: Honest revenue relationship comes through

- **WHEN** the dossier describes a B2B agency wrapped in mission language
- **THEN** the tagline conveys who pays the company and for what (e.g. "A digital consultancy hired by clients to design and build their software"), not the marketing mission, and does not retreat into vague phrasing such as "helps companies with digital solutions"

#### Scenario: Company name omitted

- **WHEN** a tagline is produced for a company whose name is a distinctive word
- **THEN** neither the `en` nor the `nl` tagline contains the company's name, since it is shown next to the tagline

#### Scenario: Bilingual parity

- **WHEN** a tagline is produced
- **THEN** `en` and `nl` express the same meaning, neither left blank

#### Scenario: Thin dossier gets a caveat sentence

- **WHEN** the dossier lists no concrete offerings or contradicts itself
- **THEN** the tagline states the company's apparent core and appends one caveat sentence noting the missing or conflicting information

#### Scenario: No marketing language

- **WHEN** the dossier is dense with promotional adjectives
- **THEN** the tagline contains none of them and states plainly what the company does

### Requirement: LLM Generation

The stage SHALL produce each tagline with a single LLM call via OpenRouter, returning a JSON object with `en` and `nl` string keys. The prompt SHALL be loaded from a versioned file under `prompts/`, identified by name; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `TAGLINE_EXTRACTION_MODEL` environment variable. A response that cannot be parsed into an object with non-empty `en` and `nl` strings SHALL be treated as an LLM error.

#### Scenario: Prompt loaded from versioned file

- **WHEN** the stage builds the LLM request
- **THEN** the instruction text is read from a named file under `prompts/`, not from a string literal in a `.py` module

#### Scenario: Model override honoured

- **WHEN** `TAGLINE_EXTRACTION_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Malformed response is an error

- **WHEN** the model returns text that is not a JSON object with non-empty `en` and `nl`
- **THEN** the company's record is written with `status: llm_error` and null taglines

### Requirement: Status Tracking

The `status` field SHALL take exactly one value, each tied to a distinct outcome:

- `ok` — a bilingual tagline was generated.
- `upstream_failed` — the dossier is missing or its frontmatter `status` is not `ok`; no LLM call is made.
- `empty` — the dossier frontmatter is `ok` but its body has no usable text; no LLM call is made. The offline mode short-circuit also yields this status.
- `llm_error` — the LLM call failed after retries or returned an unparseable/incomplete response.

#### Scenario: Empty body recorded

- **WHEN** the dossier frontmatter is `ok` but the body is blank or whitespace
- **THEN** the record is written with `status: empty`, null taglines, and no LLM call

#### Scenario: LLM error recorded

- **WHEN** the LLM call fails after retries
- **THEN** the record is written with `status: llm_error` and null taglines

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company failures other than the name-collision case. LLM, transport, and decode failures SHALL be caught and recorded as `status: llm_error` on the affected company; the batch continues.

#### Scenario: One LLM failure does not abort batch

- **WHEN** the third company's LLM call times out after retries
- **THEN** the other companies still produce records and company three gets a file with `status: llm_error`

### Requirement: Execution Modes

The stage SHALL support the modes required by `pipeline-architecture`:

1. **CLI**: `python -m pipeline.tagline_extraction` reads `data/content-summarization/` and writes `data/tagline-extraction/`.
2. **Orchestrator-callable**: a programmatic entry point yields each output record; on-disk behaviour is identical to CLI.
3. **Dry-run** suppresses writes only (the LLM is still called). A separate **offline** mode short-circuits the LLM call entirely, emitting `status: empty` for companies that would have required it.

The same input SHALL produce the same output record across modes (the only difference being whether and where it is persisted).

#### Scenario: CLI run

- **WHEN** `python -m pipeline.tagline_extraction` runs with `data/content-summarization/` populated
- **THEN** each dossier produces a `data/tagline-extraction/<id>.json`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode
- **THEN** no files are written and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made and companies that would need one receive `status: empty`

### Requirement: Out of Scope

The stage SHALL NOT score, rate, or rank the company; SHALL NOT perform tagging, ikigai-matching, or other analytic labelling; and SHALL NOT re-read raw HTML or `content-collection` artefacts. It consumes only the `content-summarization` dossier.

#### Scenario: No scoring emitted

- **WHEN** the dossier contains heavy marketing language
- **THEN** the output carries a tagline only, with no score, rating, or rank

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious hazards. They are load-bearing for any re-implementation:

- **`.env` precedence.** A local `.env` MUST NOT override an already-exported `OPENROUTER_API_KEY` (CI sets the env var directly). Use `python-dotenv` with `override=False`.
- **JSON response coercion.** Models frequently wrap JSON output in a code fence or chatty preamble; the stage MUST strip these and parse the embedded object rather than treating the whole response as the tagline.

#### Scenario: Exported API key not overridden

- **WHEN** `OPENROUTER_API_KEY` is exported in the environment and a local `.env` defines a different value
- **THEN** the exported value is used

