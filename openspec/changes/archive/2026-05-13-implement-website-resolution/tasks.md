## Tasks

### Project scaffolding

- [x] Add `pyproject.toml` (or update existing) with runtime deps: `ddgs`, `python-slugify`, `tldextract`. Dev deps: `pytest`.
- [x] Create `pipeline/` and `pipeline/website_resolution/` as Python packages (with `__init__.py`).
- [x] Add `.gitignore` entries for `data/` and `.venv/` if not already covered.

### `search.py` — DDGS wrapper

- [x] Implement `search(query: str) -> str | None` that queries DDGS with region `nl-nl`.
- [x] Implement the engine fallback chain: try `["yandex", "mojeek", "brave"]` in order, return the first engine's top hit. Return `None` only if every engine returned 0 results. (Engine list updated from the original `["google","bing","duckduckgo"]` after probing — see design.md.)
- [x] Wrap each engine call in a single-retry: on exception, sleep 5s then retry once; second failure raises.
- [x] Make the engine list a module-level constant so it can be edited without touching call sites.

### `core.py` — resolver

- [x] Implement `company_id(name: str) -> str`: strip entity suffixes (`B.V.`, `N.V.`, `Holding`, `Holdings`, case-insensitive, with surrounding whitespace), then slugify via `python-slugify`. Lowercased ASCII, hyphen-separated.
- [x] Document the slugification rule in the module docstring; flag changes to it as breaking.
- [x] Implement `resolve(record: dict) -> dict`: validate `name` non-empty, short-circuit when `website` is present, otherwise call `search.search(name)` and assemble the success or failure record per the `Output Record Shape` requirement.
- [x] Implement `run(records: Iterable[dict], *, write: bool, out_dir: Path) -> Iterator[dict]`:
  - For each record: yield `resolve(record)`.
  - Between records that triggered a search: `time.sleep(1.5)`. No sleep when website was already present.
  - On `write=True`: detect collisions — refuse to overwrite an existing `<out_dir>/<id>.json` whose stored `name` differs from the current record's `name`; raise with both names in the message.
  - On `write=True`: write each yielded record as `<out_dir>/<company_id(name)>.json` (UTF-8, 2-space indent).
  - On `write=False`: write nothing; just yield.

### `__main__.py` — CLI

- [x] `python -m pipeline.website_resolution` with flags:
  - `--input <path>` (default: `test-set/companies.json`)
  - `--out-dir <path>` (default: `data/website-resolution/`)
  - `--dry-run` (sets `write=False`; prints output records to stdout as JSON Lines instead of writing)
- [x] On startup, create `--out-dir` if missing (only when not dry-run).
- [x] Print a one-line summary at the end: `N resolved, M failed, K skipped`.

### Tests

- [x] `tests/test_website_resolution.py` (mark `@pytest.mark.network`):
  - Load `test-set/companies.json`, strip `website` from each entry.
  - Call `run(stripped, write=False, out_dir=...)`, collect outputs.
  - For each output, compare resolved URL's registered domain (via `tldextract.extract().top_domain_under_public_suffix`) to the test-set's original URL's registered domain. Assert equal.
- [x] Add an offline test that mocks `search.search` and verifies:
  - Skip behavior when `website` is already present (no call to `search.search`).
  - Failure record shape when `search.search` returns `None`.
  - Extra input keys are preserved in the output.
  - Empty/missing `name` produces a failure record without calling `search.search`.
- [x] Add an offline test for `company_id`: `Land Life Company B.V.` → `land-life-company`; collisions raise in `run` when `write=True`.

### Smoke run

- [x] Run `python -m pipeline.website_resolution --input test-set/companies.json --dry-run` and confirm all three test companies resolve to the expected registered domain. (Confirmed via the network pytest test; CLI dry-run with the unstripped test-set skips all 3 because they already have `website` set, which is the correct behavior.)
- [x] Run once non-dry against `data/website-resolution/` to confirm files land at `data/website-resolution/<company-id>.json`. (Produced `brainial.json`, `gravity.json`, `land-life-company.json`.)

### Documentation

- [x] Add a short `pipeline/website_resolution/README.md` with usage, dependencies, and the slugification rule.
