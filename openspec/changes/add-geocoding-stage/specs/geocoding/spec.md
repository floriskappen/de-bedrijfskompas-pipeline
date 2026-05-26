## ADDED Requirements

### Requirement: Input Record Shape

The stage SHALL read each company's input from `data/fact-extraction/<company-id>.json`. Load-bearing keys are `name`, `website`, `status`, and `address` (`street`, `postcode`, `city`, `country`); all other input keys SHALL be carried through verbatim so downstream stages can join on company identity.

If the fact-extraction `status` is not a success status (`regex_single`, `regex_disambiguated`, `llm_fallback`) — i.e. is `empty`, `upstream_failed`, or `llm_error` — the stage SHALL emit `status: "upstream_failed"` without any HTTP call.

#### Scenario: Upstream success proceeds

- **WHEN** the fact-extraction record has `status: "regex_single"` and a populated `address`
- **THEN** the stage proceeds to attempt PDOK lookup

#### Scenario: Upstream non-success cascades

- **WHEN** the fact-extraction record has `status: "upstream_failed"` (or `empty` / `llm_error`)
- **THEN** the stage writes a geocoding record with `status: "upstream_failed"`, `latlng: null`, `match_quality: null`, no HTTP call performed

#### Scenario: Extra input keys preserved

- **WHEN** the fact-extraction record contains `{"name": ..., "website": ..., "source": "incubator-2026-01", ...}`
- **THEN** the geocoding record retains `source` with the same value

### Requirement: Output Schema

For each company the stage SHALL emit a JSON object:

- `name`: string (from input).
- `website`: string or null (from input).
- `latlng`: object `{ "lat": <float>, "lng": <float> }` (WGS84 decimal degrees) or `null`.
- `match_quality`: one of `exact`, `postcode_centroid`, `city_centroid`, or `null`.
- `source`: one of `pdok`, or `null` when no successful lookup occurred.
- `status`: one of `ok`, `empty`, `upstream_failed`, `lookup_error`.

`latlng`, `match_quality`, and `source` SHALL be non-null together (a successful lookup) or null together (any other outcome). Any input-record key not listed above SHALL be carried through verbatim.

#### Scenario: Successful exact hit

- **WHEN** PDOK returns the rooftop address for the company
- **THEN** the record has `latlng: { "lat": 52.0826, "lng": 5.1726 }`, `match_quality: "exact"`, `source: "pdok"`, `status: "ok"`

#### Scenario: All-null when no lookup succeeds

- **WHEN** the stage attempts all three PDOK tiers and every tier returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `source: null`, `status: "empty"`

### Requirement: Address Preparation

The stage SHALL derive the PDOK query inputs from the fact-extraction `address`:

- **Postcode**: the literal `address.postcode` if non-null, with the internal space removed for PDOK (e.g. `"3526 KS"` → `"3526KS"`).
- **House number**: the first integer matched by `\b(\d+)\b` in `address.street` (read left-to-right). Suffix letters and `huisnummertoevoeging` are ignored. If `street` is null or contains no digits, the house number is unavailable.
- **City**: the literal `address.city` if non-null.

The stage SHALL emit `status: "empty"` directly, with no HTTP call, when `country` is non-null and not `"NL"`, or when both `postcode` and `city` are null.

#### Scenario: Postcode space stripped

- **WHEN** the address has `postcode: "3584 DW"`
- **THEN** the PDOK query is built with `postcode:3584DW`

#### Scenario: House number parsed from street

- **WHEN** the address has `street: "Cambridgelaan 771"`
- **THEN** the parsed house number is `771`

#### Scenario: Suffix letter ignored

- **WHEN** the address has `street: "Europalaan 100a"`
- **THEN** the parsed house number is `100`; the suffix letter does not appear in the query

#### Scenario: Non-NL skipped without HTTP

- **WHEN** the address has `country: "BE"`
- **THEN** the record is written with `status: "empty"` and no HTTP request is made

#### Scenario: No usable anchor skipped without HTTP

- **WHEN** the address has `postcode: null` and `city: null`
- **THEN** the record is written with `status: "empty"` and no HTTP request is made

### Requirement: Tiered PDOK Lookup

The stage SHALL query `https://api.pdok.nl/bzk/locatieserver/search/v3_1/free` with strict `fq=` filters in tier order, stopping at the first tier whose response has `numFound > 0`:

1. **`exact`** — requires postcode and house number. Query: `fq=type:adres&fq=postcode:<P>&fq=huisnummer:<N>&rows=1`.
2. **`postcode_centroid`** — requires postcode. Query: `fq=type:postcode&fq=postcode:<P>&rows=1`.
3. **`city_centroid`** — requires city. Query: `fq=type:woonplaats&fq=woonplaatsnaam:<C>&rows=1`.

The successful tier's `match_quality` SHALL be recorded on the output record. Each hit's `latlng` SHALL be parsed from the WKT `centroide_ll` field, which has the form `POINT(<lng> <lat>)` (longitude first); the stored object SHALL be `{ "lat": <lat>, "lng": <lng> }`. The stage SHALL NOT fall back to the `/free?q=...` free-text endpoint; strict `fq=` filtering means a hit is correct by construction.

A tier whose required inputs are unavailable (e.g. `exact` without a parsed house number) SHALL be skipped in favour of the next tier rather than queried with an empty filter value.

#### Scenario: Exact tier hits

- **WHEN** the postcode-and-huisnummer query returns `numFound: 1` with `centroide_ll: "POINT(5.17259687 52.08263581)"`
- **THEN** the record has `latlng: { "lat": 52.08263581, "lng": 5.17259687 }`, `match_quality: "exact"`, no further tiers attempted

#### Scenario: Exact tier falls through to postcode tier

- **WHEN** the postcode-and-huisnummer query returns `numFound: 0` but the postcode-only query returns `numFound: 1`
- **THEN** the record has the postcode hit's `latlng` and `match_quality: "postcode_centroid"`

#### Scenario: Postcode tier falls through to city tier

- **WHEN** both prior tiers return `numFound: 0` but the city-only query returns `numFound: 1`
- **THEN** the record has the city hit's `latlng` and `match_quality: "city_centroid"`

#### Scenario: All tiers empty

- **WHEN** every queried tier returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `status: "empty"`

#### Scenario: Tier skipped when input unavailable

- **WHEN** the address has `postcode: "3526 KS"` but no parsed house number
- **THEN** the `exact` tier is not queried; the stage starts at the `postcode_centroid` tier

### Requirement: Status Tracking

The output `status` field SHALL take exactly one value, each tied to a distinct resolution path:

- `ok` — at least one tier returned a hit; `latlng`, `match_quality`, and `source` are all set.
- `empty` — extraction ran, all queried tiers returned zero, or the address carried no usable anchor / was non-NL; `latlng` is null.
- `upstream_failed` — the upstream fact-extraction record's status was not a success status; no lookup attempted.
- `lookup_error` — an HTTP call to PDOK failed (timeout, non-2xx, unparseable response) after the configured single attempt; `latlng` is null.

#### Scenario: PDOK error distinct from empty

- **WHEN** the PDOK call raises a timeout
- **THEN** the record has `latlng: null`, `match_quality: null`, `status: "lookup_error"`

### Requirement: Output File Layout

The stage SHALL write one file per company at `data/geocoding/<company-id>.json` containing the Output Schema JSON.

A company-id collision with a differing `name` SHALL be treated as a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful write

- **WHEN** company `acme` resolves successfully
- **THEN** `data/geocoding/acme.json` exists with the output JSON

#### Scenario: Name-collision refusal

- **WHEN** `data/geocoding/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Failure Handling

The stage SHALL NOT halt or raise on per-company resolution failures other than the name-collision case. HTTP errors, parse failures, and unexpected response shapes SHALL be caught and recorded as `status: "lookup_error"` on the affected company; the batch continues.

#### Scenario: One PDOK failure does not abort batch

- **WHEN** the third company's PDOK call times out
- **THEN** companies one, two, four, ... still produce their files; company three gets a file with `status: "lookup_error"`

### Requirement: Execution Modes

The stage SHALL support three modes per `pipeline-architecture`:

1. **CLI**: `python -m pipeline.geocoding` reads `data/fact-extraction/` and writes `data/geocoding/`.
2. **Orchestrator-callable**: programmatic entry point yields output JSON; on-disk behaviour identical to CLI.
3. **Dry-run** suppresses writes only (PDOK is still called). A separate **offline** mode short-circuits HTTP entirely; companies that would need a lookup receive `status: "empty"`.

Same input SHALL produce the same output record across all modes (the only difference being whether and where it is persisted).

#### Scenario: CLI run

- **WHEN** `python -m pipeline.geocoding` runs with `data/fact-extraction/` populated
- **THEN** each fact-extraction record produces a `data/geocoding/<id>.json`

#### Scenario: Dry-run yields without writing

- **WHEN** the stage runs in dry-run mode
- **THEN** no files are written and each output record is yielded to the caller

#### Scenario: Offline mode short-circuits HTTP

- **WHEN** the stage runs in offline mode
- **THEN** no HTTP requests are made; companies needing a lookup receive `status: "empty"`

### Requirement: Out of Scope

The stage SHALL NOT:

- Re-parse `content-collection` markdown or HTML to recover an address — it consumes only `fact-extraction` output.
- Geocode non-NL addresses via a global service (Nominatim, Google, Mapbox); non-NL records are emitted as `empty`.
- Reverse-geocode (lat/lng → address) or compute isochrones, routes, or any geometric derivative beyond the centroid `latlng`.
- Persist a cache of PDOK responses across runs; each run re-queries.
- Retry a failed PDOK call beyond the single configured attempt.

#### Scenario: Non-NL not queried globally

- **WHEN** the fact-extraction address has `country: "BE"` and a populated street
- **THEN** no Nominatim/Google lookup is attempted; the record has `status: "empty"`
