## 1. City normalization (fact-extraction)

- [x] 1.1 Replace `_strip_city` in `pipeline/fact_extraction/address.py` with the conservative pipeline: HTML-unescape → strip leading separators → cut at end boundary (`\n , | ( ) • · ; : – —` + tab) → cut at boilerplate label (`kvk|btw|vat|tel|telefoon|phone|fax|e-?mail|©|copyright`) → strip trailing country suffix (`the netherlands|netherlands|nederland`, spaced or fused; not `NL`/`Holland`)
- [x] 1.2 Add conservative prior-line city recovery in `_extract_candidates`: when the normalized following context yields no city, take the second-to-last non-empty line of the preceding context as city only when the last line (street) contains a digit and the prior line matches `^[A-Za-zÀ-ÿ'’.\- ]{2,40}$` with no digit
- [x] 1.3 Add fact-extraction unit tests for every new Postcode Anchor scenario: leading comma, next-line city, bullet+KVK/BTW, closing paren, label-without-bullet, fused country, spaced country, `&nbsp;` entity, prior-line recovery (positive), and prior-line decline on a digit-bearing line
- [x] 1.4 Confirm existing Postcode Anchor scenarios still pass unchanged (structured/footer/body, no-space, repeated whitespace, line-break, visible-text, email rejection, NBSP)

## 2. Exact-match house number (geocoding)

- [x] 2.1 Replace the house-number derivation in `pipeline/geocoding/address.py::prepare` with first-digit-run extraction (`re.search(r"\d+", street)`), dropping the letter-stripping `re.sub`; `8c1` → `8`
- [x] 2.2 Add geocoding unit tests for `8c1`→8, `100a`→100, `5-7`→5, `771`→771, `34`→34, and `<br>`/no-digit → unavailable

## 3. Remove city_centroid tier (geocoding)

- [x] 3.1 Delete the `city_centroid` tier from `pipeline/geocoding/core.py` so resolution stops after `postcode_centroid`; a no-hit address resolves to `status: "empty"`
- [x] 3.2 Remove the `city_centroid` client call path; if `pdok.city_centroid` becomes unused, delete it
- [x] 3.3 Update geocoding unit tests: drop `city_centroid` cases, add "both tiers empty → empty" and "city-only address makes no HTTP request → empty"

## 4. Verification run

- [x] 4.1 Run the full unit suite (`pytest`, excluding `@pytest.mark.network`) and confirm green
- [x] 4.2 Re-run fact-extraction → geocoding on the 123-company set; report city completeness and suspicious-city count, `exact`/`postcode_centroid`/`empty` counts, and the reason for every remaining `postcode_centroid` — 59/86 success records have a city, 0 suspicious; geocoding exact=54, postcode_centroid=1, city_centroid=0, none=68; only remaining postcode_centroid is StrateGis (`street: "<br>"`, no house number — out of scope)
- [x] 4.3 Confirm DashData resolves to `exact` and the country-suffix/entity leaks (Resono, StrateGis, MaarsbergenThe-Netherlands-shaped cases) are gone — DashData now `exact` (8c1→8); Resono city is `Amersfoort`; no suspicious cities remain

## 5. Close out

- [x] 5.1 Remove the completed follow-up section from `TODO.md`
- [x] 5.2 Run `openspec validate --changes normalize-city-and-exact-geocoding` and verify it passes
