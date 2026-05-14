## ADDED Requirements

### Requirement: Input Record Shape

The stage SHALL read its input for each company from `data/content-collection/<company-id>/`, consisting of:

- `_meta.json` (always present): the per-company sidecar produced by `content-collection`. Of particular interest are `status`, `footer_text`, and `pages`.
- Per-page markdown files (`<page-slug>.md`): the precision-mode trafilatura extraction; present only when `content-collection` produced them.
- Optional recall-mode markdown files (`<page-slug>.recall.md`): present for address-bearing slugs (`contact`, `over-ons`, `about`, `about-us`) when `content-collection` emitted them. Recall mode retains structured address blocks that precision mode strips as boilerplate.

For each address-bearing slug the stage reads, it SHALL prefer `<slug>.recall.md` when present and fall back to `<slug>.md` when only the precision file exists. The postcode anchor is regex-based and benefits from more surface, not less — precision-mode content commonly omits the very address blocks the anchor needs.

If `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`, the stage SHALL NOT attempt extraction or any LLM call, and SHALL emit a result with `status: "upstream_failed"`.

All other input keys from `_meta.json` (`name`, `website`, and any further upstream fields) SHALL be carried into the output record unchanged so downstream stages can join on company identity without re-reading upstream files.

#### Scenario: Valid content-collection input

- **WHEN** `data/content-collection/acme/_meta.json` has `status: "ok"` and `footer_text: "Europalaan 100, 3526 KS Utrecht ..."` with `index.md`, `about.md`, `contact.md` present
- **THEN** the stage proceeds with extraction using `footer_text` and the listed contact/about pages

#### Scenario: Recall-mode markdown preferred

- **WHEN** both `contact.md` (precision) and `contact.recall.md` (recall) exist in the company directory
- **THEN** the postcode anchor is applied against `contact.recall.md`; `contact.md` is ignored for this company

#### Scenario: Precision markdown used when recall absent

- **WHEN** `contact.md` exists but no `contact.recall.md` does
- **THEN** the postcode anchor is applied against `contact.md`

#### Scenario: Upstream failure propagation

- **WHEN** `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`
- **THEN** no extraction is attempted and the output record has `status: "upstream_failed"`, with `name` and `website` preserved from the input

#### Scenario: Extra input keys preserved

- **WHEN** `_meta.json` contains `{"name": "Acme B.V.", "website": "https://acme.example", "source": "incubator-list-2026-01", ...}`
- **THEN** the output record retains `source` with the same value

### Requirement: Output Schema

For each company, the stage SHALL emit a JSON object with the following shape:

- `name`: string. Copied from input.
- `website`: string or null. Copied from input.
- `address`: object with exactly these fields, each independently nullable:
  - `street`: string or null. Street name plus house number (and optional suffix) as a single string.
  - `postcode`: string or null. When non-null, the value MUST match the Dutch postcode regex (see Postcode Anchor) after normalisation to uppercase with a single space between digits and letters (e.g. `"3526 KS"`).
  - `city`: string or null.
  - `country`: string or null. ISO 3166-1 alpha-2 when set (e.g. `"NL"`).
- `status`: string. One of `"regex_single"`, `"regex_disambiguated"`, `"llm_fallback"`, `"empty"`, `"upstream_failed"`, `"llm_error"` (see Status Tracking).
- `source`: string or null. The resolution-path artefact for audit: for regex paths, the substring of input text that yielded the match (capped at 200 characters); for `llm_fallback`, the model id used; null for `empty`, `upstream_failed`, `llm_error`.

Any input-record key not listed above SHALL be carried through verbatim.

#### Scenario: All fields present

- **WHEN** extraction yields `{street: "Europalaan 100", postcode: "3526 KS", city: "Utrecht", country: "NL"}` via the regex path with one footer hit
- **THEN** the output JSON has `address` populated with those four values and `status: "regex_single"`

#### Scenario: Partial address

- **WHEN** the only signal available is a city name in prose (`"gevestigd in Utrecht"`) and the LLM fallback emits `{street: null, postcode: null, city: "Utrecht", country: "NL"}`
- **THEN** the output JSON has `address.city: "Utrecht"`, all other address fields null, `status: "llm_fallback"`

#### Scenario: No address found via LLM fallback

- **WHEN** no postcode candidates exist and the LLM fallback returns all-null fields
- **THEN** every `address.*` field is null and `status` is `"llm_fallback"` (path label preserved)

#### Scenario: No address found via disambiguation decline

- **WHEN** regex candidates exist but the disambiguation LLM returns null (no plausible HQ)
- **THEN** every `address.*` field is null and `status` is `"empty"`

### Requirement: Postcode Anchor

The stage SHALL detect Dutch postal codes using the regex `\d{4}\s?[A-Z]{2}`, requiring the letter pair to be **uppercase in the source text**. Lowercase letter pairs (e.g. `to`, `in`, `at`) are not matched — they are indistinguishable from prose words and produce false positives (e.g. "launched in 2015 to incredibly…" matching as postcode `2015 TO`). Sites that write their postcode in lowercase fall to the LLM fallback path. The normalised output form is always `"DDDD LL"` uppercase with a single space. Each match anchors a **candidate address** consisting of:

- Up to 80 characters of preceding context (the street + house number surface).
- The matched postcode itself.
- Up to 40 characters of following context (the city surface).

Candidate fields are extracted from the surrounding context using these rules:

- `street`: the trailing fragment of the preceding context, taken up to the first newline or comma boundary working backwards from the postcode. Leading punctuation and whitespace SHALL be stripped.
- `city`: the leading fragment of the following context, taken up to the first newline, comma, or sentence boundary. Leading/trailing whitespace SHALL be stripped.
- `country`: defaults to `"NL"` when the postcode itself was the match anchor (the regex is Dutch-format-specific).

The postcode anchor SHALL be applied to two surfaces, in order: first `_meta.json.footer_text` if non-null, then the concatenation of any address-bearing page content that exists, in this order — `contact`, `over-ons`, `about`, `about-us`. For each slug the recall-mode file (`<slug>.recall.md`) is preferred when present; the precision-mode file (`<slug>.md`) is used as a fallback. Hits found in `footer_text` are tagged as `footer` candidates; hits from page markdown are tagged as `body` candidates.

#### Scenario: Single clean footer hit

- **WHEN** `footer_text` is `"Europalaan 100, 3526 KS Utrecht | KVK 12345678"`
- **THEN** one candidate is produced: `{street: "Europalaan 100", postcode: "3526 KS", city: "Utrecht", country: "NL", surface: "footer"}`

#### Scenario: Lowercase postcode not matched by regex

- **WHEN** the surrounding text contains `"3526 ks utrecht"` (lowercase letters)
- **THEN** no candidate is produced; the company falls to the LLM fallback path

#### Scenario: No-space postcode normalised

- **WHEN** the surrounding text contains `"3526KS Utrecht"`
- **THEN** the candidate's `postcode` is `"3526 KS"` (space inserted)

### Requirement: Candidate Filtering and Ranking

After candidates are produced by the Postcode Anchor, the stage SHALL apply filtering and ranking before deciding the resolution path:

1. **`Postbus` filter** — any candidate whose `street` field (case-insensitive) begins with `Postbus` SHALL be discarded. `Postbus` denotes a Dutch PO box (`postadres`), not a physical visiting address.
2. **Hint-based ranking** — within a window of up to 60 characters before and after each surviving candidate, the stage SHALL scan for these case-insensitive lexical hints and apply them to ordering:
   - **Boosts** (this candidate is the HQ): `bezoekadres`, `hoofdkantoor`, `vestiging`, `vestigingsadres`, `kantooradres`, `hq`.
   - **Demotions** (this candidate is a mailing address, not a physical HQ): `postadres`, `correspondentieadres`, `factuuradres`.
3. **Surface ranking** — `footer` candidates SHALL rank above `body` candidates when boost/demotion tiers are equal.

A single surviving candidate is the `regex_single` path. Multiple surviving candidates feed the disambiguation path; the highest-ranked candidate is presented first but the LLM is still consulted unless a candidate carries a `bezoekadres` / `hoofdkantoor` / `vestiging` boost while no other candidate does, in which case the boosted candidate SHALL be emitted directly with `status: "regex_single"`.

#### Scenario: Postbus stripped

- **WHEN** footer text is `"Postbus 123, 3500 AA Utrecht | Bezoekadres: Europalaan 100, 3526 KS Utrecht"`
- **THEN** the `Postbus 123` candidate is discarded and the `Europalaan 100` candidate is emitted with `status: "regex_single"`

#### Scenario: Boost wins without LLM

- **WHEN** two candidates remain after `Postbus` filtering, and the surrounding text labels exactly one of them `hoofdkantoor`
- **THEN** the boosted candidate is emitted with `status: "regex_single"` and no LLM call is made

#### Scenario: Footer beats body

- **WHEN** one candidate is from `footer_text` and one is from `about.md` body, with no hints either side
- **THEN** the footer candidate ranks first; both still proceed to the disambiguation path

#### Scenario: Postadres demoted

- **WHEN** a candidate is preceded by `Postadres:` within the hint window
- **THEN** that candidate is ranked below any non-demoted candidate; if it is the only candidate it still proceeds (regex_single) but with no `bezoekadres`-class boost

### Requirement: Disambiguation Path

When two or more candidates remain after filtering and no candidate carries a sole `bezoekadres`-class boost, the stage SHALL call a small LLM to choose the HQ candidate. The call SHALL:

- Pass the candidate list as structured JSON, capped at the top 5 candidates by surface+hint ranking, each with `street`, `postcode`, `city`, and up to 200 characters of surrounding context.
- Ask the model to return either an index into the candidate list, or `null` if no candidate plausibly represents the HQ.
- Return the chosen candidate verbatim (no field-level corrections in this first cut) and set `status: "regex_disambiguated"`.
- On `null` response, return all-null fields and `status: "empty"`.

#### Scenario: Two equal candidates resolved

- **WHEN** two footer candidates remain (`Europalaan 100, 3526 KS Utrecht` and `Hoofdstraat 5, 1011 AA Amsterdam`) with no hints
- **THEN** the LLM is called with both candidates and the chosen one is emitted with `status: "regex_disambiguated"`

#### Scenario: LLM declines to pick

- **WHEN** the disambiguation LLM call returns `null` (no candidate is recognisably an HQ)
- **THEN** the output has all address fields null and `status: "empty"`

### Requirement: LLM Fallback Path

When zero candidates survive filtering (or the input contained no postcode-format text), the stage SHALL attempt LLM-based extraction over prose. The call SHALL:

- Receive at most ~2000 characters of concatenated content drawn from `contact.md`, `over-ons.md`, `about.md`, `about-us.md` in that order, truncated as needed. `footer_text` is explicitly excluded: the regex already scanned it in full, and if it yielded no postcode candidates, including it in the LLM surface adds noise without signal.
- Be prompted to emit the address schema (`street`, `postcode`, `city`, `country`) with explicit nulls for unknown fields.
- Have its emitted `postcode` (if non-null) re-validated against the Postcode Anchor regex; a non-conforming value SHALL be dropped to null while preserving other fields.
- Set `status: "llm_fallback"` on success, including the all-null case (the path was taken, the model said nothing was extractable).

The stage SHALL NOT take the LLM fallback path when `_meta.json.status` indicates upstream failure, or when no relevant page content was collected (`contact.md`, `over-ons.md`, `about.md`, `about-us.md` are all absent). In the latter case the stage SHALL emit `status: "empty"` directly without an LLM call.

#### Scenario: Prose-only address extracted

- **WHEN** no postcode matches anywhere, but `contact.md` contains `"Wij zijn gevestigd in het centrum van Utrecht"` and the LLM emits `{street: null, postcode: null, city: "Utrecht", country: "NL"}`
- **THEN** the output records those values with `status: "llm_fallback"`

#### Scenario: Invalid postcode dropped to null

- **WHEN** the LLM fallback emits `{postcode: "3526", city: "Utrecht", ...}` (incomplete postcode)
- **THEN** `postcode` is rewritten to null on output; `city` is retained; `status: "llm_fallback"`

#### Scenario: Fallback yields nothing

- **WHEN** the LLM fallback returns all-null fields
- **THEN** the output has all address fields null and `status: "llm_fallback"` (not `"empty"`) — the path taken is preserved for evaluation

### Requirement: Status Tracking

The output `status` field SHALL take exactly one of these values, each tied to a distinct resolution path:

- `"regex_single"` — exactly one candidate survived filtering (or a sole-boost candidate was selected); no LLM call was made.
- `"regex_disambiguated"` — two or more candidates survived; the LLM picked one.
- `"llm_fallback"` — zero candidates survived; the LLM extracted from prose. Includes the case where the model returned all nulls.
- `"empty"` — extraction ran (regex or LLM-disambiguation), all surviving fields are null. Distinct from `"llm_fallback"` to keep path-attribution intact.
- `"upstream_failed"` — `content-collection`'s status was `"upstream_failed"` or `"fetch_failed"`; no extraction was attempted.
- `"llm_error"` — an LLM call was required by the resolution path but failed after retries (network error, schema-violation retry exhausted, etc.). Address fields are all null.

#### Scenario: Status reflects path, not just outcome

- **WHEN** the LLM fallback returns all-null fields versus the regex disambiguation LLM declining to pick
- **THEN** the former emits `status: "llm_fallback"` and the latter emits `status: "empty"`

#### Scenario: LLM error distinct from empty

- **WHEN** the disambiguation LLM call raises after retries
- **THEN** address fields are all null and `status: "llm_error"`

### Requirement: Output File Layout

The stage SHALL write one file per company at `data/fact-extraction/<company-id>.json` (single-file layout per `pipeline-architecture`). The file content is the JSON object defined in Output Schema.

A company-id collision with a differing `name` SHALL be treated as a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful write

- **WHEN** company `acme` resolves successfully
- **THEN** `data/fact-extraction/acme.json` exists and contains the output JSON

#### Scenario: Name-collision refusal

- **WHEN** `data/fact-extraction/acme.json` already exists with `name: "Acme B.V."` and the current run carries a record with `id: "acme"` but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company resolution failures other than the name-collision case. LLM errors, schema-violation retries, and decode failures SHALL be caught and recorded as `status: "llm_error"` on the affected company; processing SHALL continue with the next company.

#### Scenario: One LLM failure does not abort batch

- **WHEN** processing a batch where the third company's disambiguation call times out after retries
- **THEN** companies one, two, four, ... still produce their files normally; company three gets a file with `status: "llm_error"`

### Requirement: Execution Modes

The stage SHALL be runnable in all three modes mandated by `pipeline-architecture`:

1. **Standalone CLI**: `python -m pipeline.fact_extraction` processes the contents of `data/content-collection/` and writes to `data/fact-extraction/`.
2. **Orchestrator-callable**: a programmatic entry point accepts records and returns/yields the output JSON, with on-disk behaviour identical to CLI mode.
3. **Dry-run / no-write**: invoking with the dry-run option runs the full pipeline (including LLM calls) and yields outputs to the caller without writing to `data/fact-extraction/`. A separate **offline** mode short-circuits LLM calls entirely and is used by tests that assert regex-only behaviour.

Behaviour parity across modes is required: the same input SHALL produce the same output record in CLI, orchestrator, and dry-run modes.

#### Scenario: CLI run

- **WHEN** `python -m pipeline.fact_extraction` is invoked with `data/content-collection/` populated
- **THEN** each company directory produces a corresponding `data/fact-extraction/<id>.json`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode against the same input
- **THEN** no files are written to `data/fact-extraction/` and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits LLM

- **WHEN** the stage runs in offline mode
- **THEN** no LLM calls are made; companies that would have taken a `regex_disambiguated`, `llm_fallback`, or `llm_error` path receive `status: "empty"` (or the regex-only sub-result, e.g. the highest-ranked candidate if a boosted one exists)

### Requirement: Out of Scope

The stage SHALL NOT:

- Extract facts other than the HQ address (company size, founding year, sector tags are deferred to later changes).
- Validate or correct the extracted address against an external register (PDOK, BAG, postal-register lookup).
- Geocode the address into latitude/longitude.
- Extract more than one address per company. Multi-location handling is out of scope.
- Attempt extraction from raw HTML; the stage consumes only the artefacts `content-collection` produces.
- Recognise non-Dutch postal-code formats via regex. Non-NL addresses can be returned by the LLM-fallback path but no anchor-based extraction is provided for them.

#### Scenario: Other facts ignored

- **WHEN** input pages contain founding-year or company-size text
- **THEN** the stage emits only the address record; no other fact fields appear in the output

#### Scenario: Foreign address through fallback

- **WHEN** the LLM fallback emits a non-NL country (e.g. `country: "BE"` with a Belgian city) and no postcode anchor was hit
- **THEN** the record is emitted as the fallback path produced it; the stage does not reject non-NL countries

### Requirement: Operational Pitfalls

The following hazards SHALL be handled by the implementation. They are not requirements on observable behaviour but are load-bearing for any re-implementation.

- **Postcode matches inside email addresses or product codes.** Strings such as `support@1234ab.example` or product SKUs like `1234AB-X` can match the postcode regex. Mitigation: require the postcode match to be preceded by whitespace, punctuation, or start-of-string, and followed by whitespace, punctuation, or end-of-string — not by an alphanumeric continuation.
- **Multi-byte whitespace.** Dutch sites occasionally use non-breaking spaces (` `) between the four digits and two letters of a postcode, or between postcode and city. Treat `\s` as Unicode-whitespace inclusive when matching and when normalising.
- **`Postbus` written as `Postbus`, `Postbus.`, `P.O. Box`, or `Pb.`** Match the filter case-insensitively and tolerate trailing punctuation; do not require an exact `Postbus ` prefix with a trailing space.
- **LLM JSON-mode quirks.** Some OpenRouter models emit JSON wrapped in markdown code fences even when JSON mode is requested. Strip a single leading/trailing code-fence pair before parsing; do not treat fenced output as a schema error.
- **`.env` precedence.** Local `.env` files MUST NOT override an already-exported `OPENROUTER_API_KEY` (CI sets the env var directly). Use `python-dotenv`'s `override=False` setting.

#### Scenario: Postcode in email rejected

- **WHEN** the surface text contains `support@1234ab.example`
- **THEN** no candidate is produced for `1234AB`

#### Scenario: Non-breaking space tolerated

- **WHEN** the surface text contains `"3526 KS Utrecht"` (non-breaking spaces)
- **THEN** the candidate is produced with `postcode: "3526 KS"` and `city: "Utrecht"`

#### Scenario: Fenced LLM JSON parsed

- **WHEN** the LLM returns its JSON wrapped in `` ```json ... ``` ``
- **THEN** the fences are stripped and the JSON is parsed successfully (no `llm_error` raised)
