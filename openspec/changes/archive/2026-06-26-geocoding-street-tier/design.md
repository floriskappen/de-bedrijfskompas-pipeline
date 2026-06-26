## Context

The geocoding stage (`pipeline/geocoding/`) resolves a fact-extraction address to a lat/lng via PDOK Locatieserver's `/free` endpoint. Today it only queries by **postcode** (`exact` postcode+huisnummer, then `postcode_centroid`). Companies whose address has a street + city but **no postcode** — or a garbled street that yields a wrong postcode (e.g. a PoBox postcode) — fall through to `status: "empty"` even when the address is fully resolvable. PDOK's `type:adres` index is filterable by `straatnaam` + `huisnummer` + `woonplaatsnaam`, validated against real records:

- `amulet` (`Europalaan 100, Utrecht`, no postcode) → `straatnaam:Europalaan&huisnummer:100&woonplaatsnaam:Utrecht` ⇒ `numFound: 1`, rooftop `52.064, 5.108` (identical to `brainial`'s postcode-based exact hit on the same street).
- `arcadis` (`Parnassusweg 793, …`, postcode is a PoBox) ⇒ `numFound: 1`, correct rooftop.

## Goals / Non-Goals

**Goals:**
- Geocode addresses that have a parseable street name + house number + city but no usable postcode, at **rooftop precision** (the `type:adres` doc), with no new data source and no pipeline data-flow change.

**Non-Goals:**
- No city-centroid tier (too imprecise for the map UI — a city pin lands in the wrong spot).
- No free-text `q=` search (see Decision 1).
- No change to upstream fact-extraction address quality; no scraper-city threading.
- No fix to the pre-existing ordinal-street huisnummer edge case (e.g. `2e Industrieweg`).

## Decisions

### Decision 1: strict `fq` filters, not free-text `q`
Query `fq=type:adres&fq=straatnaam:<S>&fq=huisnummer:<N>&fq=woonplaatsnaam:<C>`. **Alternative considered:** free-text `q=<street>, <city>&fq=type:adres` — validated to resolve, but returns `numFound` in the hundreds of thousands (PDOK ranks free-text matches) and violates the existing spec's "SHALL NOT use `/free?q=`; strict `fq` means correct by construction". Strict `fq` keeps a hit unambiguous (`numFound: 1` in tests) and needs no spec-contract override.

### Decision 2: tier ordered `exact` → `street` → `postcode_centroid`
The street tier is rooftop-precise (a `type:adres` doc), so it outranks `postcode_centroid`. Placing it **before** `postcode_centroid` also prevents a garbled/wrong postcode (e.g. arcadis's PoBox `1008 AB`) from producing a misleading postcode centroid. It only runs when `exact` was skipped or returned `numFound: 0`.

### Decision 3: all three anchors required; skip otherwise
The street tier requires `straatnaam` + `huisnummer` + `woonplaatsnaam` (city) all present. Without the city filter, `straatnaam:Europalaan&huisnummer:100` returns 17 hits across NL (ambiguous). Without `huisnummer`, it would return an arbitrary address on the street (false precision). Missing any anchor ⇒ skip the tier (fall through to `postcode_centroid` / `empty`), mirroring the existing "tier skipped when input unavailable" rule.

### Decision 4: `straatnaam` = street text before the house-number token
Extract by taking `address.street` up to the parsed house-number token (reusing the existing `huisnummer` parse so both tiers agree on the number). **Alternative considered:** a dedicated `(?P<name>.*?)\s+(?P<num>\d+)` regex — rejected to avoid diverging from the exact tier's `huisnummer` and risking the ordinal-street edge case differently. If extraction yields an empty `straatnaam` (e.g. street is a bare number or garbage like `"Copyright ©"`), the tier is skipped — safe (no false positive, just no hit).

### Decision 5: new `match_quality: "street"` value
Distinguish the lookup path for observability (street-verified vs postcode-verified), so the frontend/debugging can tell how a coordinate was derived. **Alternative considered:** reuse `exact` (no schema change) — rejected because street-name extraction is slightly lower-confidence than a postcode, and the distinction is worth surfacing. Additive enum value; `dataset-output` projects `match_quality` verbatim, so no downstream change.

## Risks / Trade-offs

- **[Mis-extracted street name → wrong rooftop]** A garbled street that coincidentally matches a real `straatnaam` in the same city could pin incorrectly. → Mitigation: strict `fq` returns `numFound: 0` for non-existent names (falls through, no false hit); the risk is only a *real* wrong-name collision, which is rare and bounded to the extracted-string surface.
- **[Ordinal streets (`2e Industrieweg`)]** The existing `huisnummer` parse grabs the leading ordinal `2` (pre-existing bug); `straatnaam` extraction inherits it and the tier skips. → Mitigation: out of scope; falls through to `postcode_centroid` harmlessly.
- **[Extra PDOK call per company]** One additional HTTP call when `exact` misses. → Mitigation: bounded to the minority without a postcode hit; single attempt, no retry (consistent with existing contract).
