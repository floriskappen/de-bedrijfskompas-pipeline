## ADDED Requirements

### Requirement: Input Record Shape

The stage SHALL accept input records as JSON objects with the following fields:

- `name` (string, required): the company's display name.
- `website` (string, optional): a URL if already known.
- Any additional keys MUST be carried through to the output unchanged.

Input that lacks a `name` field, or where `name` is empty/whitespace, SHALL be rejected as invalid and recorded as a failed record (see "Failure Handling").

#### Scenario: Valid input with only a name

- **WHEN** the stage receives `{"name": "Acme B.V."}`
- **THEN** the record is accepted for processing and discovery is attempted

#### Scenario: Valid input with website already present

- **WHEN** the stage receives `{"name": "Acme B.V.", "website": "https://acme.example"}`
- **THEN** the record is accepted and discovery is skipped (see "Skip Discovery When Website Present")

#### Scenario: Extra keys preserved

- **WHEN** the stage receives `{"name": "Acme B.V.", "source": "hackernews-2026-01"}`
- **THEN** the output record retains `source` with the same value

#### Scenario: Missing or empty name

- **WHEN** the stage receives `{"website": "https://acme.example"}` or `{"name": ""}`
- **THEN** the record is treated as a failure with `status: "failed"` and an `error` describing the missing name

### Requirement: Skip Discovery When Website Present

When the input record already contains a non-empty `website` field, the stage SHALL NOT issue any search query for that record. The output SHALL be the input record unchanged.

#### Scenario: Pre-resolved record passes through

- **WHEN** input is `{"name": "Acme B.V.", "website": "https://acme.example"}`
- **THEN** the output is `{"name": "Acme B.V.", "website": "https://acme.example"}` with no network calls to the search backend

### Requirement: Discovery via DDGS Search

When `website` is missing, the stage SHALL discover it by issuing a query through the `DDGS` Python library with region set to the Netherlands (`nl-nl`) and SHALL take the URL of the top-ranked result as the resolved website.

#### Scenario: Successful discovery

- **WHEN** input is `{"name": "Land Life Company B.V."}` and DDGS returns at least one result
- **THEN** the output record's `website` field is set to the URL of the top result

#### Scenario: Region is Netherlands

- **WHEN** the stage queries DDGS for any company name
- **THEN** the query SHALL be issued with region `nl-nl`

### Requirement: Output Record Shape

On success, the stage SHALL emit a JSON object containing every key from the input record, with `website` set to the resolved URL (or unchanged if already present). On failure, the stage SHALL emit a JSON object containing every key from the input record plus `website: null`, `status: "failed"`, and an `error` field describing the cause.

#### Scenario: Success output shape

- **WHEN** discovery succeeds for `{"name": "Acme B.V."}` resolving to `https://acme.example`
- **THEN** the output is `{"name": "Acme B.V.", "website": "https://acme.example"}`

#### Scenario: Failure output shape

- **WHEN** discovery returns no results for `{"name": "Nonexistent X"}`
- **THEN** the output is `{"name": "Nonexistent X", "website": null, "status": "failed", "error": "no search results"}`

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-record failures. Errors that affect a single record (no search results, network error, invalid input) SHALL be captured in that record's output and processing SHALL continue with the next record.

#### Scenario: One bad record does not block the rest

- **WHEN** processing a batch where the second record fails
- **THEN** records one and three are still produced normally; record two is produced with `status: "failed"`

#### Scenario: Transient search backend error

- **WHEN** DDGS raises an exception for a particular query
- **THEN** the record is written with `status: "failed"` and an `error` field, and the next record is still processed

### Requirement: Out of Scope

The stage SHALL NOT:

- Verify that the discovered URL actually belongs to the named company (deferred to a future change).
- Follow HTTP redirects, perform HEAD/GET on the resolved URL, or otherwise validate reachability.
- Disambiguate between multiple companies sharing the same name (deferred to a future change).
- Re-rank, filter, or otherwise post-process DDGS results beyond taking the top hit.

#### Scenario: No reachability check

- **WHEN** DDGS returns `https://acme.example` as the top result
- **THEN** the stage emits that URL as-is, regardless of whether it is reachable

#### Scenario: No ownership verification

- **WHEN** DDGS returns a top result whose domain does not appear to match the company name
- **THEN** the stage still emits that URL; no domain/name correlation check is performed
