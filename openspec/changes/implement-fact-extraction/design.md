## Context

Stage 3 of the pipeline. Reads `data/content-collection/<id>/_meta.json` + per-page markdown for one company, and writes a structured fact record to `data/fact-extraction/<id>.json`. First fact: **HQ address** (`street`, `postcode`, `city`, `country`, each independently nullable).

The pipeline-architecture spec deliberately places this stage **before** `content-summarization` so that fact extraction sees verbatim text. Summaries are lossy in exactly the way that hurts here — they paraphrase prose and drop "marketing-irrelevant" details like postcodes.

Two grounding observations from `content-collection`:

1. **`_meta.json.footer_text` is the high-yield surface for NL addresses.** trafilatura strips footers by design; content-collection re-captures them precisely so this stage doesn't have to re-parse HTML. On Dutch sites, the footer typically contains the visiting address in canonical postcode form.
2. **Dutch postcodes have a rigid format** (`1234 AB`, four digits + two uppercase letters). That format is rare enough in surrounding prose that a regex match is a near-certain address signal — which makes a regex-first approach viable instead of an LLM-only one.

## Goals / Non-Goals

**Goals:**
- For companies whose `footer_text` contains a Dutch postcode, extract a `{street, postcode, city}` record deterministically, without an LLM call.
- Keep total LLM spend per full pipeline run negligible — the regex path should resolve the bulk of the test set.
- Survive companies where the address is buried in prose, split across markdown cells, or written without a postcode (e.g. "gevestigd in Utrecht"), via a small-LLM fallback on contact/about-page text.
- Produce a useful record even when fields are missing — every populated field is itself useful downstream (city alone enables a map; postcode alone enables PDOK lookup later).
- The three execution modes required by `pipeline-architecture` (CLI, orchestrator-callable, dry-run).

**Non-Goals:**
- International (non-NL) addresses. The regex anchor is NL-specific; foreign HQs are out of scope and fall back to the LLM path or come back `empty`.
- Address validation against PDOK / BAG. Lookup-based correction is a later change.
- Multi-location extraction. One HQ per company; secondary offices ignored.
- Geocoding to lat/long.
- Other facts (size, founding year, sector). Each is a separate change.
- `libpostal`. The C dependency is heavyweight and the NL postcode anchor already disambiguates; not worth it at this scope.

## Decisions

### Resolution paths and the `status` field

`status` doubles as the **resolution-path label**, not just a success/failure flag, because the per-path failure modes are different and worth distinguishing during evaluation:

- `regex_single` — exactly one postcode hit survives filtering; emit directly. Fully deterministic; reproducible without an API key.
- `regex_disambiguated` — multiple hits; LLM picked the HQ from the candidate list. Cheap LLM call with a short, structured prompt.
- `llm_fallback` — zero postcode hits; LLM extracted from prose on contact/about pages. The most expensive path; expected to be the minority.
- `empty` — extraction ran, all fields null. Distinguishes a real "no address published" outcome from upstream/transport failures.
- `upstream_failed` — `content-collection` produced no usable content (`status: "upstream_failed"` or `status: "fetch_failed"`). No extraction attempted.
- `llm_error` — the LLM API call itself failed after retries on a path that needed it. Distinct from `empty`: the data may or may not exist; we just couldn't determine.

This split makes per-path accuracy measurable independently after a run. If `regex_single` is 95% correct but `llm_fallback` is 40%, that's a different remediation than the inverse.

The exact regex, the `Postbus` filter, and the lexical-hint vocabulary (`bezoekadres`, `hoofdkantoor`, `vestiging`, `postadres`) are **load-bearing** for a re-implementer and live in the spec, not here.

### Module layout

`pipeline/fact_extraction/` as a Python package:

- `__main__.py` — CLI entry: arg-parses, loads inputs from `data/content-collection/`, drives `run`, prints summary.
- `core.py` — `process(meta, pages, *, out_dir, write) -> dict` (single company) and `run(records, *, write, out_dir) -> Iterator[dict]` (orchestrator-callable; `write=False` is dry-run).
- `address.py` — postcode regex, candidate extraction with surrounding context, `Postbus` filter, lexical-hint ranking. Pure functions, no I/O. The bulk of the deterministic logic lives here so it can be exercised by offline tests.
- `llm.py` — thin OpenRouter HTTP wrapper (`httpx`), structured-output coercion, retry policy.
- `prompt.py` — the two prompts: (a) disambiguation prompt over a candidate list, (b) prose-extraction prompt for the fallback path.

Address logic and LLM logic are split so the regex path is independently testable and the LLM path can be mocked in tests by patching `llm.call`.

### LLM choice and call shape

OpenRouter via `httpx`, not an SDK. Default model: a small/cheap one (Haiku 4.5 / Gemini Flash / GPT-4o-mini class). Model id is configurable via env (`FACT_EXTRACTION_MODEL`) so the cheap default can be raised for spot evaluation without code changes.

Two call patterns:

- **Disambiguation** receives a short JSON candidate list (`[{street, postcode, city, surrounding_context}]`, ≤5 entries, context capped at ~200 chars each) and is asked to return the index of the HQ plus optional field corrections. Token budget per call: low hundreds.
- **Prose fallback** receives the homepage `footer_text` (if non-null) + contact/about-page markdown trimmed to ~2000 characters total, and is asked to emit the same address schema or nulls. Token budget per call: a few thousand at most.

Both calls use structured JSON output and validate against a pydantic schema before persisting. On schema violation: one retry with a stricter "respond with valid JSON matching this schema" reminder, then `llm_error`.

API key from `OPENROUTER_API_KEY` env var; `python-dotenv` for local `.env` loading.

### Input selection

For each company:

1. Always read `_meta.json.footer_text` if non-null. This is the primary regex surface.
2. Read `contact`, `over-ons`, `about`, `about-us` page content in that order if present (matches the slug conventions from content-collection). For each slug, prefer the recall-mode markdown (`<slug>.recall.md`) when content-collection emitted one; otherwise fall back to the precision-mode `<slug>.md`. These are the secondary regex surface and the **only** surface for the prose-fallback path.
3. Do not load all collected pages — irrelevant pages dilute the regex hit rate (e.g. a postcode in a customer testimonial) and inflate the LLM token bill on the fallback path.

If `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`, skip extraction entirely and emit `status: "upstream_failed"`.

### Why content-collection grew dual extraction

`favor_precision=True` is the right default for summarisation — fewer tokens, higher signal — but it classifies structured address blocks (office cards, contact widgets) as boilerplate and drops them, which is exactly the data this stage needs. Two alternatives were rejected: (a) switching all of content-collection to `favor_recall=True` would bloat tokens for every downstream LLM call, and (b) parsing raw HTML inside fact-extraction would duplicate fetch state and put HTML-parsing logic in a fact stage. The chosen path — emit both `.md` (precision) and `.recall.md` (recall) for the four address-bearing slugs only — keeps the cost of dual extraction proportional to its benefit and lets each consumer pick its own trade-off via filename.

### Why footer text is block-aware

`lxml`'s `text_content()` concatenates descendant text with no separator, fusing inline siblings (`<a>LinkedIn</a><a>Instagram</a>` → `LinkedInInstagram`) and stripping the line breaks the HTML author placed between address fields. The postcode anchor relies on `\n` (and `|`) as field separators when slicing 80 chars of pre-context and 40 chars of post-context: without those separators, the slice swallows neighbouring nav links and email addresses, producing technically-correct postcode hits with garbage street/city fields. The fix — a tree walk that emits `\n` at block-element boundaries and `" "` at inline boundaries, followed by per-line whitespace normalisation — is small, contained, and recovers the structural information that the HTML always carried.

### Dry-run mechanics

Same shape as `content-collection`: `run(records, *, write=False)` always yields the would-be JSON payload; `write=False` suppresses disk writes only. Dry-run still hits the LLM by default (the call is part of "normal processing"); a separate `--offline` flag short-circuits LLM calls and is used only for tests that want to assert the regex path in isolation.

### Hint-window boundary

The hint window (60 chars each side of a candidate) stops at the nearest **single newline**, not a double-newline. The original assumption was that `\n\n` (paragraph break) would be the natural field separator, but in practice Dutch footers are densely packed on a single line or use single newlines between address entries — so a double-newline cap is too wide and causes hint labels from one address to bleed into an adjacent candidate's window. Single-newline cap keeps each hint tightly associated with the address line it appears on.

### Test strategy

- **Offline** (`tests/test_fact_extraction.py`): exercise `address.py` directly with fabricated footer-text fixtures covering:
  - Single clean postcode → `regex_single`.
  - Postbus-only footer → filter strips it; falls through to LLM fallback (mocked) or `empty`.
  - Postbus + bezoekadres → bezoekadres wins via hint ranking; deterministic, no LLM.
  - Two postcodes, one labelled `hoofdkantoor` → hint ranking picks it; no LLM call.
  - Two postcodes, no hints → goes to disambiguation; LLM call is mocked, assertion is "called with these candidates."
  - No postcode anywhere → goes to fallback; LLM call is mocked.
  - Upstream-failed `_meta.json` → emits `upstream_failed` without calling the LLM.

  Each scenario from the spec maps to a named test in `tasks.md`, per the project's tasks rule.

- **Network** (`@pytest.mark.network`): run end-to-end against `test-set/companies-medium.json` (14 companies), using real `content-collection/` output and the real LLM. Assertions deliberately soft: a target proportion lands in `regex_single`, all companies produce a file, no exceptions escape. Real-LLM tests are gated by `OPENROUTER_API_KEY` presence.

## Risks / Trade-offs

- **Regex false positives** (a postcode appearing in marketing copy unrelated to the HQ — e.g. a case study about a customer). Mitigation: prefer footer hits over body hits in ranking; when both exist, only footer hits feed the `regex_single` path. Body-only hits with no hints get routed to disambiguation rather than emitted directly.
- **LLM hallucinating address fields** on the prose fallback (inventing a postcode from a city name). Mitigation: pydantic schema is strict but doesn't validate postcode format against PDOK — instead, the prompt is explicit that omitted fields must be null, and we re-validate the emitted postcode against the same regex post-hoc; a non-conforming postcode is dropped to null.
- **Companies with a `Postbus`-only footer and an address-less site.** The filter strips the Postbus, the regex finds nothing else, the LLM finds nothing; status is `empty` even though the Postbus is technically a published address. Acceptable — downstream consumers want a physical location, and `empty` is honest.
- **NL-only.** Non-NL HQs (rare in the current scope but real) all route to LLM fallback or come back `empty`. Acceptable for the MVP; a later change can add country-specific regex anchors.
- **Cost variance with corpus shape.** If a future test set is heavy on SPAs or sites without postcodes, the `llm_fallback` share rises and the cost claim weakens. Mitigation: the `status` field makes this visible after one run — easy to detect and budget for.

## Open Questions

- **Token cap on the prose-fallback surface.** Picked ~2000 chars by gut. Likely fine; revisit after the first medium-set run if `llm_error` rate is high due to truncated context or if cost is higher than expected.
- **Country field default.** When postcode + city are extracted via regex on a Dutch-postcode anchor, should `country` default to `"NL"` even though the site never said so? Leaning yes (the regex itself is the evidence) but the spec leaves it nullable so the implementation can adopt either policy without a spec change.
- **Disambiguation prompt: ask for index, or ask for the full record?** Index is cheaper and harder to hallucinate; full record lets the LLM correct OCR-style regex artefacts (e.g. ligature-mangled street names). Default to index; revisit if the medium-set run shows systematic street-field issues.
