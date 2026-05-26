# fact-extraction Specification

## Purpose

Pipeline stage 3a: extract a structured HQ address (`{street, postcode, city, country}`) per company from the `content-collection` output, using a regex-anchored fast path and a small-LLM fallback. The `status` field doubles as a resolution-path label so per-path accuracy is auditable downstream.

## Requirements

### Requirement: Input Record Shape

The stage SHALL read each company's input from `data/content-collection/<company-id>/`: `_meta.json` (always present; `status`, `footer_text`, and `pages` are load-bearing) plus optional per-page markdown.

For each address-bearing slug — `contact`, `over-ons`, `about`, `about-us` — the stage SHALL prefer `<slug>.recall.md` when present and fall back to `<slug>.md` otherwise.

If `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`, the stage SHALL emit `status: "upstream_failed"` without attempting extraction or any LLM call. All other input keys SHALL be carried through verbatim so downstream stages can join on company identity.

#### Scenario: Recall-mode markdown preferred

- **WHEN** both `contact.md` and `contact.recall.md` exist
- **THEN** the postcode anchor is applied against `contact.recall.md`; `contact.md` is ignored

#### Scenario: Precision markdown used when recall absent

- **WHEN** `contact.md` exists but `contact.recall.md` does not
- **THEN** the postcode anchor is applied against `contact.md`

#### Scenario: Upstream failure propagation

- **WHEN** `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`
- **THEN** no extraction is attempted and the output has `status: "upstream_failed"` with input keys preserved

#### Scenario: Extra input keys preserved

- **WHEN** `_meta.json` contains `{"name": ..., "website": ..., "source": "incubator-2026-01", ...}`
- **THEN** the output record retains `source` with the same value

### Requirement: Output Schema

For each company, the stage SHALL emit a JSON object:

- `name`: string (from input).
- `website`: string or null (from input).
- `address`: object with independently nullable fields:
  - `street`: string or null (street name + house number).
  - `postcode`: string or null. When non-null, MUST match the Dutch postcode regex normalised to `"DDDD LL"` uppercase with a single space.
  - `city`: string or null.
  - `country`: string or null. ISO 3166-1 alpha-2 when set.
- `status`: one of `regex_single`, `regex_disambiguated`, `llm_fallback`, `empty`, `upstream_failed`, `llm_error` (see Status Tracking).
- `source`: string or null. For regex paths, the substring of input text that yielded the match (≤200 chars); for `llm_fallback`, the model id; null for `empty`, `upstream_failed`, `llm_error`.

Any input-record key not listed above SHALL be carried through verbatim.

#### Scenario: All fields present

- **WHEN** the regex path yields `{street: "Europalaan 100", postcode: "3526 KS", city: "Utrecht", country: "NL"}` from a single footer hit
- **THEN** `address` carries those four values and `status: "regex_single"`

#### Scenario: Partial address

- **WHEN** the LLM fallback emits `{street: null, postcode: null, city: "Utrecht", country: "NL"}`
- **THEN** `address.city` is `"Utrecht"`, the other address fields are null, `status: "llm_fallback"`

### Requirement: Postcode Anchor

The stage SHALL detect Dutch postal codes using the regex `\d{4}\s?[A-Z]{2}` with the letter pair uppercase in the source text. Lowercase letter pairs are not matched. Normalised output form: `"DDDD LL"` uppercase with single space. Each match anchors a candidate:

- Up to 80 characters of preceding context → `street` (taken backwards to the first `\n`, `|`, or `,` boundary; leading punctuation stripped).
- The matched postcode itself.
- Up to 40 characters of following context → `city` (taken forwards to the first `\n`, `,`, `|`, `(`, or `\t` boundary).
- `country` defaults to `"NL"` (the regex is Dutch-specific).

The anchor SHALL be applied to surfaces in order: `_meta.json.footer_text` (tagged `footer`), then `contact` / `over-ons` / `about` / `about-us` page content (tagged `body`).

#### Scenario: Single clean footer hit

- **WHEN** `footer_text` is `"Europalaan 100, 3526 KS Utrecht | KVK 12345678"`
- **THEN** one `footer` candidate is produced: `{street: "Europalaan 100", postcode: "3526 KS", city: "Utrecht", country: "NL"}`

#### Scenario: Lowercase postcode not matched by regex

- **WHEN** the surface text contains `"3526 ks utrecht"`
- **THEN** no candidate is produced; the company falls to the LLM fallback path

#### Scenario: No-space postcode normalised

- **WHEN** the surface text contains `"3526KS Utrecht"`
- **THEN** the candidate's `postcode` is `"3526 KS"`

#### Scenario: Postcode in email rejected

- **WHEN** the surface text contains `support@1234ab.example`
- **THEN** no candidate is produced for `1234AB`

#### Scenario: Non-breaking space tolerated

- **WHEN** the surface text contains `"3526 KS Utrecht"` (non-breaking spaces)
- **THEN** a candidate with `postcode: "3526 KS"` and `city: "Utrecht"` is produced

### Requirement: Candidate Filtering and Ranking

After candidates are produced, the stage SHALL apply, in order:

1. **`Postbus` filter** — candidates whose `street` (case-insensitive, trailing punctuation tolerated) begins with `Postbus`, `P.O. Box`, or `Pb.` SHALL be discarded.
2. **Hint-based ranking** — within a 60-character window before and after each surviving candidate, capped at the nearest single newline, scan case-insensitively for:
   - **Boosts**: `bezoekadres`, `hoofdkantoor`, `vestiging`, `vestigingsadres`, `kantooradres`, `hq`, `headquarters`, `head office`, `main office`, `registered office`, `visiting address`, `office address`.
   - **Demotions**: `postadres`, `correspondentieadres`, `factuuradres`, `mailing address`, `postal address`, `po box`, `p.o. box`.
3. **Surface ranking** — `footer` candidates rank above `body` candidates at equal hint tier.

A single surviving candidate is the `regex_single` path. Multiple survivors feed disambiguation, except: if exactly one candidate carries a boost and no others do, that candidate SHALL be emitted directly as `regex_single` without an LLM call.

#### Scenario: Postbus stripped

- **WHEN** footer text is `"Postbus 123, 3500 AA Utrecht | Bezoekadres: Europalaan 100, 3526 KS Utrecht"`
- **THEN** the `Postbus 123` candidate is discarded and the boosted `Europalaan 100` candidate is emitted as `regex_single`

#### Scenario: Boost wins without LLM

- **WHEN** two candidates remain after filtering and exactly one carries a `hoofdkantoor` label
- **THEN** the boosted candidate is emitted as `regex_single` with no LLM call

#### Scenario: Footer beats body

- **WHEN** one candidate is from `footer_text` and one from `about.md` body, no hints either side
- **THEN** the footer candidate ranks first; both still proceed to disambiguation

#### Scenario: Postadres demoted

- **WHEN** a candidate is preceded by `Postadres:` within the hint window
- **THEN** it ranks below any non-demoted candidate

### Requirement: Disambiguation Path

When two or more candidates survive filtering and no sole-boost shortcut applies, the stage SHALL call an LLM with the top 5 candidates (by surface+hint ranking) as structured JSON, each with `street`, `postcode`, `city`, and ≤200 chars of surrounding context. The model returns an index or `null`. On a valid index, the chosen candidate is emitted verbatim with `status: "regex_disambiguated"`. On `null`, all address fields are null and `status: "empty"`.

#### Scenario: Two equal candidates resolved

- **WHEN** two footer candidates remain with no hints and the LLM returns the index of the second
- **THEN** the second candidate is emitted with `status: "regex_disambiguated"`

#### Scenario: LLM declines to pick

- **WHEN** the disambiguation LLM returns `null`
- **THEN** all address fields are null and `status: "empty"`

### Requirement: LLM Fallback Path

When zero candidates survive filtering, the stage SHALL attempt LLM extraction from prose. The call:

- Receives ≤2000 chars of concatenated page content drawn from `contact` / `over-ons` / `about` / `about-us` in that order. `footer_text` is excluded — the regex already scanned it, so its inclusion would add noise without signal.
- Returns the address schema with explicit nulls for unknown fields.
- Has its emitted `postcode` re-validated against the postcode regex; a non-conforming value SHALL be dropped to null while other fields are retained.
- Sets `status: "llm_fallback"` on success, including the all-null case (the path was taken, the model said nothing was extractable).

The stage SHALL NOT call the LLM when no relevant page content was collected; in that case it emits `status: "empty"` directly.

#### Scenario: Prose-only address extracted

- **WHEN** no postcode matches anywhere but `contact.md` contains `"gevestigd in het centrum van Utrecht"` and the LLM emits `{street: null, postcode: null, city: "Utrecht", country: "NL"}`
- **THEN** those values are recorded with `status: "llm_fallback"`

#### Scenario: Invalid postcode dropped to null

- **WHEN** the LLM fallback emits `{postcode: "3526", city: "Utrecht", ...}` (incomplete postcode)
- **THEN** `postcode` is rewritten to null; `city` is retained; `status: "llm_fallback"`

#### Scenario: Fallback yields nothing

- **WHEN** the LLM fallback returns all-null fields
- **THEN** all address fields are null and `status: "llm_fallback"` (not `"empty"` — the path label is preserved)

### Requirement: Status Tracking

The output `status` field SHALL take exactly one value, each tied to a distinct resolution path:

- `regex_single` — one surviving candidate (or sole-boost shortcut); no LLM call.
- `regex_disambiguated` — multiple survivors, LLM picked one.
- `llm_fallback` — zero survivors, LLM extracted from prose (including the all-null case).
- `empty` — extraction ran, all fields null. Distinct from `llm_fallback` to preserve path attribution: `empty` means disambiguation declined or no surface was available.
- `upstream_failed` — `content-collection` reported `upstream_failed` or `fetch_failed`; no extraction attempted.
- `llm_error` — an LLM call needed by the resolution path failed after retries.

#### Scenario: LLM error distinct from empty

- **WHEN** the disambiguation LLM raises after retries
- **THEN** all address fields are null and `status: "llm_error"`

### Requirement: Output File Layout

The stage SHALL write one file per company at `data/fact-extraction/<company-id>.json` containing the Output Schema JSON.

A company-id collision with a differing `name` SHALL be treated as a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful write

- **WHEN** company `acme` resolves successfully
- **THEN** `data/fact-extraction/acme.json` exists with the output JSON

#### Scenario: Name-collision refusal

- **WHEN** `data/fact-extraction/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company resolution failures other than the name-collision case. LLM errors, schema-violation retries, and decode failures SHALL be caught and recorded as `status: "llm_error"` on the affected company; the batch continues.

#### Scenario: One LLM failure does not abort batch

- **WHEN** the third company's disambiguation call times out after retries
- **THEN** companies one, two, four, ... still produce their files; company three gets a file with `status: "llm_error"`

### Requirement: Execution Modes

The stage SHALL support three modes per `pipeline-architecture`:

1. **CLI**: `python -m pipeline.fact_extraction` reads `data/content-collection/` and writes `data/fact-extraction/`.
2. **Orchestrator-callable**: programmatic entry point yields output JSON; on-disk behaviour identical to CLI.
3. **Dry-run** suppresses writes only (LLM still called). A separate **offline** mode short-circuits LLM calls entirely.

Same input SHALL produce the same output record across all modes.

#### Scenario: CLI run

- **WHEN** `python -m pipeline.fact_extraction` runs with `data/content-collection/` populated
- **THEN** each company directory produces a `data/fact-extraction/<id>.json`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode
- **THEN** no files are written and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made; companies needing LLM resolution receive `status: "empty"` (or the top-ranked candidate when a sole-boost exists)

### Requirement: Out of Scope

The stage SHALL NOT:

- Extract facts other than HQ address (size, founding year, sector tags are deferred).
- Validate or correct addresses against external registers (PDOK, BAG).
- Geocode to lat/long.
- Extract more than one address per company.
- Re-parse raw HTML — the stage consumes only `content-collection` artefacts.
- Match non-Dutch postcode formats via regex (non-NL addresses can come back via the LLM-fallback path).

#### Scenario: Other facts ignored

- **WHEN** input pages contain founding-year or company-size text
- **THEN** the output carries only the address record; no other fact fields appear

#### Scenario: Foreign address through fallback

- **WHEN** the LLM fallback emits a non-NL country (e.g. `country: "BE"`) and no postcode anchor was hit
- **THEN** the record is emitted as the fallback produced it; non-NL countries are not rejected

### Requirement: Operational Pitfalls

The implementation SHALL handle these non-obvious hazards. They are not requirements on observable behaviour but are load-bearing for any re-implementation:

- **LLM JSON-mode code-fences.** Some models emit JSON wrapped in markdown code fences even when JSON mode is requested. Strip a single leading/trailing fence pair before parsing; don't treat fenced output as a schema error.
- **`.env` precedence.** Local `.env` files MUST NOT override an already-exported `OPENROUTER_API_KEY` (CI sets the env var directly). Use `python-dotenv`'s `override=False`.

#### Scenario: Fenced LLM JSON parsed

- **WHEN** the LLM returns its JSON wrapped in `` ```json ... ``` ``
- **THEN** the fences are stripped and the JSON is parsed successfully (no `llm_error` raised)
