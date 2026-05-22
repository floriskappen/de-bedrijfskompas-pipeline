## Context

`tagline-extraction` is a stage-5 analytic stage that turns the `content-summarization` dossier into a short, plain-language, bilingual one-liner for the frontend. It mirrors the shape of `content-summarization` and `fact-extraction`: a `process()` per company, a `run()` batch generator, three execution modes, and the shared failure-status vocabulary. The novel parts are the bilingual JSON output and reading markdown frontmatter as the upstream gate.

## Goals / Non-Goals

**Goals:**
- A self-contained module that distils the dossier into `{en, nl}` taglines whose spine is "who pays them and for what".
- Conform to the architecture's execution-mode and Failure-Propagation contracts with no shared cross-stage code.

**Non-Goals:**
- A shared OpenRouter client or shared frontmatter utility across stages — deliberately avoided (see Decisions).
- Any scoring, tagging, or matching; any re-reading of `content-collection`.

## Decisions

**Self-contained module, no shared code.** The stage gets its own `pipeline/tagline_extraction/` with a local `llm.py` and a local frontmatter reader, copying the established pattern rather than importing from sibling stages. Each stage stays independently runnable and modifiable; a premature shared `llm` helper would couple stages whose prompt/parse needs already diverge (raw text vs. JSON). The only cross-stage import remains `company_id` from `website-resolution`, as the other stages already do.

**JSON-returning LLM call.** The local `llm.py` parses the completion into an object and returns `{en, nl}` (like `fact-extraction`'s client), not raw text (like `content-summarization`'s). A response that won't parse into non-empty `en` and `nl` strings is an `LLMError` → `status: llm_error`. This keeps malformed/partial output from leaking into the dossier-facing record.

**One call for both languages.** A single prompt asks for both `en` and `nl` in one JSON object, rather than generating English then translating in a second call. Cheaper, lower latency, and the model keeps the two phrasings semantically aligned because it writes them together.

**Frontmatter as the gate.** The dossier is markdown; the stage reads its YAML frontmatter `status` and proceeds only on `ok`, feeding only the body to the LLM. A tiny local parser extracts `status`/`name`/`website` — no YAML dependency, matching how `content-summarization` already hand-parses its own frontmatter.

**Default model + override.** Default to the same DeepSeek model as the other stages, overridable via `TAGLINE_EXTRACTION_MODEL`, so the per-stage env-var convention holds.

## Risks / Trade-offs

- **Pattern duplication.** Three near-identical `llm.py` files now exist. Accepted: per-stage isolation is the explicit design value, and the files differ in parse logic. A shared client can be its own refactor change later if the duplication bites.
- **Bilingual quality from one call.** A single call could yield a weaker Dutch rendering than a dedicated translation pass. Accepted for cost/consistency; the prompt instructs faithful equivalence and the test-set lets us eyeball `nl` quality before scaling.
- **Frontmatter parsing fragility.** A hand-rolled parser is fine for the fixed, stage-controlled frontmatter keys but would break on arbitrary YAML; that is acceptable because this stage only ever reads dossiers written by `content-summarization`.
