## Why

The analytic stages (`tagline-extraction`, `global-scoring`) currently generate Dutch inline, on the same expensive LLM call that does the reasoning. That couples translation quality to the reasoning model, splits its attention across two languages, and pays reasoning-model rates for what is a simpler task. Pulling translation into its own stage lets each analytic stage stay monolingual (English) and focused, and lets the Dutch be produced in one cheap, batched call per company.

## What Changes

- Add a new `translation` stage (stage 6) that fans in from the analytic stage outputs, produces the Dutch (`nl`) for an explicitly registered set of fields, and writes them to `data/translation/<company-id>.json`. The translation stage **owns** every `nl` value; nobody else writes one.
- Targets are an explicit, hand-maintained registry inside the stage (e.g. `tagline-extraction → tagline`, `global-scoring → scores.*.reason`). Adding a future translatable field is a one-line edit, not automatic discovery.
- One batched translation call per company. The default model stays DeepSeek V4 Flash (same as the analytic stages — one model across the pipeline), overridable via `TRANSLATION_MODEL`. The saving comes from batching all of a company's Dutch into one call and from keeping the reasoning calls monolingual, not from a cheaper model.
- **BREAKING** `tagline-extraction`: drops the Dutch instruction from its prompt and emits the tagline as English only (no `nl`).
- **BREAKING** `global-scoring`: drops the Dutch instruction from its prompt and emits each axis `reason` as English only (no `nl`).
- Insert `translation` into the pipeline stage sequence between the stage-5 analytic stages and the terminal `dataset-output`. The eventual en+nl join belongs to `dataset-output`, which does not exist yet, so that join is out of scope here.

## Capabilities

### New Capabilities
- `translation`: a fan-in stage that renders the Dutch for a registered set of English fields produced by upstream analytic stages, one batched LLM call per company, owning all `nl` values on disk.

### Modified Capabilities
- `tagline-extraction`: the tagline output becomes English-only; the stage no longer produces `nl`.
- `global-scoring`: each axis `reason` becomes English-only; the stage no longer produces `nl`.
- `pipeline-architecture`: the stage sequence gains `translation` as a fan-in stage after the parallel analytic stages and before `dataset-output`.

## Impact

- New code: `pipeline/translation/` (self-contained: own `llm.py`, `frontmatter.py`, `core.py`, `__main__.py`) and `prompts/translation.md`.
- Modified: `prompts/tagline-extraction.md`, `prompts/global-scoring.md` (remove Dutch), and the two stages' validators/record shapes (drop `nl`).
- New env var `TRANSLATION_MODEL`; new output dir `data/translation/`.
- Workflow note: after this change, Dutch for a company lives in `data/translation/`, not inline in the analytic stage outputs.
