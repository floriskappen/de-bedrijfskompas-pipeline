## Context

Address quality was re-investigated on the 123-company verification run after
`harden-content-collection-address-capture`. Two independent problems remain, and a
third is a product-policy question:

1. **Dirty / missing `city`** — `fact_extraction/address.py::_strip_city` takes up to
   40 chars after the postcode and cuts only at `\n , | ( \t`. Reproduced failures:
   `Utrecht • KVK: … • BTW: …`, `Utrecht) is gespecialiseerd …`,
   `MaarsbergenThe Netherlands`, `Amersfoort&nbsp;`, `Amersfoort The Netherlands`,
   and `null` for `Postcode, City` / `Postcode\nCity` / `City\nStreet\nPostcode`.
2. **`exact` misses from house numbers** — `geocoding/address.py::prepare` runs
   `re.sub(r"(?<=\d)[a-zA-Z]+","")` then `\b(\d+)\b`. On `Turbinestraat 8c1` it
   deletes the `c` and fuses `8`+`1` → house number **81**. Verified live against
   PDOK: `postcode:3903LW huisnummer:8` → 13 hits (`exact`); `huisnummer:81` → 0 hits,
   forcing a `postcode_centroid` result. This is the DashData failure.
3. **`city_centroid` pins** — whole-city pins have no map value per the product
   premise, yet the tier is still attempted after a postcode miss.

PDOK's `exact` tier keys on **postcode + house number**, never `city`; cleaning
`city` improves the stored dataset and fallback safety but cannot by itself promote a
`postcode_centroid` to `exact`. The two fixes are therefore independent.

## Goals / Non-Goals

**Goals:**

- Normalize `city` conservatively so common boilerplate, separators, country
  suffixes, and HTML entities no longer leak into or null out the field.
- Extract the correct base house number so suffixed streets (`8c1`, `100a`) can match
  `exact`.
- Remove `city_centroid` so a no-postcode-hit address resolves to `empty`, not a
  city pin.

**Non-Goals:**

- Adding `huisletter` / `huisnummertoevoeging` filters to the PDOK `exact` query —
  the base `huisnummer` already returns the rooftop centroid (verified), so the extra
  filters add query complexity for no pin benefit.
- Recovering addresses with no usable street (e.g. `street: "<br>"`); a missing house
  number legitimately stays at `postcode_centroid`.
- Any change to the LLM fallback, ranking, or surface ordering.
- A global (non-NL) geocoder.

## Decisions

### City normalization pipeline (replaces `_strip_city`)

Order, validated against all reproduced cases (12/12):

1. **HTML-unescape** the post-postcode window first, so `&nbsp;` / `&amp;` become
   real characters before any boundary logic.
2. **Strip leading separators** (`whitespace`, NBSP, `,`, `\n`, `|`). This lets
   `Postcode, City` and `Postcode\nCity` resolve to `City` instead of `null` —
   treating a leading separator as "city follows", not "empty city".
3. **Cut at the first end boundary** in `\n , | ( ) • · ; : – —` and tab. Adds `)`,
   bullets, semicolon, colon, and en/em dashes to the current set.
4. **Cut at a boilerplate label** — `\b(kvk|btw|vat|tel|telefoon|phone|fax|e-?mail|©|
   copyright)\b`, case-insensitive — so `Utrecht KVK: 123` (no bullet) still yields
   `Utrecht`. Label-aware rather than a blanket "first digit" rule, because valid
   Dutch place names can contain digits.
5. **Strip a trailing country suffix**, spaced or fused:
   `\s*(the\s+netherlands|netherlands|nederland)\s*$`, case-insensitive.
   `MaarsbergenThe Netherlands` → `Maarsbergen`.

Decision: the country list is **`{the netherlands, netherlands, nederland}` only** —
bare `NL` and `Holland` are excluded. Stripping a 2-letter trailing token or
`Holland` risks mangling real place names, and a wrong city is worse than a
slightly-suffixed one when a postcode is already present.

### Prior-line city recovery (`City\nStreet\nPostcode`)

When the post-postcode window yields no city, inspect the `before` context: split into
non-empty lines, take the last as street and the second-to-last as the candidate city.
Accept **only** when the street line contains a digit (a real house number) and the
prior line is city-like (`^[A-Za-zÀ-ÿ'’.\- ]{2,40}$`, no digit). Rejects prose,
phone-number lines, and single-line layouts (verified 5/5). Deliberately conservative:
a wrong city is worse than `null` when a postcode already exists.

### House-number extraction (replaces the regex-sub in `geocoding/address.py`)

Take the first run of digits via `re.search(r"\d+", street)`. `8c1` → `8`,
`100a` → `100`, `5-7` → `5`, `34` → `34`. Drops the letter-stripping sub entirely;
the base `huisnummer` is what PDOK indexes suffixed addresses under.

### Remove `city_centroid`

Delete tier 3 from `geocoding/core.py`; `match_quality` enum drops `city_centroid`.
After `exact` and `postcode_centroid` both miss, `status` is `empty`. The geocoding
spec's Tiered Lookup, Output Schema, and Status Tracking lose all `city_centroid`
references and scenarios.

## Risks / Trade-offs

- **Over-trimming a real multi-word city** (e.g. a city containing a stopword) →
  Mitigation: boundaries are punctuation/label/country-anchored, never whitespace or
  hyphen; spaces inside a city (`Bergen op Zoom`, `Den Haag`) survive.
- **Prior-line recovery picks a non-city line** → Mitigation: gated on house-number
  presence + city-like prior line + no digits; falls back to `null` on any doubt.
- **`base huisnummer` returns a neighbouring unit's centroid** rather than the exact
  unit → Mitigation: acceptable — same building footprint, rooftop-level pin; the map
  granularity requirement is postcode-level or better.
- **Removing `city_centroid` loses pins for postcode-less, city-only addresses** →
  Accepted by product decision: whole-city pins are not useful.

## Migration Plan

Pure code change, no data migration. After unit tests pass, re-run
fact-extraction → geocoding on the 123-company set and report city completeness,
`exact`/`postcode_centroid`/`empty` counts, and the reason for every remaining
`postcode_centroid`. Rollback is a straight revert; on-disk dataset is regenerated
each run.

## Open Questions

None — the city-centroid policy (remove entirely), country-suffix scope, and
house-number rule are settled above.
