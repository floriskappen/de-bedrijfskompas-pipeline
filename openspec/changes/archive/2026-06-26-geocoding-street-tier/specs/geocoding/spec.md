## MODIFIED Requirements

### Requirement: Output Schema

For each company the stage SHALL emit a JSON object:

- `name`: string (from input).
- `website`: string or null (from input).
- `latlng`: object `{ "lat": <float>, "lng": <float> }` (WGS84 decimal degrees) or `null`.
- `match_quality`: one of `exact`, `street`, `postcode_centroid`, or `null`.
- `source`: one of `pdok`, or `null` when no successful lookup occurred.
- `status`: one of `ok`, `empty`, `upstream_failed`, `lookup_error`.

`latlng`, `match_quality`, and `source` SHALL be non-null together (a successful lookup) or null together (any other outcome). Any input-record key not listed above SHALL be carried through verbatim.

#### Scenario: Successful exact hit

- **WHEN** PDOK returns the rooftop address for the company via the postcode-and-huisnummer query
- **THEN** the record has `latlng: { "lat": 52.0826, "lng": 5.1726 }`, `match_quality: "exact"`, `source: "pdok"`, `status: "ok"`

#### Scenario: Successful street hit

- **WHEN** PDOK returns the rooftop address via the straatnaam-and-huisnummer-and-woonplaatsnaam query
- **THEN** the record has `latlng: { "lat": 52.0642, "lng": 5.1085 }`, `match_quality: "street"`, `source: "pdok"`, `status: "ok"`

#### Scenario: All-null when no lookup succeeds

- **WHEN** the stage attempts every PDOK tier and each returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `source: null`, `status: "empty"`

### Requirement: Address Preparation

The stage SHALL derive the PDOK query inputs from the fact-extraction `address`:

- **Postcode**: the literal `address.postcode` if non-null, with the internal space removed for PDOK (e.g. `"3526 KS"` → `"3526KS"`).
- **House number**: the first integer matched by `\b(\d+)\b` in `address.street` (read left-to-right). Suffix letters and `huisnummertoevoeging` are ignored. If `street` is null or contains no digits, the house number is unavailable.
- **Street name**: the `address.street` text with the parsed house-number token and any text following it removed (e.g. `"Europalaan 100"` → `"Europalaan"`, `"Parnassusweg 793, 1082 LZ, P.O. Box 7895"` → `"Parnassusweg"`). If `street` is null or the result is empty/whitespace-only, the street name is unavailable.
- **City**: the literal `address.city` if non-null.

The stage SHALL emit `status: "empty"` directly, with no HTTP call, when `country` is non-null and not `"NL"`, or when both `postcode` and `city` are null.

#### Scenario: Postcode space stripped

- **WHEN** the address has `postcode: "3584 DW"`
- **THEN** the PDOK query is built with `postcode:3584DW`

#### Scenario: House number parsed from street

- **WHEN** the address has `street: "Cambridgelaan 771"`
- **THEN** the parsed house number is `771`

#### Scenario: Street name parsed from street field

- **WHEN** the address has `street: "Europalaan 100"`
- **THEN** the parsed street name is `Europalaan` and the parsed house number is `100`

#### Scenario: Garbled street still yields street name

- **WHEN** the address has `street: "Parnassusweg 793, 1082 LZ, P.O. Box 7895"`
- **THEN** the parsed street name is `Parnassusweg` and the parsed house number is `793`

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
2. **`street`** — requires street name, house number, and city. Query: `fq=type:adres&fq=straatnaam:<S>&fq=huisnummer:<N>&fq=woonplaatsnaam:<C>&rows=1`.
3. **`postcode_centroid`** — requires postcode. Query: `fq=type:postcode&fq=postcode:<P>&rows=1`.

The successful tier's `match_quality` SHALL be recorded on the output record (`exact`, `street`, or `postcode_centroid` respectively). Each hit's `latlng` SHALL be parsed from the WKT `centroide_ll` field, which has the form `POINT(<lng> <lat>)` (longitude first); the stored object SHALL be `{ "lat": <lat>, "lng": <lng> }`. The stage SHALL NOT fall back to the `/free?q=...` free-text endpoint; strict `fq=` filtering means a hit is correct by construction.

A tier whose required inputs are unavailable (e.g. `exact` without a parsed house number, or `street` without a city) SHALL be skipped in favour of the next tier rather than queried with an empty filter value.

#### Scenario: Exact tier hits

- **WHEN** the postcode-and-huisnummer query returns `numFound: 1` with `centroide_ll: "POINT(5.17259687 52.08263581)"`
- **THEN** the record has `latlng: { "lat": 52.08263581, "lng": 5.17259687 }`, `match_quality: "exact"`, no further tiers attempted

#### Scenario: Exact tier falls through to street tier

- **WHEN** the address has no postcode (so `exact` is skipped) but `street: "Europalaan 100"` and `city: "Utrecht"`, and the street query returns `numFound: 1`
- **THEN** the record has the street hit's `latlng` and `match_quality: "street"`, and the `postcode_centroid` tier is not attempted

#### Scenario: Street tier hits on garbled postcode

- **WHEN** the address has `postcode: "1008 AB"` (a PoBox postcode) and `street: "Parnassusweg 793"` and `city: "Amsterdam"`, the `exact` query returns `numFound: 0`, and the `street` query returns `numFound: 1`
- **THEN** the record has `match_quality: "street"` and the `postcode_centroid` tier (which would resolve the PoBox postcode) is not attempted

#### Scenario: Street tier falls through to postcode tier

- **WHEN** both `exact` and `street` return `numFound: 0` (or `street` is skipped for missing inputs) but the postcode-only query returns `numFound: 1`
- **THEN** the record has the postcode hit's `latlng` and `match_quality: "postcode_centroid"`

#### Scenario: Street tier skipped when city missing

- **WHEN** the address has `street: "Europalaan 100"` but `city: null`
- **THEN** the `street` tier is not queried (a city filter is required to disambiguate); the stage proceeds to `postcode_centroid`

#### Scenario: All tiers empty

- **WHEN** every queried tier returns `numFound: 0`
- **THEN** the record has `latlng: null`, `match_quality: null`, `status: "empty"`

#### Scenario: Tier skipped when input unavailable

- **WHEN** the address has `postcode: "3526 KS"` but no parsed house number
- **THEN** the `exact` tier is not queried; the stage proceeds to the next tier whose inputs are available
