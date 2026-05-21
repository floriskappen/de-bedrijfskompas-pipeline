## ADDED Requirements

### Requirement: Input Selection

The stage SHALL read each company's input from `data/content-collection/<company-id>/`: `_meta.json` (always present; `name`, `website`, and `status` are load-bearing) plus the precision per-page markdown files `<slug>.md`. Recall-mode files (`<slug>.recall.md`) SHALL be ignored — they exist for `fact-extraction` and carry boilerplate noise.

Page bodies SHALL be concatenated in a deterministic order — `index` first, then remaining slugs alphabetically — each labelled with its slug, and the concatenation SHALL be truncated to at most 24000 characters before the LLM call.

#### Scenario: Recall files excluded

- **WHEN** a company directory contains both `about.md` and `about.recall.md`
- **THEN** only `about.md` contributes to the dossier input; `about.recall.md` is ignored

#### Scenario: Deterministic page order

- **WHEN** a company has `portfolio.md`, `index.md`, and `about.md`
- **THEN** the concatenated input orders them `index`, `about`, `portfolio`, each prefixed by its slug

#### Scenario: Oversized input truncated

- **WHEN** the concatenated page bodies exceed 24000 characters
- **THEN** the input is truncated to 24000 characters before the LLM call and the stage still produces a dossier

### Requirement: Output Dossier File

For each company the stage SHALL write one markdown file at `data/content-summarization/<company-id>.md`. The file SHALL begin with a YAML frontmatter block carrying `name`, `website`, `status`, `source_language`, and `model`, followed by the dossier body in markdown.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Dossier written with frontmatter

- **WHEN** company `acme` is summarised successfully
- **THEN** `data/content-summarization/acme.md` exists, opening with a YAML frontmatter block containing `name`, `website`, `status`, `source_language`, and `model`, followed by the markdown body

#### Scenario: Name-collision refusal

- **WHEN** `data/content-summarization/acme.md` exists with frontmatter `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Dossier Content

The dossier body SHALL be a faithful, de-marketed, English company description written for consumption by downstream LLM stages, not for humans. It SHALL:

- Contain all substantive information present in the source that is relevant to understanding the company (what it does, its products/services, stated mission and values, sector, customers, history, size/structure cues), and omit sections for which the source provides nothing — structure is dynamic per company.
- Be normalised to English regardless of source language.
- Deduplicate content repeated across pages.
- Distinguish what the company **does** (activities, offerings) from what it **claims or stands for** (mission, values), attributing claims as claims rather than asserting them as established fact.
- Have length driven by the substance available, not a fixed target — a terse factual site yields a short dossier; a marketing-heavy site collapses to its few sentences of substance.

#### Scenario: Marketing collapsed to substance

- **WHEN** the source is dominated by emotive marketing or narrative content with little concrete description of the company's offering
- **THEN** the dossier is short, states plainly what the company does insofar as the source supports it, and does not pad with restated marketing

#### Scenario: Source language normalised

- **WHEN** the source pages are written in Dutch
- **THEN** the dossier body is written in English and `source_language` records the detected source language

#### Scenario: Cross-page duplication removed

- **WHEN** the same descriptive content appears on two or more pages
- **THEN** the dossier states the information once

#### Scenario: Claim attributed, not asserted

- **WHEN** the source states an aspirational mission or impact claim about the company
- **THEN** the dossier records it as a stated claim, not as an established fact

### Requirement: Faithfulness and Noise Rejection

The dossier SHALL add no facts absent from the source, and SHALL reflect only content genuinely attributable to the company. It SHALL NOT treat as company information any non-company noise present in the source — for example placeholder or filler text, leftover template content describing an unrelated business, sample or mockup data, or bulk repetitive listings — beyond what is needed to convey what the company does. World-knowledge enrichment is out of scope and SHALL NOT be performed at this stage.

#### Scenario: Filler and unrelated template excluded

- **WHEN** a page contains placeholder filler text or leftover template content describing a business unrelated to the company's evident purpose
- **THEN** none of it appears in the dossier

#### Scenario: Sample data not treated as fact

- **WHEN** a page contains sample or mockup data (such as fictitious names, addresses, or records used to illustrate a feature)
- **THEN** that data is not recorded as the company's own information

#### Scenario: Bulk listing not reproduced

- **WHEN** a page consists largely of a long repetitive listing (such as schedules, events, or catalogue entries) with the company's actual description appearing only briefly
- **THEN** the dossier conveys what the company does without reproducing the listing

#### Scenario: No external facts added

- **WHEN** the source does not state the company's founding year
- **THEN** the dossier does not supply a founding year from the model's own knowledge

### Requirement: LLM Generation

The stage SHALL produce each dossier with a single LLM call via OpenRouter. The prompt SHALL be loaded from a versioned file under `prompts/`, identified by name; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `CONTENT_SUMMARIZATION_MODEL` environment variable. The model output SHALL be used as the dossier body after stripping any conversational preamble/epilogue or surrounding code fences.

#### Scenario: Prompt loaded from versioned file

- **WHEN** the stage builds the LLM request
- **THEN** the instruction text is read from a named file under `prompts/`, not from a string literal in a `.py` module

#### Scenario: Model override honoured

- **WHEN** `CONTENT_SUMMARIZATION_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Conversational wrapper stripped

- **WHEN** the model returns the dossier wrapped in `Here is the dossier:` preamble or a ` ```markdown ` fence
- **THEN** the wrapper is removed and only the dossier body is written

### Requirement: Status Tracking

The frontmatter `status` field SHALL take exactly one value, each tied to a distinct outcome:

- `ok` — a dossier body was generated.
- `upstream_failed` — `_meta.json.status` is `upstream_failed` or `fetch_failed`; no LLM call is made and the body is empty.
- `empty` — content-collection succeeded but no usable page content was available to summarise; no LLM call is made and the body is empty.
- `llm_error` — the LLM call failed after retries; the body is empty.

#### Scenario: Upstream failure propagated

- **WHEN** `_meta.json.status` is `upstream_failed`
- **THEN** the dossier file is written with `status: upstream_failed`, an empty body, and no LLM call is made

#### Scenario: No content to summarise

- **WHEN** content-collection reports `ok` but no precision page bodies exist
- **THEN** the dossier file is written with `status: empty` and no LLM call is made

#### Scenario: LLM error recorded

- **WHEN** the LLM call fails after retries
- **THEN** the dossier file is written with `status: llm_error` and an empty body

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company failures other than the name-collision case. LLM errors and decode failures SHALL be caught and recorded as `status: llm_error` on the affected company; the batch continues.

#### Scenario: One LLM failure does not abort batch

- **WHEN** the third company's LLM call times out after retries
- **THEN** the other companies still produce their dossiers and company three gets a file with `status: llm_error`

### Requirement: Execution Modes

The stage SHALL support the modes required by `pipeline-architecture`:

1. **CLI**: `python -m pipeline.content_summarization` reads `data/content-collection/` and writes `data/content-summarization/`.
2. **Orchestrator-callable**: a programmatic entry point yields each output record; on-disk behaviour is identical to CLI.
3. **Dry-run** suppresses writes only (the LLM is still called). A separate **offline** mode short-circuits the LLM call entirely, emitting `status: empty` for companies that would have required it.

The same input SHALL produce the same output record across modes (the only difference being whether and where it is persisted).

#### Scenario: CLI run

- **WHEN** `python -m pipeline.content_summarization` runs with `data/content-collection/` populated
- **THEN** each company directory produces a `data/content-summarization/<id>.md`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode
- **THEN** no files are written and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made and companies that would need one receive `status: empty`

### Requirement: Out of Scope

The stage SHALL NOT:

- Score, rate, or rank the company (bullshit-scoring, bcorp-scoring are downstream stage-5 stages).
- Produce the concise human-facing front-end description (a downstream stage derives that from the dossier).
- Perform philosophical-framework mapping, tagging, or ikigai-matching.
- Extract structured facts such as the HQ address (that is `fact-extraction`).
- Re-fetch or re-parse raw HTML — it consumes only `content-collection` artefacts.

#### Scenario: No scoring emitted

- **WHEN** the source contains heavy marketing language
- **THEN** the dossier reflects the de-marketed substance but emits no bullshit score or rating

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious hazards. They are load-bearing for any re-implementation:

- **`.env` precedence.** A local `.env` MUST NOT override an already-exported `OPENROUTER_API_KEY` (CI sets the env var directly). Use `python-dotenv` with `override=False`.
- **Markdown wrapper artefacts.** Models frequently wrap markdown output in a code fence or add a chatty preamble even when asked not to; the stage MUST strip these before persisting rather than treating them as content.

#### Scenario: Exported API key not overridden

- **WHEN** `OPENROUTER_API_KEY` is exported in the environment and a local `.env` defines a different value
- **THEN** the exported value is used
