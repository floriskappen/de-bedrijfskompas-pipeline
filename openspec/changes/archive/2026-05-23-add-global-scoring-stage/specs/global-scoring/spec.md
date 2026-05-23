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

The stage SHALL inspect the dossier frontmatter `status` before any LLM call. It SHALL proceed to scoring only when that status is `ok`. Any other dossier status (`upstream_failed`, `empty`, `llm_error`, or any value other than `ok`) SHALL cascade to `status: upstream_failed` on this stage's output with no LLM call.

#### Scenario: Non-ok dossier cascades

- **WHEN** the dossier frontmatter reports `status: llm_error`
- **THEN** this stage writes `status: upstream_failed`, a null `scores` payload, and makes no LLM call

#### Scenario: Ok dossier proceeds

- **WHEN** the dossier frontmatter reports `status: ok` and the body is non-empty
- **THEN** the stage proceeds to score the company

### Requirement: Axis Set

The stage SHALL score each company on exactly the five axes defined in `docs/GLOBAL_SCORING_FRAMEWORK.md`, identified by these fixed keys: `substance`, `ecology`, `power`, `embeddedness`, `posture`. It SHALL emit all five axes for every successfully scored company and SHALL NOT add, drop, or rename axes. It SHALL NOT emit any composite, aggregate, weighted, or overall score across the axes.

#### Scenario: All five axes present

- **WHEN** company `acme` is scored successfully
- **THEN** its `scores` object contains exactly the keys `substance`, `ecology`, `power`, `embeddedness`, `posture`

#### Scenario: No composite score

- **WHEN** any company is scored
- **THEN** the record contains no overall, total, average, or weighted score field — only the five per-axis entries

### Requirement: Per-Axis Entry Shape

Each axis entry SHALL be an object with three members: `score`, `evidence`, and `reason`. `score` SHALL be an integer in the inclusive range 0–100, or `null`. `evidence` SHALL be exactly one of the fixed vocabulary `well_evidenced`, `partial`, `no_signal`. `reason` SHALL be an object with non-empty `en` and `nl` string members. The stage SHALL enforce the score↔evidence invariant by normalization, not rejection: a numeric `score` returned with `evidence: no_signal` keeps its score and is recorded as `evidence: partial`; a `null` score returned with a numeric evidence level is recorded as `evidence: no_signal`. In the persisted output a `null` score therefore always carries `evidence: no_signal`, and a numeric score never does. Only genuinely unusable axis output (a missing entry, an evidence value outside the vocabulary, a non-integer non-null score, or an empty/missing bilingual reason) is treated as an LLM error.

#### Scenario: Evidenced axis carries a numeric score

- **WHEN** an axis is `well_evidenced` or `partial`
- **THEN** its `score` is an integer 0–100 and its `reason.en` and `reason.nl` are non-empty

#### Scenario: No-signal axis carries a null score

- **WHEN** an axis has `evidence: no_signal`
- **THEN** its `score` is `null` and its `reason` still explains, in `en` and `nl`, that the dossier gives no signal for that axis

#### Scenario: Inconsistent score and evidence are normalized, not rejected

- **WHEN** the model returns a numeric `score` paired with `evidence: no_signal` for one axis (or a `null` score paired with a numeric evidence level)
- **THEN** the stage normalizes that axis (keeping the numeric score as `partial`, or forcing `no_signal` for the null score) and still produces the company's full five-axis record, rather than discarding it as an LLM error

### Requirement: Silence Handling Per Axis

The stage SHALL read silence asymmetrically across axes, per `docs/GLOBAL_SCORING_FRAMEWORK.md` (the source of truth for these rules, transcribed into the prompt): for `substance`, vagueness or marketing-without-specifics counts as a negative signal (a low `score`, not `no_signal`); for `ecology`, a baseline SHALL always be inferred from the company's sector and core activity, so ecology is never `no_signal` — explicit website evidence only adjusts that baseline, with `evidence: well_evidenced` reserved for concrete, specific facts and `partial` for a sector-based read; for `power`, silence SHALL NOT be penalised and absent ownership/governance evidence SHALL default to `evidence: no_signal` with `score: null`; for `embeddedness`, absence of rootedness is a low rootedness `score`, not a penalty; for `posture`, a genuinely neutral tone SHALL score middling rather than be guessed at.

#### Scenario: Ecology is always scored from sector

- **WHEN** the dossier makes no explicit environmental claim
- **THEN** the `ecology` axis still carries a numeric `score` inferred from the company's sector and core activity, with `evidence: partial`, never `no_signal`

#### Scenario: Power silence is unknown, not penalised

- **WHEN** the dossier says nothing about ownership, governance, or who benefits
- **THEN** the `power` axis is `evidence: no_signal` with `score: null`, not a low numeric score

#### Scenario: Substance vagueness counts against

- **WHEN** the dossier cannot say concretely what the company does after the de-marketing pass
- **THEN** the `substance` axis carries a low numeric `score` with an evidenced reason, not `no_signal`

### Requirement: Reason Content

Each axis `reason.en` SHALL state, in plain language, why that axis received its score, grounded in the dossier's substance; `reason.nl` SHALL be its faithful Dutch rendering of the same meaning. Because the dossier is an internal artefact never shown to the user, the reason SHALL NOT quote or cite the dossier or the source website; it SHALL explain the judgement in its own words. It SHALL use no marketing adjectives and add no facts absent from the dossier.

#### Scenario: Reason explains rather than quotes

- **WHEN** an axis score is justified
- **THEN** its `reason` paraphrases the judgement in plain language and contains no quotation of dossier or website text

#### Scenario: Bilingual parity

- **WHEN** a reason is produced for an axis
- **THEN** `reason.en` and `reason.nl` express the same meaning, neither left blank

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/global-scoring/<company-id>.json` containing `name`, `website`, `status`, `model`, and `scores`. The `scores` field SHALL be an object keyed by the five axis names with per-axis entries when `status` is `ok`, and `null` otherwise. `model` SHALL be null when no LLM call was made.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is scored successfully
- **THEN** `data/global-scoring/acme.json` exists with `status: "ok"`, a non-null `model`, and `scores` carrying all five axis entries

#### Scenario: Null scores on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `scores` is `null`

#### Scenario: Name-collision refusal

- **WHEN** `data/global-scoring/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: LLM Generation

The stage SHALL produce each company's scores with a single LLM call via OpenRouter, returning a JSON object covering all five axes. The prompt SHALL instruct the model to write each axis `reason.en` first and then translate it to `reason.nl` within that same response. The prompt SHALL be loaded from a versioned file under `prompts/`, identified by name; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `GLOBAL_SCORING_MODEL` environment variable. A response that cannot be parsed and validated into the five-axis schema (all axes present, each with a valid `score`, `evidence`, and non-empty bilingual `reason`) SHALL be treated as an LLM error.

#### Scenario: Prompt loaded from versioned file

- **WHEN** the stage builds the LLM request
- **THEN** the instruction text is read from a named file under `prompts/`, not from a string literal in a `.py` module

#### Scenario: Model override honoured

- **WHEN** `GLOBAL_SCORING_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Malformed response is an error

- **WHEN** the model returns text that does not validate into the five-axis schema
- **THEN** the company's record is written with `status: llm_error` and `scores: null`

### Requirement: Status Tracking

The `status` field SHALL take exactly one value, each tied to a distinct outcome:

- `ok` — all five axes were scored.
- `upstream_failed` — the dossier is missing or its frontmatter `status` is not `ok`; no LLM call is made.
- `empty` — the dossier frontmatter is `ok` but its body has no usable text; no LLM call is made. The offline mode short-circuit also yields this status.
- `llm_error` — the LLM call failed after retries or returned a response that does not validate into the five-axis schema.

#### Scenario: Empty body recorded

- **WHEN** the dossier frontmatter is `ok` but the body is blank or whitespace
- **THEN** the record is written with `status: empty`, `scores: null`, and no LLM call

#### Scenario: LLM error recorded

- **WHEN** the LLM call fails after retries
- **THEN** the record is written with `status: llm_error` and `scores: null`

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company failures other than the name-collision case. LLM, transport, and decode failures SHALL be caught and recorded as `status: llm_error` on the affected company; the batch continues.

#### Scenario: One LLM failure does not abort batch

- **WHEN** the third company's LLM call times out after retries
- **THEN** the other companies still produce records and company three gets a file with `status: llm_error`

### Requirement: Execution Modes

The stage SHALL support the modes required by `pipeline-architecture`:

1. **CLI**: `python -m pipeline.global_scoring` reads `data/content-summarization/` and writes `data/global-scoring/`.
2. **Orchestrator-callable**: a programmatic entry point yields each output record; on-disk behaviour is identical to CLI.
3. **Dry-run** suppresses writes only (the LLM is still called). A separate **offline** mode short-circuits the LLM call entirely, emitting `status: empty` for companies that would have required it.

The same input SHALL produce the same output record across modes (the only difference being whether and where it is persisted).

#### Scenario: CLI run

- **WHEN** `python -m pipeline.global_scoring` runs with `data/content-summarization/` populated
- **THEN** each dossier produces a `data/global-scoring/<id>.json`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode
- **THEN** no files are written and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made and companies that would need one receive `status: empty`

### Requirement: Out of Scope

The stage SHALL NOT produce a tagline, description, tags, or ikigai/local match; SHALL NOT emit any composite or weighted score (weighting is the frontend's personal layer); and SHALL NOT re-read raw HTML or `content-collection` artefacts. It consumes only the `content-summarization` dossier and emits only the five-axis profile.

#### Scenario: Only the five-axis profile emitted

- **WHEN** the dossier is scored
- **THEN** the output carries the five per-axis entries only, with no tagline, tags, match, or composite number

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious hazards. They are load-bearing for any re-implementation:

- **`.env` precedence.** A local `.env` MUST NOT override an already-exported `OPENROUTER_API_KEY` (CI sets the env var directly). Use `python-dotenv` with `override=False`.
- **JSON response coercion.** Models frequently wrap JSON output in a code fence or chatty preamble; the stage MUST strip these and parse the embedded object rather than treating the whole response as the payload.

#### Scenario: Exported API key not overridden

- **WHEN** `OPENROUTER_API_KEY` is exported in the environment and a local `.env` defines a different value
- **THEN** the exported value is used
