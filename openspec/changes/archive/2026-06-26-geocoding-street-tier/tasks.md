## 1. Address preparation — `straatnaam` extraction

- [x] 1.1 In `pipeline/geocoding/address.py`, extend `prepare()` to return `straatnaam`: the `address.street` text up to the parsed house-number token, with the number and any trailing text removed. Reuse the existing `huisnummer` parse so both tiers agree on the number. Yield `None` when `street` is null or the result is empty/whitespace-only.
- [x] 1.2 Add `test_street_name_parsed` — asserts `"Europalaan 100"` → `straatnaam="Europalaan"`, `huisnummer=100` (covers spec scenario *Street name parsed from street field*).
- [x] 1.3 Add `test_garbled_street_yields_street_name` — asserts `"Parnassusweg 793, 1082 LZ, P.O. Box 7895"` → `straatnaam="Parnassusweg"`, `huisnummer=793` (covers *Garbled street still yields street name*).
- [x] 1.4 Confirm existing `test_postcode_space_stripped`, `test_house_number_parsed`, `test_suffix_letter_ignored`, `test_non_nl_skip_reason`, `test_no_anchor_skip_reason` still pass unchanged (scenarios *Postcode space stripped*, *House number parsed*, *Suffix letter ignored*, *Non-NL skipped*, *No usable anchor skipped*).

## 2. PDOK client — `street` query function

- [x] 2.1 In `pipeline/geocoding/pdok.py`, add `street(straatnaam, huisnummer, woonplaatsnaam)` returning `{lat,lng}` or `None`, querying `fq=type:adres&fq=straatnaam:<S>&fq=huisnummer:<N>&fq=woonplaatsnaam:<C>&rows=1` via the existing `_query_pdok` helper. No free-text `q`.
- [x] 2.2 Add `test_street_query_builds_strict_fq` — asserts the PDOK URL is built with the three `fq` filters and no `q` param (offline URL inspection via monkeypatched `_query_pdok`/opener).

## 3. Core — insert the `street` tier

- [x] 3.1 In `pipeline/geocoding/core.py`, insert the `street` tier between `exact` and `postcode_centroid`: call `client.street(straatnaam, huisnummer, city)` only when all three are present and `exact` did not hit; on hit set `match_quality="street"`, `source="pdok"`, `status="ok"` and stop.
- [x] 3.2 Update `test_exact_falls_through_to_street` (rename from `test_exact_falls_through_to_postcode`) — no postcode, `street="Europalaan 100"`, `city="Utrecht"` → `match_quality="street"`, postcode tier not called (covers *Exact tier falls through to street tier*).
- [x] 3.3 Add `test_street_tier_hits_on_garbled_postcode` — `postcode="1008 AB"` (PoBox), `street="Parnassusweg 793"`, `city="Amsterdam"`; exact returns 0, street returns 1 → `match_quality="street"`, `postcode_centroid` not attempted (covers *Street tier hits on garbled postcode*).
- [x] 3.4 Add `test_street_falls_through_to_postcode` — exact and street return 0 (or street skipped), postcode returns 1 → `match_quality="postcode_centroid"` (covers *Street tier falls through to postcode tier*).
- [x] 3.5 Add `test_street_tier_skipped_when_city_missing` — `street="Europalaan 100"`, `city=null` → street tier not called, no `street` request (covers *Street tier skipped when city missing*).
- [x] 3.6 Update `test_both_tiers_empty_yields_empty_status` → `test_all_tiers_empty` — all three tiers return 0 → `status="empty"`, all-null (covers *All tiers empty* + Output Schema *All-null when no lookup succeeds*).
- [x] 3.7 Confirm `test_tier_skipped_when_input_unavailable` still passes with the new tier order (covers *Tier skipped when input unavailable*).
- [x] 3.8 Add `test_successful_street_hit` — full output-shape assertion for a street hit: `latlng` set, `match_quality="street"`, `source="pdok"`, `status="ok"` (covers Output Schema *Successful street hit*).
- [x] 3.9 Confirm `test_exact_tier_hits` still passes (covers *Exact tier hits* + Output Schema *Successful exact hit*).

## 4. Reconcile `city_centroid` removal

- [x] 4.1 Remove `city_centroid` from the `match_quality` allowed set in any assertion/helper and the existing `test_city_only_address_makes_no_request` — city-only still makes no request (street tier needs `straatnaam`+`huisnummer`), so the assertion holds; just ensure no test references the dropped enum value.
- [x] 4.2 Grep `pipeline/` and `tests/` for `city_centroid` to confirm no remaining references.

## 5. Verify end-to-end

- [x] 5.1 Run `pytest tests/test_geocoding.py -m "not network"` — all green.
- [x] 5.2 Run the full offline suite `pytest tests/ -m "not network"` — no regressions.
- [x] 5.3 Live check: delete `data/geocoding/amulet.json` and `data/geocoding/arcadis.json`, re-run the geocoding stage, confirm both now resolve to a rooftop `latlng` with `match_quality="street"`.
