## Why

The six LLM-using stages (`fact-extraction`, `content-summarization`, `tagline-extraction`, `global-scoring`, `tagging`, `translation`) each process companies strictly sequentially in a `for record in records: yield process(...)` loop. At ~60s per LLM call and ~100 companies per batch, a single stage takes ~100 minutes wall-clock, and the ten-stage pipeline multiplies that. LLM latency is the dominant cost. The calls are independent per company (each reads its own input, writes its own output file, no cross-company state), so they parallelize cleanly — but `pipeline-architecture` currently mandates sequential intra-stage processing (`End-to-End Orchestrator`: "Within a stage, companies SHALL be processed in input order").

## What Changes

- **Amend the intra-stage ordering contract**: companies are still *yielded* in input order (external contract unchanged), but processing within a stage MAY happen concurrently in a bounded per-stage pool.
- **Add 429-aware backoff** to each LLM stage's retry loop. Today retries are immediate with no sleep (`for attempt in range(retries + 1)`); under concurrency this thundering-herds the shared `OPENROUTER_API_KEY` into repeated 429s and burns all retries in under a second.
- **Per-stage bounded concurrency** via a `*_CONCURRENCY` env var per stage (e.g. `TAGLINE_EXTRACTION_CONCURRENCY`). Per-stage, not global, per the self-contained-stage principle (`pipeline-architecture/spec.md:114`; reaffirmed `2026-05-22-add-tagline-extraction-stage/design.md:17`).
- **fact-extraction two-phase split**: run the sync candidate-extraction + decision logic for all companies first, then parallelize only the LLM-bound companies (disambiguation / prose-fallback). Most companies resolve to `regex_single`/`empty` with zero LLM calls; pooling them naively wastes LLM concurrency slots on instant regex work.

Stages stay self-contained: no shared client, no shared runner, no shared concurrency primitive. The retry/backoff and the pool logic are duplicated per stage — same genre as the existing six duplicated `llm.py` files, and the same explicitly-accepted cost of isolation (`2026-05-22-add-tagline-extraction-stage/design.md:29`, `2026-05-23-add-global-scoring-stage/design.md:34`).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `pipeline-architecture`: the End-to-End Orchestrator requirement's "Within a stage, companies SHALL be processed in input order" clause is amended to permit bounded concurrent intra-stage processing while requiring results to be yielded in input order; failure-as-record isolation is unchanged.

## Impact

- `pipeline/run.py`: unchanged — it already does `list(run(...))` per stage, materializing each batch, so a parallel `run()` that yields in input order is externally indistinguishable.
- `pipeline/{fact_extraction,content_summarization,tagline_extraction,global_scoring,tagging,translation}/core.py`: each `run()` replaces its sequential loop with a bounded `ThreadPoolExecutor` map that preserves input order and isolates per-company failures (the existing `try/except` → failure-record contract carries over unchanged).
- `pipeline/{...six stages...}/llm.py`: each retry loop gains exponential backoff with jitter on 429/5xx, honouring `Retry-After` when present.
- `pipeline/fact_extraction/core.py`: `process()` split into a sync decision phase and an LLM-call phase; `run()` parallelizes only the LLM-bound companies.
- `tests/`: the six `test_one_llm_failure_does_not_abort_batch` tests key failure off a call-order counter (`if len(call_log) == 2: raise`); under concurrency "second call" is non-deterministic, so they are rewritten to key off the company identity carried in the messages (translation's `tests/test_translation.py:232` already uses this pattern).
