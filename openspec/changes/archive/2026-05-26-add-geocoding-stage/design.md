## Context

`geocoding` turns the structured address that `fact-extraction` produces into a WGS84 lat/lng the frontend can drop on a map. It mirrors the project's existing stage pattern (self-contained module, on-disk seam, three execution modes, shared failure-status vocabulary) and adds nothing new architecturally — its novelty is a deterministic HTTP lookup against an external geocoder rather than an LLM call. The change also tightens the architecture spec's stage labels into a topological wave numbering (`1`, `2`, `3a/3b`, `4a/4b/4c`, `5`, `6`) so the labels match the DAG the orchestrator will execute.

## Goals / Non-Goals

**Goals:**
- A self-contained module that resolves `data/fact-extraction/<id>.json` addresses to WGS84 lat/lng, with a `match_quality` label so the frontend can vary pin precision.
- Stage labels in `pipeline-architecture` that match the real dependency DAG, so the future orchestrator reads them rather than inventing its own.
- Zero new Python dependencies; outbound HTTPS only to `api.pdok.nl`.

**Non-Goals:**
- Global geocoding (Nominatim, Google, Mapbox). Non-NL addresses are emitted as `empty` until non-NL companies actually appear.
- Reverse geocoding, isochrone overlays, or route planning. These are downstream concerns the frontend (or a future stage) can layer on top of `latlng`.
- A persistent geocoder cache. PDOK is free and fast; we re-run cheap.

## Decisions

**PDOK Locatieserver as the only geocoder in v1.** Free, no API key, no practical rate limit, authoritative for NL (BAG-backed), and returns WGS84 directly so no projection conversion is needed. Alternatives — Nominatim (uneven outside NL, 1 req/s, requires custom User-Agent), Google/Mapbox (paid, key) — were rejected for v1: every meaningful company in the test set is NL. The Nominatim fallback is a clean future extension because the contract (input address → `latlng` + `source` + `match_quality`) is geocoder-agnostic; we record `source: "pdok"` so a later fallback layer is identifiable without spec change.

**Three-tier match strategy via strict `fq=` filters, recorded as `match_quality`.** Tier 1 `exact`: `fq=type:adres&fq=postcode:<P>&fq=huisnummer:<N>` — a hit is the rooftop address by construction, no fuzzy score to interpret. Tier 2 `postcode_centroid`: `fq=type:postcode&fq=postcode:<P>` — street-midpoint within the postcode (≈10 m off rooftop for a single-street postcode in NL). Tier 3 `city_centroid`: `fq=type:woonplaats&fq=woonplaatsnaam:<city>`. Each tier is attempted only if the previous returned `numFound: 0`; all-zero → `status: "empty"`. The frontend uses `match_quality` to pick pin style so a job seeker is never misled into thinking we know the building when we only know the city. Alternative: PDOK's `/free?q=...` free-text endpoint with fuzzy ranking. Rejected — it cross-matches all of NL (test query returned 1057 docs), forcing a round-trip verification step the strict filters make unnecessary. Single `latlng` with no quality label also rejected: rooftop vs city centroid is an order-of-magnitude precision difference and matters for a map UI.

**House-number parsing is a regex pass on `fact-extraction`'s `street`, not a new structured field.** `fact-extraction` already stores `street` as the cleaned human-readable line (e.g. `"Europalaan 100"`); the geocoder extracts the trailing number with `re.search(r"\b(\d+)\b", street)` reading right-to-left, ignoring suffix letters (PDOK's `huisnummer` field is the bare integer; `huisletter` / `huisnummertoevoeging` are separate fields we don't need for centroid-quality pinning). Alternative: extend `fact-extraction`'s output schema to carry `house_number` as its own field. Rejected — it leaks a downstream consumer's parsing concern into an upstream stage; the regex is local and cheap, and a parse miss simply falls through to the postcode tier.

**No retries beyond a single timeout, no cache.** PDOK is free and fast; one HTTPS call per company per run is fine. A timeout (default 5s) failure becomes `status: "lookup_error"` and the batch continues, matching the shared failure-propagation contract. Alternative: tenacity-style retries + on-disk cache. Rejected — premature; both can be added without spec change if pain shows up at scale.

**Topological wave numbering (`number = wave, letter = wave-mate`).** The current "stage 1 … stage 7" labels lie about the DAG (e.g. `fact-extraction`'s and `content-summarization`'s "3 then 4" suggests a dependency that doesn't exist). The new scheme makes the parallelism explicit, which is what an orchestrator will scan first. Alternative hierarchical labels (`3a.1` for "child of 3a") were rejected — they encode parentage twice (once in the dependency declaration, once in the label) and get unreadable past two depths. Letters denote wave-mates, not shared parents; per-company gating is driven by each stage's declared dependencies, never by the label.

**`dataset-output` joins `geocoding` block-level-null.** Same projection discipline already in place for `scores` and `nl`: a missing/non-success geocoding file blanks the whole `latlng` block, while a present block with `latlng: null` means geocoding ran and found nothing. Frontend code therefore distinguishes "not yet geocoded" from "tried, no result." No alternative seriously considered — it's the established pattern.

## Risks / Trade-offs

- **PDOK outage or API change.** → The stage emits `lookup_error`, downstream stages already null-handle a missing block, and a future commit can swap geocoders behind the same contract. No spec change required.
- **`fact-extraction` street parsing edge cases** (`"Europalaan 100, ground floor"`, suffix letters, "Postbus" leakage despite the filter) yield a wrong or missing house number. → Strict `fq=huisnummer:<N>` either matches or returns zero; a zero falls through to `postcode_centroid` with no false `exact` claim. Test the parse against the test set so the fall-through rate is observable.
- **Renumbering churn.** Every canonical spec carrying a stage label moves. → Single PR, mechanical edits, label-only — no behaviour drift. Caught by `openspec validate` before archive.
- **Future stage growth re-shifts labels.** A stage depending on `translation` would push `dataset-output` to wave 7. → Acceptable: labels aren't stable identifiers, stage *names* are. Orchestrator reads declared dependencies.
