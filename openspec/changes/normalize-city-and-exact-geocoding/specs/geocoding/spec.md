## MODIFIED Requirements

### Requirement: Output Schema

For each company the stage SHALL emit a JSON object:

- `name`: string (from input).
- `website`: string or null (from input).
- `latlng`: object `{ "lat": <float>, "lng": <float> }` (WGS84 decimal degrees) or `null`.
- `match_quality`: one of `exact`, `postcode_centroid`, or `null`.
- `source`: one of `pdok`, or `null` when no successful lookup occurred.
- `status`: one of `ok`, `empty`, `upstream_failed`, `lookup_error`.

`latlng`, `match_quality`, and `source` SHALL be non-null together (a successful lookup) or null together (any other outcome). Any input-record key not listed above SHALL be carried through verbatim.

#### Scenario: Successful exact hit

- **WHEN** PDOK returns the rooftop address for the company
- **THEN** the record has `latlng: { "lat": 52.0826, "lng": 5.1726 }`, `match_quality: "exact"`, `source: "pdok"`, `status: "ok"`

#### Scenario: All-null when no lookup succeeds

- **WHEN** the stage attempts both PDOK tiers and every tier returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `source: null`, `status: "empty"`

### Requirement: Address Preparation

The stage SHALL derive the PDOK query inputs from the fact-extraction `address`:

- **Postcode**: the literal `address.postcode` if non-null, with the internal space removed for PDOK (e.g. `"3526 KS"` → `"3526KS"`).
- **House number**: the first run of digits matched by `\d+` in `address.street`, read left-to-right. Any trailing letter, separator, or `huisnummertoevoeging` is excluded — only the leading numeric run is taken (e.g. `"8c1"` → `8`, not `81`). PDOK indexes suffixed addresses under this base `huisnummer`, so the base value resolves the rooftop. If `street` is null or contains no digits, the house number is unavailable.
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

#### Scenario: Letter-and-addition suffix reduced to base number

- **WHEN** the address has `street: "Turbinestraat 8c1"`
- **THEN** the parsed house number is `8`, not `81`; the `c` and `1` do not appear in the query

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

The stage SHALL NOT attempt a whole-city (`type:woonplaats`) lookup; a city-only address that lacks a usable postcode resolves to `empty`. The successful tier's `match_quality` SHALL be recorded on the output record. Each hit's `latlng` SHALL be parsed from the WKT `centroide_ll` field, which has the form `POINT(<lng> <lat>)` (longitude first); the stored object SHALL be `{ "lat": <lat>, "lng": <lng> }`. The stage SHALL NOT fall back to the `/free?q=...` free-text endpoint; strict `fq=` filtering means a hit is correct by construction.

A tier whose required inputs are unavailable (e.g. `exact` without a parsed house number) SHALL be skipped in favour of the next tier rather than queried with an empty filter value.

#### Scenario: Exact tier hits

- **WHEN** the postcode-and-huisnummer query returns `numFound: 1` with `centroide_ll: "POINT(5.17259687 52.08263581)"`
- **THEN** the record has `latlng: { "lat": 52.08263581, "lng": 5.17259687 }`, `match_quality: "exact"`, no further tiers attempted

#### Scenario: Exact tier falls through to postcode tier

- **WHEN** the postcode-and-huisnummer query returns `numFound: 0` but the postcode-only query returns `numFound: 1`
- **THEN** the record has the postcode hit's `latlng` and `match_quality: "postcode_centroid"`

#### Scenario: Both tiers empty

- **WHEN** every queried tier returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `status: "empty"`

#### Scenario: City-only address not queried

- **WHEN** the address has `postcode: null` but `city: "Utrecht"`
- **THEN** no PDOK request is made and the record has `status: "empty"`

#### Scenario: Tier skipped when input unavailable

- **WHEN** the address has `postcode: "3526 KS"` but no parsed house number
- **THEN** the `exact` tier is not queried; the stage starts at the `postcode_centroid` tier
