## Why

The pipeline produces rich per-company dossiers but no structured signal for "what kinds of expertise does this company run on" — the most useful axis for a job-seeking UI that wants to surface companies a candidate could plausibly work at. Industry/sector alone misclassifies hybrid companies (e.g. a nature-restoration firm that hires ML and remote-sensing talent). A capability-family tag set, drawn from the existing dossier, fills that gap with a small fixed vocabulary the UI can filter on.

## What Changes

- Add a new dossier-derived analytic stage `tagging` (wave `4d`) that reads each company's `data/content-summarization/<company-id>.md` dossier and emits `data/tagging/<company-id>.json` containing a list of capability tags.
- Each tag is `{ "family": <slug>, "prominence": "core" | "supporting" | "incidental" }`. At most one entry per family. Tier-2 (specific) tags are anticipated in the record shape but not implemented in this change.
- Fix the tier-1 vocabulary to 19 family slugs covering the Dutch economy: `software-engineering`, `data-ai`, `hardware-electronics`, `mechanical-civil-engineering`, `life-sciences`, `earth-environmental-sciences`, `clinical-care`, `design-creative`, `content-media`, `commercial`, `finance-accounting`, `legal-compliance`, `policy-public-administration`, `operations-supply-chain`, `people-org`, `field-trades-operators`, `education-training`, `service-hospitality`, `community-social`.
- LLM client uses `deepseek/deepseek-v4-flash` via OpenRouter (matches the other analytic stages), overridable via `TAGGING_MODEL`.
- Stage follows the established analytic-stage shape: `__main__.py` CLI, `core.py` with `process`/`run`, `llm.py`, `frontmatter.py`, versioned prompt under `prompts/tagging.md`. Self-contained per `[[project_per_stage_self_contained]]`.
- Extend `dataset-output` to left-join `data/tagging/` into the per-company record at the root as `capability_tags` (language-neutral; not a translation target).
- Tagging is **not** an input to `translation` (slugs are language-neutral) and **not** required by `dataset-output`.

Not in scope:
- Sector tags (intentionally skipped; messier vocabulary, no chosen UI use yet).
- Tier-2 specific tags (vocabulary will be designed once UI matching needs crystallize).
- A vocab-state/feedback loop file — vocabulary is hard-coded in the prompt for this change.

## Capabilities

### New Capabilities

- `tagging`: dossier-derived analytic stage that emits a fixed-vocabulary capability-family tag set per company with a prominence qualifier.

### Modified Capabilities

- `pipeline-architecture`: add `tagging` as wave `4d` in Stage Sequence; it depends only on `content-summarization`, is not a translation input, and is left-joined (not required) by `dataset-output`.
- `dataset-output`: add `capability_tags` to the output record's language-neutral root, sourced from `data/tagging/<company-id>.json`, left-joined (null when absent).

## Impact

- **Code**: new `pipeline/tagging/` package (`__init__.py`, `__main__.py`, `core.py`, `llm.py`, `frontmatter.py`); new `prompts/tagging.md`; small additions to `pipeline/dataset_output/` (read tagging file, project field) and to the orchestrator's stage list.
- **Data**: new `data/tagging/<company-id>.json` files. `data/dataset-output/<company-id>.json` and the aggregated `companies.json` gain a `capability_tags` field (additive, ignored by older consumers).
- **Cost**: one extra deepseek call per company on first tagging run; cheap.
- **Tests**: new tests under `tests/tagging/` mirroring the structure used for `tagline_extraction` and `global_scoring`; new fixture-level assertion in dataset-output tests for the new field.
