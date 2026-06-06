## MODIFIED Requirements

### Requirement: Output Record Shape

Each record SHALL be a JSON object whose language-neutral data lives at the root and whose translatable text lives under per-locale trees. The five score axes are `substance`, `ecology`, `power`, `embeddedness`, `posture`. The locales are `en` and `nl`. The shape is:

- Root: `company_id`, `name`, `website`, `favicon_url` (string or `null`), `status`, `address` (object with `street`, `postcode`, `city`, `country`, or `null`), `latlng` (object with `lat` and `lng`, or `null`), `match_quality` (one of `exact`, `postcode_centroid`, `city_centroid`, or `null`), `scores` (object mapping each axis to `{ score, evidence }`, or `null`), `capability_tags` (a JSON array of `{ isco_code, prominence, confidence }` objects, or `null`), `created_at` (ISO 8601 UTC string with second precision, `YYYY-MM-DDTHH:MM:SSZ`), and `updated_at` (same format as `created_at`).
- `en` / `nl`: each an object `{ tagline, scores }`, where `scores` maps each axis to `{ reason }`; or `null`.

`company_id` SHALL equal the record's filename stem and be derived from `name` via the shared `company_id` helper. Axis `score` is an integer or `null`; `evidence` is one of `well_evidenced`, `partial`, `no_signal` passed through verbatim from global-scoring. `latlng.lat` and `latlng.lng` are WGS84 decimal-degree floats; `latlng` and `match_quality` are non-null together or null together. Each `capability_tags` entry has an `isco_code` drawn from the fixed tagging vocabulary, a `prominence` of `core`, `supporting`, or `incidental`, and a `confidence` of `high` or `low`, passed through verbatim from tagging. `created_at` and `updated_at` are always present and never `null`; `updated_at` is greater than or equal to `created_at`.

#### Scenario: Fully populated record

- **WHEN** a company has successful fact-extraction, geocoding, global-scoring, tagline-extraction, tagging, and translation outputs
- **THEN** the record has a non-null `address`, a non-null `latlng` with a `match_quality`, a `scores` object with all five axes carrying `score` and `evidence`, a `capability_tags` array of `{ isco_code, prominence, confidence }` objects, `created_at` and `updated_at` ISO 8601 UTC strings, and `en`/`nl` trees each carrying a `tagline` and a per-axis `reason`

#### Scenario: Root holds only language-neutral data

- **WHEN** any record is produced
- **THEN** score numbers, `evidence`, `address`, `latlng`, `match_quality`, `capability_tags`, `created_at`, and `updated_at` appear only at the root, and `tagline` and per-axis `reason` text appear only under the `en`/`nl` trees (numbers, coordinates, capability codes, and timestamps are never duplicated into the locale trees)

## ADDED Requirements

### Requirement: Record Lifecycle Timestamps

The stage SHALL maintain `created_at` and `updated_at` for each company across runs by persisting per-company sidecar files at `data/dataset-output/timestamps/<company-id>.json`. Each sidecar holds `{ "created_at", "updated_at", "content_hash" }`, where `content_hash` is the SHA-256 (hex) of the record canonicalised with sorted keys and with `created_at`/`updated_at` stripped before hashing.

On every run, for each emitted record:

- If no sidecar exists for the `company_id`, both `created_at` and `updated_at` are set to the current run timestamp, and a sidecar is written with the new `content_hash`.
- If a sidecar exists and the freshly computed `content_hash` equals the stored one, `created_at` and `updated_at` are copied from the sidecar verbatim and the sidecar is not rewritten.
- If a sidecar exists and the `content_hash` differs, `created_at` is copied from the sidecar, `updated_at` is set to the current run timestamp, and the sidecar is overwritten with the new `updated_at` and `content_hash`.

All bumps within a single stage run SHALL use the same current-run timestamp value, captured once at stage start (ISO 8601 UTC, second precision, `YYYY-MM-DDTHH:MM:SSZ`). Sidecars whose `company_id` is no longer in the fact-extraction spine SHALL be left untouched (neither read nor deleted). In dry-run mode no sidecar SHALL be written, but timestamps SHALL still be computed against existing sidecars so the in-memory records match what a real run would produce.

#### Scenario: First time a company is seen

- **WHEN** a company has no `data/dataset-output/timestamps/<company-id>.json` and the stage emits a record for it
- **THEN** `created_at` and `updated_at` in the record are both equal to the run timestamp, and a sidecar is written with that pair and the record's `content_hash`

#### Scenario: Unchanged record preserves both timestamps

- **WHEN** a company's freshly computed `content_hash` equals the stored sidecar `content_hash`
- **THEN** the emitted record's `created_at` and `updated_at` come verbatim from the sidecar, and the sidecar file is not rewritten

#### Scenario: Changed record bumps updated_at only

- **WHEN** a company's freshly computed `content_hash` differs from the stored sidecar `content_hash`
- **THEN** the emitted record's `created_at` is the sidecar's stored value, its `updated_at` is the run timestamp, and the sidecar is overwritten with the new `updated_at` and `content_hash`

#### Scenario: Hash excludes the timestamp fields

- **WHEN** two records differ only in their `created_at` or `updated_at` values
- **THEN** their `content_hash` values are equal

#### Scenario: Single run shares one timestamp

- **WHEN** the stage emits records for multiple companies in a single run and several need their `updated_at` bumped
- **THEN** every bumped `updated_at` in that run is the same ISO 8601 string

#### Scenario: Dry-run does not write sidecars

- **WHEN** the stage runs in dry-run mode against a populated `data/dataset-output/timestamps/` directory
- **THEN** in-memory records carry the same `created_at` / `updated_at` they would in a real run, and no sidecar file is created, modified, or deleted
