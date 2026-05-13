## Context

Stage 2 of the pipeline. Reads the upstream JSON record from `data/website-resolution/<id>.json`, fetches a curated subset of the company's website, and writes one markdown file per page (plus a `_meta.json` sidecar) at `data/content-collection/<id>/`.

The job is **collection, not interpretation** — produce clean markdown of the pages most likely to contain durable substance (mission, services, team, contact), capture a few cheap meta-signals (page titles, footer text), and let downstream stages do the LLM work. The downstream consumers are `fact-extraction` (stage 3 — reads markdown + footer for verbatim facts like HQ address) and `content-summarization` (stage 4 — reads markdown to produce the compact prose that stage-5 theme analytics will consume).

Three exploration findings ground the design choices below:

1. **trafilatura intentionally strips footers as boilerplate.** On 5 sampled Dutch sites with addresses visible in the raw HTML, 0/5 had address signals in trafilatura's main output. So we capture `<footer>` text separately.
2. **schema.org / JSON-LD has 24% address coverage** on the 17-company test set, and `trafilatura.extract_metadata()` deliberately ignores schema.org address fields. Not worth a custom JSON-LD pass.
3. **Top-hit-of-bare-name fails for generic companies** is a stage-1 issue, but it bleeds in: companies whose homepage trafilatura yields <100 chars will land in `"thin"` or `"fetch_failed"` status here. Acceptable; the LLM downstream can do nothing useful with a SPA shell either way.

## Goals / Non-Goals

**Goals:**
- For the 17-company test set, the majority of healthy sites land in `status: "ok"` with 3–8 pages collected, headed by `/index.md` plus at least one of `/about.md`, `/contact.md`, or equivalent.
- Reliable per-company isolation: one bad site cannot poison the batch.
- A `_meta.json` rich enough that `fact-extraction` and `content-summarization` need nothing else from the HTML world.
- The three execution modes mandated by `pipeline-architecture` (CLI, orchestrator-callable, dry-run).

**Non-Goals:**
- JS rendering. SPAs will produce thin output; we accept that for the MVP. A later change can add `playwright` behind a flag.
- Smart link ranking beyond the tier system. No PageRank, no anchor-text scoring, no learned heuristics.
- robots.txt or rate-limit-per-host beyond a simple 1-second inter-page sleep within a single company.
- Caching DDGS/HTTP responses between runs. Add `requests-cache` later if it bites.
- Sitemap parsing. Considered and deferred — adds variance to page count per company without a clear win.

## Decisions

### Module layout

`pipeline/content_collection/` as a Python package:

- `__main__.py` — CLI entry: parses args, loads upstream input, drives `run`, prints summary.
- `core.py` — `process(record, *, out_dir, write) -> dict` (single record) and `run(records, *, write, out_dir, sleep) -> Iterator[dict]` (orchestrator-callable; `write=False` is dry-run).
- `crawl.py` — link extraction from homepage HTML, tier-based URL selection, slug derivation.
- `extract.py` — trafilatura wrapper (markdown + per-page metadata) and footer extractor.
- `fetch.py` — thin `httpx.get` wrapper with timeout + retry policy.

Trafilatura, the link/footer extractors, and the fetcher are each isolated so they can be swapped (e.g. for playwright-backed fetching) without churn elsewhere.

### Seed path tiers (the literal data)

Lives in `crawl.py` as module-level tuples:

```python
TIER_1_PATHS = (  # identity / mission / services — read first
    "/about", "/about-us", "/over-ons", "/over",
    "/who-we-are", "/wie-we-zijn",
    "/company", "/bedrijf",
    "/story", "/ons-verhaal", "/history", "/geschiedenis",
    "/manifesto", "/mission", "/missie", "/vision", "/visie",
    "/values", "/waarden",
    "/what-we-do", "/wat-we-doen",
    "/how-we-work", "/hoe-wij-werken", "/aanpak", "/onze-aanpak",
    "/werkwijze", "/process", "/proces",
    "/services", "/diensten",
    "/products", "/producten",
    "/solutions", "/oplossingen",
    "/platform",
    "/expertise", "/expertises", "/specialisaties",
    "/portfolio", "/our-work", "/ons-werk",
    "/sectors", "/sectoren", "/industries", "/branches",
    "/technology", "/technologie", "/research", "/onderzoek",
    "/culture", "/cultuur",
    "/impact", "/sustainability", "/duurzaamheid",
)

TIER_2_PATHS = (  # supporting context
    "/cases", "/case-studies", "/projects", "/projecten",
    "/team", "/leadership", "/founders", "/people", "/mensen",
    "/clients", "/klanten", "/customers",
    "/referenties", "/references", "/testimonials",
    "/partners",
    "/locations", "/locaties", "/vestigingen", "/kantoren", "/offices",
    "/careers", "/jobs", "/werken-bij", "/vacatures",
    "/pricing", "/prijzen",
    "/press", "/pers", "/media",
    "/faq", "/veelgestelde-vragen",
    "/contact",
)

TIER_3_PATHS = (  # fresh content — fallback only
    "/blog", "/nieuws", "/news", "/actueel", "/updates",
    "/insights", "/inzichten", "/articles", "/artikelen",
)
```

Matching is path-prefix, case-insensitive, trailing-slash-insensitive. A real link of `/about-us/our-story` matches `/about-us`. Selection order: homepage + tier-1 matches (in TIER_1_PATHS list order) + tier-2 matches + tier-3 only when total would otherwise drop below 3. Hard cap at 8 URLs total.

### Trafilatura settings

```python
trafilatura.extract(
    html,
    output_format="markdown",
    include_comments=False,
    include_tables=True,
    include_images=False,
    include_links=False,
    include_formatting=True,
    deduplicate=True,
    favor_precision=True,
)
```

`favor_precision=True` is the de-marketing-ify lever — trafilatura will drop borderline blocks rather than keep them. We accept a higher false-negative rate on content to get a lower false-positive rate on boilerplate.

Per-page metadata via `trafilatura.extract_metadata(html).as_dict()` — keep `title`, `description`, `sitename` only. The rest (`author`, `tags`, `image`, `date`) is captured if present but considered low-priority; the `_meta.json.pages` schema is non-strict.

### Footer extraction

Use `lxml.html` (or `BeautifulSoup` with `lxml` parser) to find `<footer>` elements, take `.text_content()` joined with newlines, normalize whitespace. Run this on the homepage HTML before trafilatura. Store as a single string in `_meta.json.footer_text`.

If multiple `<footer>` elements exist, concatenate them (some sites have a main-site footer plus a sub-footer). If none exist or the text is empty after stripping, store `null`.

### Slug derivation

```python
def slugify_path(url_path: str) -> str:
    # Strip query and fragment
    path = url_path.split("?", 1)[0].split("#", 1)[0]
    # Strip leading/trailing slashes
    path = path.strip("/")
    if not path:
        return "index"
    # Internal slashes → hyphens
    path = path.replace("/", "-")
    # Slugify (lowercase, ASCII, hyphenated)
    return slugify(path)
```

Examples:
- `https://acme.example/` → `index`
- `https://acme.example/about-us` → `about-us`
- `https://acme.example/about/team` → `about-team`
- `https://acme.example/over-ons/` → `over-ons`
- `https://acme.example/about?lang=en#section` → `about`

### Politeness

Sequential per-page within one company. `time.sleep(1.0)` between consecutive page fetches (configurable). No inter-company sleep — by the time the next company is fetched we're on a different host. No `robots.txt` parsing in the MVP.

### Test strategy

- `tests/test_content_collection.py`:
  - **Offline**: mock `fetch.get` and `_search.search` equivalents with canned HTML fixtures. Verify link extraction, tier ranking, slug derivation, footer parsing, trafilatura wiring, `_meta.json` shape, slug collisions, sub-threshold drops.
  - **Network** (`@pytest.mark.network`): run end-to-end against `test-set/companies-medium.json` (14 companies). Assert: ≥70% land in `status: "ok"`, every successful company has `index.md`, every company has a `_meta.json`. The threshold is a smoke check — we're not asserting precise page counts because real sites change.

### Dry-run mechanics

Mirrors `website-resolution`: `run(records, *, write=False, out_dir=...)` always processes and yields results; the only difference under `write=False` is that no files are written to disk. The yielded `dict` is the same `_meta.json` payload the file-mode path would have persisted.

## Risks / Trade-offs

- **trafilatura missing useful content** → Mitigation: footer capture covers the common HQ-address miss. Other misses are accepted as fact-extraction's problem in stage 3.
- **Slug collisions** when two URLs slugify to the same name (e.g. `/about?lang=en` and `/about?lang=nl` both → `about`) → Mitigation: dedupe selected URLs by slug before fetching; first one wins. Recorded in `urls_attempted`.
- **Same-company-id collision across runs** with different `name` → Mitigation: the same defense as stage 1. Refuse to overwrite an `_meta.json` whose stored `name` differs from the current record's name; raise.
- **Tier-1 path list bias toward Western/B2B vocabularies** → Mitigation: editable list at the top of `crawl.py`. Accept the bias for the MVP; revisit when test set diversifies.
- **JS-heavy sites yielding thin output** → Mitigation: `"thin"` status surfaces them visibly. A later change can add `playwright` behind a flag without changing the contract.

## Open Questions

- **What's a sensible "minimum extracted markdown length"?** Picked 100 characters by gut. May want to revisit after seeing the medium test-set results — sites that have one-line landing pages will all fall into `"thin"` currently.
- **How does this stage handle non-200 HTTP status codes that still return HTML?** Soft-404 pages, paywalled previews, etc. Initial behavior: treat them like normal pages (trafilatura will produce whatever it produces; sub-threshold ones will be dropped). Revisit if the medium test set reveals systematic issues.
- **Should we add a per-host TTL cache via `requests-cache`?** Not for the MVP; revisit when running against larger lists.
