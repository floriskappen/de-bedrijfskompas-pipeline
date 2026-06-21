## Why

After `harden-content-collection-address-capture`, postcode recall improved but the
extracted `city` is still frequently dirty (boilerplate, bullets, country suffixes,
HTML entities) or wrongly null, and several real addresses geocode only to a
postcode centroid because dirty/missing house numbers defeat PDOK's `exact` tier.
City-only map pins, meanwhile, are not useful to the product yet are still emitted.

## What Changes

- Normalize `city` conservatively in fact-extraction: decode HTML entities; stop at
  bullets/semicolons/dashes/closing-parens and KVK/BTW/VAT/phone/copyright
  boilerplate; strip standalone and fused country suffixes; accept a leading
  separator or recover the next line when forward context has no city; and recover a
  `City\nStreet+houseno\nPostcode` layout only when strongly structured.
- Improve house-number handling for PDOK `exact`: support house-number letters and
  additions (e.g. `8c1`) rather than discarding them, so streets that currently fall
  through to `postcode_centroid` can match exactly.
- **BREAKING** Remove the `city_centroid` geocoding tier. When neither `exact` nor
  `postcode_centroid` succeeds, the record is `status: "empty"` with `latlng: null`.
  `match_quality` loses the `city_centroid` value.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `fact-extraction`: the Postcode Anchor's city-trimming behavior is replaced with
  conservative city normalization (HTML-entity decoding, label/punctuation
  boundaries, country-suffix stripping, leading-separator and prior-line recovery).
- `geocoding`: Address Preparation house-number derivation gains letter/addition
  support for the `exact` query; the Tiered PDOK Lookup, Output Schema
  (`match_quality` enum), and Status Tracking drop the `city_centroid` tier.

## Impact

- `pipeline/fact_extraction/address.py` (`_strip_city`, `_extract_candidates`,
  helpers).
- `pipeline/geocoding/address.py` (house-number preparation) and
  `pipeline/geocoding/core.py` (tier policy — remove tier 3).
- Re-run fact-extraction → geocoding on the 123-company set to report city
  completeness, exact/postcode/empty counts, and every remaining `postcode_centroid`
  reason.
