## MODIFIED Requirements

### Requirement: Output Record Shape

Each record SHALL be a JSON object whose language-neutral data lives at the root and whose translatable text lives under per-locale trees. The five score axes are `substance`, `ecology`, `power`, `embeddedness`, `posture`. The locales are `en` and `nl`. The shape is:

- Root: `company_id`, `name`, `website`, `favicon_url` (string or `null`), `status`, `address` (object with `street`, `postcode`, `city`, `country`, or `null`), `latlng` (object with `lat` and `lng`, or `null`), `match_quality` (one of `exact`, `postcode_centroid`, `city_centroid`, or `null`), and `scores` (object mapping each axis to `{ score, evidence }`, or `null`).
- `en` / `nl`: each an object `{ tagline, scores }`, where `scores` maps each axis to `{ reason }`; or `null`.

`company_id` SHALL equal the record's filename stem and be derived from `name` via the shared `company_id` helper. Axis `score` is an integer or `null`; `evidence` is one of `well_evidenced`, `partial`, `no_signal` passed through verbatim from global-scoring. `latlng.lat` and `latlng.lng` are WGS84 decimal-degree floats; `latlng` and `match_quality` are non-null together or null together.

#### Scenario: Fully populated record
- **WHEN** a company has successful fact-extraction, geocoding, global-scoring, tagline-extraction, and translation outputs
- **THEN** the record has a non-null `address`, a non-null `latlng` with a `match_quality`, a `scores` object with all five axes carrying `score` and `evidence`, and `en`/`nl` trees each carrying a `tagline` and a per-axis `reason`

#### Scenario: Root holds only language-neutral data
- **WHEN any record is produced**
- **THEN** score numbers, `evidence`, `address`, `latlng`, and `match_quality` appear only at the root, and `tagline` and per-axis `reason` text appear only under the `en`/`nl` trees (numbers and coordinates are never duplicated into the locale trees)

### Requirement: Field Projection

Each output field SHALL be sourced from exactly the following upstream field; the stage performs no other transformation than copying and renaming:

- `name`, `website` ← fact-extraction `name`, `website`
- `favicon_url` ← fact-extraction `favicon_url` when present and non-null, else `null`
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
