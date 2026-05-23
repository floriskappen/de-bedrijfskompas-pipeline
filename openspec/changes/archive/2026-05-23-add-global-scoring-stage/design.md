## Context

`global-scoring` is a stage-5 analytic stage that turns the `content-summarization` dossier into the five-axis profile from `docs/GLOBAL_SCORING_FRAMEWORK.md`. It mirrors `tagline-extraction` exactly in shape: a `process()` per company, a `run()` batch generator, three execution modes, frontmatter-gated upstream, and the shared failure-status vocabulary. The novel parts are the richer per-axis output (score + evidence + bilingual reason), the asymmetric-silence rules, and the deliberate absence of any composite score.

## Goals / Non-Goals

**Goals:**
- A self-contained module that scores the dossier on the five axes, each as `{score, evidence, reason:{en,nl}}`, faithful to the framework's silence asymmetry.
- Conform to the architecture's execution-mode and Failure-Propagation contracts with no shared cross-stage code.

**Non-Goals:**
- Any composite/global number, ranking, or weighting — explicitly forbidden by the framework; weighting is the frontend's personal layer.
- Topic tagging or ikigai/local matching (separate future stages); re-reading `content-collection`; quoting source text (the dossier is internal and not user-visible).

## Decisions

**Self-contained module, no shared code.** The stage gets its own `pipeline/global_scoring/` with a local `llm.py` and a local frontmatter reader, copying the `tagline-extraction` pattern rather than importing from siblings. The only cross-stage import remains `company_id` from `website-resolution`. A premature shared `llm` helper would couple stages whose parse needs already diverge.

**JSON-returning LLM call, strictly validated.** The local `llm.py` requests a JSON object and validates it into the five-axis schema before returning: all five axis keys present; each `score` an int 0–100 or `null`; each `evidence` in the fixed vocabulary; each `reason.en`/`reason.nl` a non-empty string. A response that won't validate is an `LLMError` → `status: llm_error`, so malformed/partial output never reaches the record.

**English-first, then Dutch — in one call.** The prompt instructs the model to reason and write each axis `reason.en` first, then translate it to `reason.nl`, all within a single response. This honours the "think in English, the model's strongest language, then translate" intent without paying for two round-trips, and keeps the two phrasings aligned. Alternative (two calls: score in English, then a translation pass) was rejected for cost/latency; a single low-temperature call is enough and the test set lets us eyeball `nl` quality.

**Nullable score + evidence level; silence is asymmetric.** A flat 0–100 cannot distinguish "genuinely low" from "unknown", which the framework treats as fundamentally different. So each axis carries an `evidence` level and a `score` that is `null` when `evidence` is `no_signal`. The per-axis silence rules (vagueness counts against Substance/Ecology; neutral for Embeddedness; never penalise Power → default `no_signal`/`null`) live in the versioned prompt, not in code.

**Prompt is the single behavioural surface; framework doc is its source.** The five-axis definitions, readability ordering, and silence rules are transcribed from `docs/GLOBAL_SCORING_FRAMEWORK.md` into `prompts/global-scoring.md`. Scoring quality is a prompt-tuning problem, iterated against `test-set/companies.json` during implementation, not a code problem.

**Default model + override.** Default to DeepSeek v4 Flash on OpenRouter, overridable via `GLOBAL_SCORING_MODEL`, holding the per-stage env-var convention. Low temperature for score stability.

## Risks / Trade-offs

- **Score calibration & non-determinism.** An LLM assigning 0–100 is noisy and may not honour the null/`no_signal` asymmetry, especially for Power. → Low temperature, explicit per-axis silence rules in the prompt, and test-set eyeballing before trusting output; prompt iteration is expected.
- **Two sources of truth.** The framework doc and the prompt can drift. → The prompt is derived from the doc and the doc is named in the spec as the source; reconcile on any framework revision.
- **Bilingual quality from one call.** A combined call may yield weaker Dutch than a dedicated pass. → Accepted for cost; the prompt mandates faithful equivalence and `nl` is eyeballed on the test set.
- **Pattern duplication.** A fourth near-identical `llm.py`. → Accepted; per-stage isolation is the explicit design value, and parse/validation logic differs per stage.
