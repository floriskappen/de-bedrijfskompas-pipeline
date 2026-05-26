## Why

The frontend's map view needs a per-company WGS84 lat/lng to drop a pin; `fact-extraction` only resolves the postal address and explicitly carves geocoding out of scope. Folding it back into `fact-extraction` would muddle that stage's regex/LLM contract with an unrelated HTTP lookup. Adding the new stage also forces an existing problem into the open: the current linear "stage 1 … stage 7" labels misrepresent the real dependency graph (e.g. `fact-extraction` and `content-summarization` are siblings, not parent/child), and the orchestrator that's coming next needs the labels to match the DAG.

## What Changes

- Add a new stage `geocoding` that reads `data/fact-extraction/<id>.json`, resolves the address to a WGS84 `latlng` via PDOK Locatieserver (the authoritative free Dutch BAG-backed geocoder, no API key), and writes one JSON record per company at `data/geocoding/<id>.json`. Each record carries `latlng` (or `null`), a `match_quality` of `exact` / `postcode_centroid` / `city_centroid`, and the shared `status` vocabulary (`ok` / `empty` / `upstream_failed` / `lookup_error`). No LLM call. Non-NL addresses and addresses lacking both postcode and city are emitted as `empty`; a global fallback (Nominatim) is deferred until non-NL companies actually appear.
- **BREAKING (label-only, no code behaviour changes).** Renumber the Stage Sequence to match the dependency DAG. The number is the topological wave (longest path from `website-resolution`); the letter is the in-wave id for stages the orchestrator may schedule in parallel. New labels:

  | # | Stage | Depends on |
  |---|---|---|
  | 1 | `website-resolution` | — |
  | 2 | `content-collection` | 1 |
  | 3a | `fact-extraction` | 2 |
  | 3b | `content-summarization` | 2 |
  | 4a | `geocoding` (new, fact-derived) | 3a |
  | 4b | `tagline-extraction` (dossier-derived) | 3b |
  | 4c | `global-scoring` (dossier-derived) | 3b |
  | 5 | `translation` (fan-in) | 4b, 4c (and future 4x dossier-derived) |
  | 6 | `dataset-output` (terminal spine = 3a; left-joins 4a/4b/4c/5) | 3a |

  Stage *names* (= module dir names = capability ids) do not change; only the ordinal labels move. Per-company gating remains driven by each stage's declared dependencies, not by the wave number.
- Modify `pipeline-architecture` Stage Sequence + dependency scenarios to encode the new labels and to introduce the "fact-derived" vs "dossier-derived" framing in place of "stage-5 theme-analytic stages." `geocoding` gates only on `fact-extraction`; `dataset-output`'s hard dependency stays `fact-extraction`.
- Modify `dataset-output` to project `latlng` and `match_quality` at the root of the per-company record (next to `address`), sourced from `data/geocoding/`. Block-level null when geocoding did not produce; `latlng: null` inside a present block when it ran but found nothing.
- Refresh stage-label references in `fact-extraction`, `content-summarization`, and `content-collection` Purpose lines so the canonical specs are internally consistent.
- Refresh stage-label docstrings in each stage's `__init__.py` and the two stage READMEs (`website-resolution`, `content-collection`) as part of implementation.

## Capabilities

### New Capabilities
- `geocoding`: address → WGS84 lat/lng via PDOK, with `match_quality` and the shared failure-status vocabulary; one JSON per company; no LLM.

### Modified Capabilities
- `pipeline-architecture`: insert `geocoding` and adopt the topological wave numbering across the Stage Sequence and its scenarios.
- `dataset-output`: project `latlng` and `match_quality` from `data/geocoding/` at the record root.
- `fact-extraction`: refresh the Purpose stage-label reference (no requirement-behaviour change).
- `content-summarization`: refresh the Purpose stage-label references (no requirement-behaviour change).
- `content-collection`: refresh the Purpose stage-label reference (no requirement-behaviour change).

## Impact

- New module `pipeline/geocoding/` (`__init__.py`, `__main__.py`, `core.py`, `pdok.py`) and new output dir `data/geocoding/<company-id>.json`.
- New runtime dependency: outbound HTTPS to `api.pdok.nl` (no key, no quota in practice). No new Python packages beyond what `website-resolution` already uses for HTTP.
- Spec edits to five canonical specs (one new, four label-only refreshes plus the architecture+dataset-output behaviour edits).
- Code edits to six `__init__.py` docstrings and two READMEs to match the new labels.
- The orchestrator that consumes the architecture spec next will read each stage's declared parent rather than the ordinal label, so the renumbering is a documentation tightening, not a behavioural change.
