## MODIFIED Requirements

### Requirement: Input Sources

The stage SHALL read its input as the per-company files written by upstream stages, one company at a time, and SHALL NOT call any LLM or perform any network request. The sources it reads are:

- `data/fact-extraction/<company-id>.json` — carries `name`, `website`, `status`, and an `address` object (`street`, `postcode`, `city`, `country`) that MAY be absent.
- `data/geocoding/<company-id>.json` — carries `status`, `latlng` (`{ "lat", "lng" }` or `null`), and `match_quality` (`exact` / `postcode_centroid` / `city_centroid` / `null`).
- `data/global-scoring/<company-id>.json` — carries `status` and `scores.<axis>.{score, evidence, reason.en}` for each axis.
- `data/tagline-extraction/<company-id>.json` — carries `status` and `tagline.en`.
- `data/tagging/<company-id>.json` — carries `status` and `capability_tags` (a list of `{ isco_code, prominence, confidence }` objects, or `null`).
- `data/translation/<company-id>.json` — carries `status` and `translations`, a flat map keyed by dotted target path (`"tagline"`, `"scores.<axis>.reason"`) to `{ "nl": <text> }`.

#### Scenario: No model calls

- **WHEN** the stage processes any company
- **THEN** it produces its record solely by reading upstream files and reshaping them, making no LLM call and no network request

### Requirement: Output Record Shape

Each record SHALL be a JSON object whose language-neutral data lives at the root and whose translatable text lives under per-locale trees. The five score axes are `substance`, `ecology`, `power`, `embeddedness`, `posture`. The locales are `en` and `nl`. The shape is:

- Root: `company_id`, `name`, `website`, `favicon_url` (string or `null`), `status`, `address` (object with `street`, `postcode`, `city`, `country`, or `null`), `latlng` (object with `lat` and `lng`, or `null`), `match_quality` (one of `exact`, `postcode_centroid`, `city_centroid`, or `null`), `scores` (object mapping each axis to `{ score, evidence }`, or `null`), and `capability_tags` (a JSON array of `{ isco_code, prominence, confidence }` objects, or `null`).
- `en` / `nl`: each an object `{ tagline, scores }`, where `scores` maps each axis to `{ reason }`; or `null`.

`company_id` SHALL equal the record's filename stem and be derived from `name` via the shared `company_id` helper. Axis `score` is an integer or `null`; `evidence` is one of `well_evidenced`, `partial`, `no_signal` passed through verbatim from global-scoring. `latlng.lat` and `latlng.lng` are WGS84 decimal-degree floats; `latlng` and `match_quality` are non-null together or null together. Each `capability_tags` entry has an `isco_code` drawn from the fixed tagging vocabulary, a `prominence` of `core`, `supporting`, or `incidental`, and a `confidence` of `high` or `low`, passed through verbatim from tagging.

#### Scenario: Fully populated record

- **WHEN** a company has successful fact-extraction, geocoding, global-scoring, tagline-extraction, tagging, and translation outputs
- **THEN** the record has a non-null `address`, a non-null `latlng` with a `match_quality`, a `scores` object with all five axes carrying `score` and `evidence`, a `capability_tags` array of `{ isco_code, prominence, confidence }` objects, and `en`/`nl` trees each carrying a `tagline` and a per-axis `reason`

#### Scenario: Root holds only language-neutral data

- **WHEN** any record is produced
- **THEN** score numbers, `evidence`, `address`, `latlng`, `match_quality`, and `capability_tags` appear only at the root, and `tagline` and per-axis `reason` text appear only under the `en`/`nl` trees (numbers, coordinates, and capability codes are never duplicated into the locale trees)

### Requirement: Field Projection

Each output field SHALL be sourced from exactly the following upstream field; the stage performs no other transformation than copying and renaming:

- `name`, `website` ← fact-extraction `name`, `website`
- `favicon_url` ← fact-extraction `favicon_url` when present and non-null, else `null`
- `address` ← fact-extraction `address` (the whole object) when present and non-null, else `null`
- `latlng` ← geocoding `latlng` (the whole object) when present and non-null, else `null`
- `match_quality` ← geocoding `match_quality` when present and non-null, else `null`
- `scores.<axis>.score`, `scores.<axis>.evidence` ← global-scoring `scores.<axis>.score`, `scores.<axis>.evidence`
- `capability_tags` ← tagging `capability_tags` (the whole array, verbatim) when present and non-null, else `null`
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

#### Scenario: Capability tags pass through verbatim

- **WHEN** tagging produced a successful record with `capability_tags: [{ "isco_code": "251", "prominence": "core", "confidence": "high" }, ...]`
- **THEN** the output record's `capability_tags` is the same array, copied verbatim, with no reordering, filtering, rollup, or reshaping
