## Why

`content-collection` produces wildly heterogeneous per-page markdown — founder bios, testimonials, mission manifestos, seminar-calendar dumps, even leftover lorem-ipsum and demo data — in mixed Dutch/English. Every downstream stage (the front-end no-bullshit blurb, philosophical-framework mapping, ikigai-matching, future analytics) would otherwise re-derive "what does this company actually do" from that mess on every prompt. This change builds the stage-4 firewall: one faithful, normalized company dossier per company that downstream LLM stages can depend on.

## What Changes

- Add pipeline stage 4 (`content-summarization`): reads each company's precision `data/content-collection/<id>/*.md` pages, writes a single `data/content-summarization/<id>.md` dossier via one LLM call (DeepSeek, OpenRouter).
- **The dossier is not a summary in the compression sense.** The corpus is small (median ~775 words, max ~3K tokens concatenated), so token reduction is not the goal. The dossier is a *normalized, de-marketed, deduplicated, English company description* containing all relevant substance, written by an LLM for downstream LLMs (not for humans).
- **Variable length, driven by signal not word count.** A terse factual site (appic, 89w) yields a short dossier; a marketing-saturated site (co-health) collapses to the few sentences of real substance. No fixed target — forcing length causes hallucination and padding.
- **Two-directional faithfulness:** (1) add no external facts not present in the source; (2) transcribe no source *junk* — lorem-ipsum, leftover template content from another industry, demo/mockup data, calendar/listing dumps. World-knowledge enrichment is explicitly deferred to downstream stages so one bad source can't poison every stage.
- Input is precision `.md` only (not `.recall.md`). Output normalized to English regardless of source language.
- CLI, orchestrator-callable, and dry-run modes per `pipeline-architecture`. Prompt lives as a versioned file under `prompts/`, loaded by name (no inline prompts).

## Capabilities

### New Capabilities

- `content-summarization`: generates one faithful, de-marketed, de-noised, English markdown dossier per company from precision content-collection pages, for consumption by downstream LLM stages.

### Modified Capabilities

- `pipeline-architecture`: corrects the stage-4 description — it is a variable-length faithful dossier, not a "compact prose summary" — and clarifies what it means for stage-5 theme-analytic stages (including `bullshit-scoring`) to depend on it.

## Impact

- New module `pipeline/content_summarization/` (core + `__main__`), mirroring existing stage structure.
- New prompt file under `prompts/`.
- New output tree `data/content-summarization/<id>.md`.
- New tests in `tests/test_content_summarization.py`.
- OpenRouter/DeepSeek dependency (already used by `fact-extraction`'s LLM path).
