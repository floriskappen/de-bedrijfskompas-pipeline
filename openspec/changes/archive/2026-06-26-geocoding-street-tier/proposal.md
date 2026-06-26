## Why

The geocoding stage only queries PDOK by **postcode** (`exact` postcode+huisnummer, then `postcode_centroid`). Companies whose fact-extraction address has a **street + city but no postcode** — or a garbled street that yields the wrong postcode — fail to geocode even when the address is fully resolvable. Example: `amulet` has `Europalaan 100, Utrecht` (no postcode) and gets `status: "empty"`, while `brainial` at `Europalaan 400, 3526 KS` geocodes to the same rooftop. PDOK's `type:adres` index is filterable by `straatnaam` + `huisnummer` + `woonplaatsnaam`, so these addresses are geocodable today with a strict `fq` query — no free-text search, no new data source.

## What Changes

- Add a **street-based PDOK lookup tier** that queries `fq=type:adres&fq=straatnaam:<S>&fq=huisnummer:<N>&fq=woonplaatsnaam:<C>`, returning the adres rooftop. It sits between `exact` and `postcode_centroid` (it is rooftop-precise, more precise than a postcode centroid).
- `address.prepare` SHALL additionally extract `straatnaam` — the street name with the house-number token stripped — alongside the existing `huisnummer`.
- The tier is **skipped** when `straatnaam`, `huisnummer`, or `woonplaatsnaam` (city) is unavailable, falling through to `postcode_centroid` — mirroring the existing "tier skipped when input unavailable" rule.
- Uses strict `fq` filters only; the stage **still SHALL NOT** use the `/free?q=` free-text endpoint. A hit is correct by construction (strict filters ⇒ unambiguous when `numFound > 0`).
- No pipeline data-flow change: the tier consumes only existing fact-extraction `address` fields (`street`, `city`). No scraper-city threading, no new dependencies.
- Does **not** add a city-centroid tier (out of scope: too imprecise for the map UI).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `geocoding`: the "Tiered PDOK Lookup" requirement gains a street-based tier between `exact` and `postcode_centroid`; the "Address Preparation" requirement gains `straatnaam` extraction; the "Output Schema" requirement's `match_quality` gains the `street` value for the new tier.

## Impact

- `pipeline/geocoding/address.py` — extract `straatnaam` in `prepare()`.
- `pipeline/geocoding/pdok.py` — add `street(straatnaam, huisnummer, woonplaatsnaam)` query function.
- `pipeline/geocoding/core.py` — insert the street tier in the lookup order.
- `tests/test_geocoding.py` — cover the street tier (hit, fall-through, skip-when-input-missing, garbled-street extraction).
- No upstream/downstream stage changes; `dataset-output` already projects `match_quality`, so the new `street` value flows through unchanged.
