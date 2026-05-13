# `website-resolution` — pipeline stage 1

Resolves the canonical website URL for each company. If the input record already has a `website` field, the record passes through unchanged.

## Run

```bash
# Default: read test-set/companies.json, write to data/website-resolution/
python -m pipeline.website_resolution

# Custom input/output
python -m pipeline.website_resolution --input my-list.json --out-dir /tmp/wr

# Dry-run: emit results as JSON Lines to stdout, write nothing
python -m pipeline.website_resolution --dry-run
```

Input is a JSON array of objects with at least `{"name": "..."}`. Extra keys are preserved in the output. Output is one file per company at `<out-dir>/<company-id>.json`.

## Dependencies

- [`ddgs`](https://pypi.org/project/ddgs/) — multi-engine search wrapper. Engine fallback chain (yandex → mojeek → brave) is in `search.py`; region is `nl-nl`.
- [`python-slugify`](https://pypi.org/project/python-slugify/) — `<company-id>` derivation.
- [`tldextract`](https://pypi.org/project/tldextract/) — used by tests for domain comparison.

## Company-ID rule (load-bearing)

`company_id(name)` strips trailing entity suffixes (`B.V.`, `N.V.`, `Holding`, `Holdings` — case-insensitive) then slugifies via `python-slugify`:

- `Land Life Company B.V.` → `land-life-company`
- `Gravity B.V.` → `gravity`
- `Acme Holdings` → `acme`

**Every downstream stage uses these IDs to address files under `data/<stage>/<company-id>.json`.** Changing the rule renames every existing artifact — treat it as a versioned migration, not a refactor.

## Tests

```bash
# Offline only (default)
pytest tests/ -m "not network"

# Network smoke against the real DDGS + real test-set
pytest tests/ -m network
```

The network test strips `website` from each test-set entry, runs the resolver, and asserts each recovered URL matches the test-set's original `website` by registered domain.

## Known limitations

- Top-hit-of-bare-name fails for generic company names (e.g. "Gravity"). Mitigated by yandex's regional ranking; if a future test entry fails, consider appending a country hint to the query.
- No ownership verification (a top hit pointing at the wrong domain is emitted as-is). Deferred to a later stage.
- No same-name disambiguation. Two distinct companies sharing a name will collide on `<company-id>`; the runner raises rather than silently overwriting.
- No on-disk cache of DDGS responses. Add `requests-cache` in `search.py` if rate limits bite.
