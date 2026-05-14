# Proposal: Implement the fact-extraction stage

## Why

`content-collection` (stage 2) reliably surfaces page markdown plus a separately-captured `footer_text` for each company, but downstream consumers (the static front-end, theme analytics) need *structured* facts — HQ address being the canonical one. Today there's nothing between raw markdown and the dataset. The pipeline-architecture spec already places `fact-extraction` at stage 3 (immediately after content-collection, before content-summarization) for this reason: facts must be pulled from verbatim text, not from a lossy summary.

This change implements that stage in its first useful form: structured **HQ address** extraction per company. It's intentionally narrow — one fact type — so the extraction plumbing and the I/O shape can be validated cheaply before scope grows.

## What Changes

- Add pipeline stage 3 (`fact-extraction`): reads `data/content-collection/<id>/_meta.json` + per-page markdown, writes `data/fact-extraction/<id>.json` with a structured address record.
- **Regex-anchored extraction with LLM fallback**, in this order:
  1. Scan `footer_text` and contact/about page markdown for Dutch postal codes (`\d{4}\s?[A-Z]{2}`), capturing surrounding street + city context.
  2. Filter out `Postbus` (PO box) matches — these are mailing addresses, not physical HQs.
  3. Use lexical hints near each match to rank candidates: `bezoekadres` / `hoofdkantoor` / `vestiging` boost; `postadres` deprioritises.
  4. **0 matches** → fall back to a small LLM call on contact/about-page text for layouts that don't expose a postcode verbatim (e.g. "gevestigd aan de Hoofdstraat in Utrecht", addresses split across table cells, etc.).
  5. **1 match** (after filtering) → emit it directly, no LLM call.
  6. **2+ matches** → hand the candidates plus short surrounding context to the same small LLM and ask which is the HQ.
- Address schema: `{ street: str | null, postcode: str | null, city: str | null, country: str | null }`. Each field is independently nullable — sites that don't publish a full address still produce a partial record, never a failure.
- Status field on the output captures **how** extraction resolved, not just success/failure: `"regex_single"` (one match, no LLM), `"regex_disambiguated"` (LLM picked from multiple regex hits), `"llm_fallback"` (no regex hit, LLM extracted from prose), `"empty"` (extraction ran, all fields null), `"upstream_failed"` (no usable content from content-collection), `"llm_error"` (LLM call failed after retries on a path that needed it). This makes per-stage accuracy auditable later without re-running.
- LLM (when invoked) is called via OpenRouter. Model choice and prompt design live in `design.md`; a small/cheap model is the default since the regex pre-filter does the heavy lifting.
- CLI, orchestrator-callable, and dry-run modes per `pipeline-architecture`.

Not in scope (deferred to later changes):
- Company size, founding year, sector tags.
- Address validation / geocoding against a postcode register (e.g. PDOK / BAG).
- Multi-location companies (only the primary HQ is extracted).
- Non-NL addresses. The regex anchor is Dutch-specific; foreign HQs fall to the LLM path or come back `empty`. International support is a later change.
- `libpostal` and other heavyweight address parsers — overkill given the NL-only scope and the postcode anchor.

## Capabilities

### New Capabilities

- `fact-extraction`: extracts structured facts (HQ address in this first cut) from per-company content-collection output using a regex-first, LLM-fallback pipeline, and persists them as a per-company JSON record.

### Modified Capabilities

- `content-collection`: surfaced address-bearing content that `favor_precision` trafilatura strips as boilerplate (office address cards, contact widgets). Three changes, all driven by failure modes uncovered while implementing fact-extraction:
  - **Dual extraction for address-bearing slugs.** Pages with slug ∈ {`contact`, `over-ons`, `about`, `about-us`} now also emit a recall-mode `<slug>.recall.md` alongside the precision-mode `<slug>.md`. fact-extraction reads `.recall.md` when present. Other downstream stages (summarisation, embeddings) keep consuming the precision file — fewer tokens, more signal.
  - **Block-aware footer text.** `<footer>` extraction now preserves block-level element boundaries as newlines (was: bare `text_content()`, which fused inline siblings like `<a>LinkedIn</a><a>Instagram</a>` into `LinkedInInstagram` and stripped the line breaks the postcode-anchor regex relies on for field separation).
  - **Page selection budget and ordering.** URL cap raised from 8 to 12; selection now prioritises top-level paths (e.g. `/contact`) over deeper sub-pages (e.g. `/platform/discover-qualify`) and caps any single tier-path prefix at 2 URLs — without this, a single `/platform`-style sub-tree could monopolise the slate and crowd out the contact page where the address actually lives.

## Impact

- **Code**: new package `pipeline/fact_extraction/` (`__main__.py`, `core.py`, `address.py` for the regex + ranking logic, `llm.py`, `prompt.py`); new dependency on an OpenRouter HTTP client (already have `httpx`). API key via `.env` (`python-dotenv`) or `os.environ`.
- **Cost**: dominated by regex (effectively free). LLM is called only for 0-match and 2+-match cases. Expectation: on the medium test set the majority of companies resolve via `regex_single`, keeping the total LLM spend per full pipeline run well under one cent.
- **Determinism**: the easy-path (`regex_single`) is fully deterministic and reproducible without an API key, which makes local dev and CI runs cheap.
- **Test set**: validated against the 14-company medium set. Spec sets per-status expectations (e.g. ≥ X% of companies whose `footer_text` contains a postcode resolve via `regex_single` with a non-null `postcode`). Thresholds calibrated after the first run.
- **Spec**: brand-new canonical spec at `openspec/specs/fact-extraction/spec.md`. No existing spec modified.
