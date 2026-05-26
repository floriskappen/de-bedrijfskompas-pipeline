# dataset-output Specification

## Purpose
TBD - created by archiving change implement-dataset-output. Update Purpose after archive.
## Requirements
### Requirement: Input Sources

The stage SHALL read its input as the per-company files written by upstream stages, one company at a time, and SHALL NOT call any LLM or perform any network request. The sources it reads are:

- `data/fact-extraction/<company-id>.json` — carries `name`, `website`, `status`, and an `address` object (`street`, `postcode`, `city`, `country`) that MAY be absent.
- `data/geocoding/<company-id>.json` — carries `status`, `latlng` (`{ "lat", "lng" }` or `null`), and `match_quality` (`exact` / `postcode_centroid` / `city_centroid` / `null`).
- `data/global-scoring/<company-id>.json` — carries `status` and `scores.<axis>.{score, evidence, reason.en}` for each axis.
- `data/tagline-extraction/<company-id>.json` — carries `status` and `tagline.en`.
- `data/translation/<company-id>.json` — carries `status` and `translations`, a flat map keyed by dotted target path (`"tagline"`, `"scores.<axis>.reason"`) to `{ "nl": <text> }`.

#### Scenario: No model calls

- **WHEN** the stage processes any company
- **THEN** it produces its record solely by reading upstream files and reshaping them, making no LLM call and no network request

### Requirement: Company Enumeration

The stage SHALL emit exactly one output record for each company that has a `data/fact-extraction/<company-id>.json` file (the enumeration spine). A company with no fact-extraction file SHALL NOT receive a record (it is "not yet run"). The other sources are left-joined: their absence reduces the record to nulls but never removes the company from the output.

#### Scenario: One record per fact-extraction file

- **WHEN** the stage runs over a `data/fact-extraction/` directory containing three companies
- **THEN** it writes exactly three records, regardless of how many of those companies have scoring, tagline, or translation files

#### Scenario: Company absent from the spine is not emitted

- **WHEN** a company has a global-scoring file but no fact-extraction file
- **THEN** the stage writes no record for that company

### Requirement: Output Record Shape

Each record SHALL be a JSON object whose language-neutral data lives at the root and whose translatable text lives under per-locale trees. The five score axes are `substance`, `ecology`, `power`, `embeddedness`, `posture`. The locales are `en` and `nl`. The shape is:

- Root: `company_id`, `name`, `website`, `status`, `address` (object with `street`, `postcode`, `city`, `country`, or `null`), `latlng` (object with `lat` and `lng`, or `null`), `match_quality` (one of `exact`, `postcode_centroid`, `city_centroid`, or `null`), and `scores` (object mapping each axis to `{ score, evidence }`, or `null`).
- `en` / `nl`: each an object `{ tagline, scores }`, where `scores` maps each axis to `{ reason }`; or `null`.

`company_id` SHALL equal the record's filename stem and be derived from `name` via the shared `company_id` helper. Axis `score` is an integer or `null`; `evidence` is one of `well_evidenced`, `partial`, `no_signal` passed through verbatim from global-scoring. `latlng.lat` and `latlng.lng` are WGS84 decimal-degree floats; `latlng` and `match_quality` are non-null together or null together.

#### Scenario: Fully populated record

- **WHEN** a company has successful fact-extraction, geocoding, global-scoring, tagline-extraction, and translation outputs
- **THEN** the record has a non-null `address`, a non-null `latlng` with a `match_quality`, a `scores` object with all five axes carrying `score` and `evidence`, and `en`/`nl` trees each carrying a `tagline` and a per-axis `reason`

#### Scenario: Root holds only language-neutral data

- **WHEN** any record is produced
- **THEN** score numbers, `evidence`, `address`, `latlng`, and `match_quality` appear only at the root, and `tagline` and per-axis `reason` text appear only under the `en`/`nl` trees (numbers and coordinates are never duplicated into the locale trees)

### Requirement: Field Projection

Each output field SHALL be sourced from exactly the following upstream field; the stage performs no other transformation than copying and renaming:

- `name`, `website` ← fact-extraction `name`, `website`
- `address` ← fact-extraction `address` (the whole object) when present and non-null, else `null`
- `latlng` ← geocoding `latlng` (the whole object) when present and non-null, else `null`
- `match_quality` ← geocoding `match_quality` when present and non-null, else `null`
- `scores.<axis>.score`, `scores.<axis>.evidence` ← global-scoring `scores.<axis>.score`, `scores.<axis>.evidence`
- `en.tagline` ← tagline-extraction `tagline.en`
- `en.scores.<axis>.reason` ← global-scoring `scores.<axis>.reason.en`
- `nl.tagline` ← translation `translations["tagline"].nl`
- `nl.scores.<axis>.reason` ← translation `translations["scores.<axis>.reason"].nl`

#### Scenario: Dutch reason resolved by flat dotted key

- **WHEN** the stage fills `nl.scores.substance.reason`
- **THEN** it reads `translations["scores.substance.reason"].nl` from the translation file (a flat dotted key lookup, not a nested traversal)

#### Scenario: latlng and match_quality move together

- **WHEN** geocoding produced a successful record with `latlng: {...}` and `match_quality: "exact"`
- **THEN** both fields are copied to the output record verbatim; they are never split (e.g. `latlng` set with `match_quality: null`)

### Requirement: Block-Level Null Discipline

The record SHALL carry a stable schema: every top-level key is always present. A whole block SHALL be `null` when the stage that produces it yielded no usable output for that company (missing file or non-success status); this is distinct from a `null` value inside a present block. The `en` and `nl` trees SHALL mirror the same axis keys, with individual fields set to `null` when their specific source is absent.

- `scores: null` means global-scoring did not produce; `scores.power.score: null` with `evidence: "no_signal"` means it did and found no signal for that axis.
- `latlng: null` (with `match_quality: null`) means geocoding either did not produce or produced a non-success status; the pair is always set or unset together.
- `nl: null` means translation did not produce; a present `nl` tree with `nl.tagline: null` means translation produced but lacked that field.

#### Scenario: Missing source nulls the whole block

- **WHEN** a company has no global-scoring file (or its status is not a success status)
- **THEN** the record's `scores` is `null` and each present locale tree's `scores` is `null`, while `tagline`, `address`, and `latlng` are unaffected

#### Scenario: Null value inside a present block is preserved

- **WHEN** global-scoring scored a company but recorded `score: null` / `evidence: "no_signal"` for the `power` axis
- **THEN** the record's `scores.power` is `{ "score": null, "evidence": "no_signal" }` and `scores` itself is not null

#### Scenario: Partial translation mirrors keys with nulls

- **WHEN** translation produced Dutch for the scores but not the tagline
- **THEN** `nl` is a present object with per-axis `reason` filled and `nl.tagline` set to `null` (not omitted)

#### Scenario: Geocoding non-success nulls the latlng block

- **WHEN** a company has a geocoding file with `status: "empty"` or `status: "lookup_error"` (or no geocoding file at all)
- **THEN** the record has `latlng: null` and `match_quality: null`; `address` and other blocks are unaffected

### Requirement: Record Status

Each record SHALL carry a `status` drawn from `ok`, `empty`, `upstream_failed`:

- `upstream_failed` — the fact-extraction file is absent or unreadable, so the spine itself is missing.
- `empty` — the fact-extraction file is readable but every payload block (`address`, `latlng`, `scores`, and both taglines) is null, leaving nothing to show.
- `ok` — at least one payload block is non-null.

Status SHALL NOT be gated on any upstream stage's own internal status: a company whose fact-extraction found no address but which has a `latlng` from geocoding, or scores or a tagline, is `ok`.

#### Scenario: Partial company is ok

- **WHEN** a company has scores and a tagline but fact-extraction found no address and geocoding found no latlng
- **THEN** the record has `status: "ok"` with `address: null`, `latlng: null`, and the scores/tagline blocks populated

#### Scenario: Latlng alone is ok

- **WHEN** a company has only a geocoded `latlng` (no address text, no scores, no tagline)
- **THEN** the record has `status: "ok"` with `latlng` populated and every other payload block null

#### Scenario: Shell company is empty

- **WHEN** a company has a fact-extraction file but no address, no latlng, no scores, and no tagline
- **THEN** the record has `status: "empty"` with all payload blocks null

### Requirement: Excluded Content

The record SHALL exclude all non-frontend-facing data. It SHALL NOT contain page HTML or markdown, the content-summarization dossier or any of its body, `footer_text`, `urls_attempted`, sitemap fields, per-stage `model` identifiers, or the intermediate per-stage `status` values of upstream stages.

#### Scenario: Internal artefacts are dropped

- **WHEN** a record is produced for a company whose fact-extraction file contains `footer_text`, `urls_attempted`, and sitemap fields
- **THEN** none of those keys, nor any upstream `model` or upstream `status`, appear anywhere in the record

### Requirement: Output Layout and Execution Model

The stage SHALL write all projected company records into a single JSON file at `data/dataset-output/companies.json` containing a JSON list of company records, and SHALL support the three execution modes: standalone CLI (`python -m pipeline.dataset_output`), an orchestrator-callable entry point with the same input/output contract, and a dry-run mode that performs all logic but writes nothing. The stage SHALL raise a hard error if any duplicate `company_id` values appear in the final aggregated output list.

#### Scenario: CLI writes single aggregated file

- **WHEN** a developer runs `python -m pipeline.dataset_output` with the upstream directories populated
- **THEN** all company records are aggregated and written to `data/dataset-output/companies.json` as a JSON array

#### Scenario: Dry-run writes nothing

- **WHEN** the stage runs in dry-run mode
- **THEN** it produces the same records in memory but writes no file under `data/dataset-output/`

#### Scenario: Company-id collision refuses

- **WHEN** the aggregated record list contains duplicate `company_id` values
- **THEN** the stage raises a `RuntimeError` rather than writing

