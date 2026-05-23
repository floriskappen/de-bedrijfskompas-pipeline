## Why

The pipeline produces rich per-stage data but nothing the frontend can consume. The static Astro site needs one clean, frontend-facing record per company — the marketing-free facts, tagline, and scores in both languages — without the internal artefacts (raw HTML, the English dossier, footer dumps). This is the declared terminal stage 7; building it closes the pipeline.

## What Changes

- Add the terminal `dataset-output` stage (stage 7): a pure projection that fans in `fact-extraction`, `tagline-extraction`, `global-scoring`, and `translation`, and writes one frontend-facing record per company to `data/dataset-output/<company-id>.json`. It makes no LLM calls.
- **Enumeration spine**: emit one record per company that has a `fact-extraction` file; left-join the analytic + translation outputs where present.
- **Output shape** (hybrid locale-keyed): language-neutral data at root (`company_id`, `name`, `website`, `status`, `address`, per-axis `score`/`evidence`); a per-locale `en`/`nl` tree holding only translatable text (`tagline`, per-axis `reason`).
- **Stable schema, block-level nulls**: top-level keys always present; a whole block is `null` when its source stage produced nothing (e.g. `scores: null` = not scored), distinct from a null *value* inside a present block (e.g. `scores.power.score: null` with `evidence: "no_signal"` = scored, no signal).
- **Excludes** everything non-frontend-facing: page HTML/markdown, the content-summarization dossier, `footer_text`, `urls_attempted`, sitemap internals, per-stage `model` and intermediate statuses.
- **BREAKING** `pipeline-architecture`: relax the terminal-stage dependency so `dataset-output` requires only `fact-extraction` (the spine) and joins analytic + translation opportunistically, rather than requiring every upstream output to exist first.

## Capabilities

### New Capabilities
- `dataset-output`: the terminal projection stage that joins per-stage outputs into one frontend-facing record per company, in the published output schema.

### Modified Capabilities
- `pipeline-architecture`: the terminal stage's dependency relaxes from "all upstream outputs must exist" to "fact-extraction required; analytic and translation joined when present," enabling partial records.

## Impact

- New code: `pipeline/dataset_output/` (self-contained: `core.py`, `__main__.py`; no `llm.py` — no model calls).
- New output dir `data/dataset-output/`. No new dependencies, no new env vars.
- Output schema is a cross-repo contract consumed by the frontend (Astro) and a future Supabase migration; the frontend enumerates companies by globbing the directory (no manifest file).
