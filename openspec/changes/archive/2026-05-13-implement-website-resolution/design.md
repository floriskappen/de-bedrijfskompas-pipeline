## Context

This is the first executable stage of the pipeline and the first production code in the repo. Inputs arrive with at least a company `name` and optionally a `website`; outputs add the resolved `website`. The MVP source is `test-set/companies.json`. Discovery uses the `DDGS` Python library — a free, no-key alternative to paid search APIs (Brave/Serp/Google CSE), which fits a solo-dev budget but trades reliability for cost: results vary by engine and rate limits exist without a proxy. Stage 1 has no upstream stage, so it also has to decide how the source list enters the pipeline and how `<company-id>` is derived.

## Goals / Non-Goals

**Goals:**
- A working stage that recovers the website for the 3 entries in `test-set/companies.json` when their `website` field is stripped.
- Three execution modes per the `pipeline-architecture` Stage Execution Model requirement: standalone CLI, orchestrator-callable function, dry-run.
- Polite, single-process operation — no proxy stack, no paid API key, no parallelism on the search backend.
- Establish the `<company-id>` derivation convention so every later stage can rely on it.

**Non-Goals:**
- Verifying the resolved URL actually belongs to the named company (deferred).
- Disambiguating multiple companies with the same name (deferred).
- Following redirects / fetching the URL (that's `page-fetching`, stage 2).
- A general orchestrator — only the per-stage entry point is in scope here.
- Caching DDGS responses across runs (can be added later if rate limits bite).

## Decisions

### Module layout

`pipeline/website_resolution/` as a Python package, with:

- `__main__.py` — CLI entry: parses args, loads the input list, invokes `run`, writes outputs.
- `core.py` — `resolve(record: dict) -> dict` (single record) and `run(records: Iterable[dict], *, write: bool, out_dir: Path) -> Iterator[dict]` (the orchestrator-callable entry; `write=False` is dry-run mode).
- `search.py` — thin wrapper around DDGS; isolates the library so an alternate backend can be swapped in later without touching `core.py`.

The CLI shells out to `run(..., write=True)`. The orchestrator (later change) imports `run` directly. Tests import `run(..., write=False)`. Behavior parity is enforced by the spec's "Behavior parity across modes" scenario.

**Alternative considered:** a single `pipeline_website_resolution.py` flat module. Rejected — `search.py` isolation is the one thing that needs to be swappable (DDGS reliability is unknown), and a package gives us that seam for free.

### `<company-id>` derivation

Slugify `name` with `python-slugify` (well-maintained, handles unicode and Dutch diacritics). Rules: lowercase, ASCII, hyphen-separated, strip leading/trailing entity suffixes like `B.V.` / `N.V.` / `Holding` before slugification so `Land Life Company B.V.` and `Land Life Company` both produce `land-life-company`.

**Alternative considered:** hash of name. Rejected — opaque IDs make `data/` impossible to navigate by hand, which kills the inspect/debug workflow the on-disk seam contract is supposed to enable.

**Risk:** collisions remain possible (two different companies named "Acme"). Captured as an open question — this stage MUST NOT silently overwrite an existing `data/website-resolution/<id>.json` from a prior run with a different `name`; collision detection lives in `run` and forces a manual decision.

### Stage 1 input source

The `pipeline-architecture` seam contract assumes every stage reads JSON from disk. Stage 1's "upstream" is the source list, so:

- CLI: takes `--input <path>` pointing at a JSON array of records (e.g. `test-set/companies.json`).
- Default `--input` if omitted: `test-set/companies.json` (fine for MVP, replaceable by a flag).

No special "stage 0" is introduced — the source path is just an argument.

### DDGS engine selection

The current `ddgs` package exposes these backends: `brave`, `duckduckgo`, `grokipedia`, `mojeek`, `wikipedia`, `yahoo`, `yandex` (no `google` or `bing`). To pick a reasonable fallback chain we ran each backend against the 3 test-set companies (`Land Life Company B.V.`, `Brainial B.V.`, `Gravity B.V.`) with region `nl-nl` and inspected the top hit:

| Backend | Land Life | Brainial | Gravity |
|---|---|---|---|
| `yandex` | ✓ landlifecompany.com | ✓ brainial.com | ✓ gravity.nl |
| `mojeek` | ✗ blog post | ✓ nl.brainial.com | ✓ gravity.nl |
| `brave` | ✓ landlifecompany.com | ✗ crunchbase | ✗ wikipedia |
| `duckduckgo` / `grokipedia` / `yahoo` | no results | no results | no results |
| `wikipedia` | no results | no results | encyclopedia article |

- **Engine fallback chain**: `["yandex", "mojeek", "brave"]`. Yandex first (3/3 correct on the test set), mojeek as backup (2/3), brave as last resort (1/3 but a different 1 than mojeek, so it catches different failure modes). The other backends are excluded because they returned no useful results.
- **Region**: `nl-nl` (locked by the spec).
- **Query format**: just the raw `name`. Yandex with this query alone passes the test set; query refinement (appending `Nederland`, `site:nl`, etc.) is deliberately *not* added yet — revisit only if a future test-set entry fails.

**Alternative considered:** pick one engine (yandex). Rejected — DDGS engine availability fluctuates and yandex specifically has gotten flaky in the past; a fallback chain is cheap insurance for a 1-line list edit.

### Rate-limit / throughput posture

- **Sequential** processing per record. No threadpool, no asyncio.
- **Sleep**: 1.5s between queries (configurable). Skipped for records that don't trigger a search (i.e. `website` already present).
- **Retry**: on a DDGS exception, sleep 5s, retry once. Second failure → record marked `status: "failed"`. No exponential backoff — this is a 3-company test set, not a 10k crawl.

When the test set grows, revisit: introduce caching, parallelism, or move to a paid backend.

### Dry-run mechanics

`run(records, *, write=False, out_dir=...)`:

- Always processes records and yields outputs.
- When `write=True`, additionally writes each yielded record to `out_dir / f"{company_id}.json"`.
- When `write=False`, never touches the filesystem. Tests collect yielded records into a list and assert against them.

This keeps the side-effect of "writing to disk" as a thin wrapper around a pure generator, which is the cheapest implementation of the three-mode requirement.

### Test strategy

`tests/test_website_resolution.py`:

- Fixture: load `test-set/companies.json`, strip `website` from each entry.
- Test: call `run(stripped, write=False)`, assert that for each output the resolved `website`'s domain matches the original (compare on registered domain via `tldextract`, not exact URL — DDGS may return `https://www.landlifecompany.com/` vs the test-set's `https://landlifecompany.com`).
- Marked `@pytest.mark.network` so the suite can be split into offline vs network tests later.

## Risks / Trade-offs

- **DDGS reliability** → Mitigation: engine fallback chain, single retry, fail-soft per record. If the test set passes <2/3 reliably, escalate to a paid backend.
- **Rate limiting / IP blocks (no proxy)** → Mitigation: 1.5s sleep, sequential only. Acceptable for ≤100 companies; revisit before scaling.
- **Top-hit-is-correct assumption fails for low-SEO companies** → Mitigation: document, defer ownership verification to a later stage. The 3-company test set is the canary — if it breaks on a known-good list, the assumption is wrong.
- **`<company-id>` collisions across different companies** → Mitigation: detect-and-fail in `run`, don't silently overwrite. Surfaces collisions as a manual decision rather than data loss.
- **Slugification rule changes later** → Breaking change for all stored data. Document the rule in `pipeline/website_resolution/core.py` and treat changes to it as a versioned migration.

## Migration Plan

Not applicable — this is a new stage, no existing data to migrate.

## Open Questions

- **Same-name disambiguation**: deferred. Likely needs a follow-up change that introduces either explicit ID input (user-provided) or post-resolution ownership verification.
- **Engine fallback order**: locked at `["google", "bing", "duckduckgo"]` for the MVP; revisit after running the test set a few dozen times.
- **Cache layer**: not in scope. If rate limits bite during development, add a `requests-cache`-style on-disk cache in `search.py` as a follow-up.
