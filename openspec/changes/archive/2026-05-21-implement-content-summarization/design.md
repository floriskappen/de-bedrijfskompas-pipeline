## Context

Stage 4 of the pipeline. Reads one company's precision page markdown from `data/content-collection/<id>/` and writes a single English company dossier to `data/content-summarization/<id>.md`. The dossier is the fan-out point: every stage-5 theme-analytic stage (bullshit-scoring, bcorp-scoring, future tagging / ikigai-matching) consumes it instead of re-deriving "what does this company do" from raw scrape.

A corpus survey of the test set reframed the stage. The scraped text is small — median ~775 words, max ~3K tokens with all pages concatenated — so **token reduction is not the point**; even feeding raw text to every downstream stage would be cheap. What the corpus *is* full of is heterogeneity: founder bios, testimonials, mission manifestos, bulk listings, leftover template/placeholder junk, mixed Dutch/English, and cross-page duplication. The value of this stage is **normalization and grounding into one stable, faithful, de-marketed artifact** that downstream prompts can rely on having a consistent shape.

## Goals / Non-Goals

**Goals:**
- One faithful, de-marketed, English dossier per company, written by an LLM for downstream LLMs.
- Variable length driven by available substance, not a fixed target.
- Two-directional faithfulness: add no external facts; transcribe no non-company noise.
- The execution modes required by `pipeline-architecture` (CLI, orchestrator-callable, dry-run, plus an offline short-circuit for tests).

**Non-Goals:**
- Compression for cost. The corpus is too small for that to matter.
- Any scoring, ranking, tagging, philosophical mapping, or the concise front-end blurb — all downstream stage-5 concerns.
- Structured fact extraction (HQ address etc.) — that is `fact-extraction`.
- World-knowledge enrichment. The dossier stays strictly source-faithful so one bad source can't poison every downstream stage; enrichment happens downstream where it's appropriate.

## Decisions

### Single LLM call, no deterministic pre-pass

Unlike `fact-extraction` (regex-first, LLM-fallback), summarization is LLM-only: there is no deterministic signal to anchor on, and the whole job — de-marketing, dedup, noise rejection, translation — is exactly what an LLM is good at and a heuristic is not. One call per company keeps the stage simple and the cost trivial at this corpus size. Alternative considered: a cleanup/dedup pre-pass before the LLM — rejected as premature; the model handles it and a pre-pass would risk dropping signal.

### DeepSeek default, configurable

Default model `deepseek/deepseek-v4-flash` via OpenRouter, reusing fact-extraction's `httpx` client shape (no SDK). DeepSeek is chosen for strong world knowledge and language handling at low cost — and because the *downstream* philosophical-mapping stages will likely use the same family, keeping the dossier well-matched to its consumers. Overridable via `CONTENT_SUMMARIZATION_MODEL` so the default can be raised for spot evaluation without code changes. The exact id is a default, not a contract — the spec only requires "a DeepSeek model."

### Markdown output with YAML frontmatter, not JSON carry-through

`fact-extraction` emits JSON and carries every input key through verbatim. This stage's output is prose, so it writes markdown (allowed by `pipeline-architecture` for content stages) with a small fixed YAML frontmatter block (`name`, `website`, `status`, `source_language`, `model`). Downstream joins by `<company-id>` (the filename), so arbitrary carry-through isn't needed; a fixed frontmatter set keeps the file clean and predictable. Alternative considered: JSON `{summary: "..."}` — rejected as a worse fit for variable-length prose and for human spot-checking.

### Prompts live in `prompts/`, not inline

The constitution requires versioned prompt files loaded by name, no inline prompts. `fact-extraction` violated this (prompts in `prompt.py`); this stage establishes the `prompts/` directory convention properly, loading the dossier prompt from a named file. The prompt carries the load-bearing behavior — variable length, faithfulness, noise rejection, English normalization, claim-vs-fact attribution — so prompt iteration is a content change, not a code change.

### Module layout

`pipeline/content_summarization/` mirroring existing stages: `__main__.py` (CLI), `core.py` (`process` single-company + `run` orchestrator/dry-run/offline), `llm.py` (thin OpenRouter wrapper, retries, wrapper-stripping), and prompt loading from `prompts/`. I/O-free input assembly (page selection, ordering, truncation) kept as pure functions so it's testable offline without the LLM.

### Status field

A small `status` enum in frontmatter (`ok`, `upstream_failed`, `empty`, `llm_error`) mirrors fact-extraction's pattern so batch outcomes are auditable after a run without re-reading every dossier. No per-path nuance is needed here since there's a single resolution path.

## Risks / Trade-offs

- **Prose output isn't deterministically verifiable.** → Offline tests assert structure/plumbing (correct input selection, recall-exclusion, status routing, write layout, wrapper stripping) with the LLM mocked; quality is judged end-to-end against the test-set `notes`, which encode ground-truth expectations (e.g. Land Life reads mission-driven, Gravity reads money-first).
- **The model may still hallucinate or transcribe junk** despite the prompt. → Low temperature, an explicit faithfulness/noise-rejection prompt, and the `notes`-based eval to catch regressions. This is inherent to an LLM stage; the spec's scenarios are the regression target.
- **Single artifact feeds all of stage 5.** A weak dossier degrades every downstream stage. → Accepted by design; it's the reason the faithfulness bar is high and the eval is end-to-end rather than per-stage.
- **English normalization may flatten nuance** in source-language phrasing. → Acceptable; downstream stages reason in one language, and `source_language` is retained for traceability.
- **Discrepancy/exclusion flagging is uneven across companies.** Because structure is dynamic (length follows substance, no fixed template), a dossier only grows a dedicated "Discrepancies" or "Key Exclusions" section when the source warrants one — a large, claim-dense site like Land Life surfaces conflicting figures and gets such sections, while a smaller, consistent site like Gravity gets the same catch folded inline (e.g. "15 years" vs "Sinds 2017") or omitted. This is the no-forced-structure principle working as intended, not the model being selectively critical. → Accepted: not uniform or guaranteed. If a stage-5 consumer (e.g. bullshit-scoring) ever needs a consistent "what's missing / what conflicts" signal for every company, add an explicit exclusions/discrepancies pass to the prompt then — deferred now because forcing it risks manufacturing nitpicks on clean sources.

## Open Questions

- **24k-char input cap** chosen as generous headroom over the observed ~3K-token max. Revisit only if a future corpus routinely exceeds it.
- **Do downstream stages need a length/quality signal** in frontmatter (e.g. word count, a "thin source" flag)? Deferred until a consumer actually needs it.
- **Temperature value** left to implementation; start low (~0.2) and revisit if dossiers come out either too templated or too loose.
