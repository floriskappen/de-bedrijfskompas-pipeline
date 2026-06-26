## Context

The pipeline runs ten stages sequentially; six of them call an LLM once (or occasionally) per company. Each LLM stage's `run()` is a sync generator doing `for record in records: yield process(...)`, and each `llm.py` retries transport failures with `for attempt in range(retries + 1)` and no backoff sleep. At ~100 companies and ~60s/call this is the dominant wall-clock cost. The calls are independent per company — distinct input, distinct output file, no cross-company state — so they parallelize cleanly. The architecture spec's `End-to-End Orchestrator` requirement currently forbids that ("Within a stage, companies SHALL be processed in input order"). Per-company failure isolation is already the contract, and per-company writes are already independent, so the batch is structurally safe to parallelize; the work is picking the concurrency model, the cap shape, and the retry policy, all while honouring the self-contained-stage principle (`pipeline-architecture/spec.md:114`, reaffirmed in `2026-05-22-add-tagline-extraction-stage/design.md:17` and `2026-05-23-add-global-scoring-stage/design.md:34`).

## Goals / Non-Goals

**Goals:**
- Within each LLM stage, process companies concurrently so a 100-company batch finishes in minutes, not hours.
- Keep the external contract identical: `run()` still yields one record per company in input order, still isolates per-company failures as records, still raises only on company-id collision.
- Survive OpenRouter rate-limiting under load: retry with backoff on 429/5xx instead of burning all retries instantly.
- In fact-extraction, don't spend LLM concurrency slots on companies that resolve via regex with zero LLM calls.

**Non-Goals:**
- Intra-wave concurrency (running `tagline-extraction` and `global-scoring` at the same time). The architecture spec already permits it; the orchestrator still runs stages one at a time. This change is strictly intra-stage.
- A shared LLM client or shared runner across stages. Explicitly rejected per the self-contained-stage principle; the retry/backoff and pool logic are duplicated per stage, same as the six existing `llm.py` files.
- Parallelizing the non-LLM stages (`website-resolution`, `content-collection`, `geocoding`, `dataset-output`, `publish`).
- Connection pooling / a shared `httpx.Client`. Each call keeps using `httpx.post`; pooling is a separate optimisation.

## Decisions

### Decision 1: Threads (`ThreadPoolExecutor`), not asyncio
- **Choice**: `concurrent.futures.ThreadPoolExecutor` inside each stage's `run()`.
- **Alternatives**: `asyncio` with `httpx.AsyncClient` + `Semaphore`.
- **Rationale**: The codebase is fully sync — zero `async`/`await` anywhere, sync `httpx.post`, sync `run()` generators consumed by `list(run(...))`. asyncio would force `async def call()` and `async def run()` across six stages, `asyncio.run` in the orchestrator and CLIs, and `AsyncMock` in tests — a paradigm shift for a personal project, for no gain at ~100 I/O-bound calls (the GIL is released during `httpx` recv, so threads genuinely parallelize the wait). Threads leave sync code sync.

### Decision 2: Parallelism lives inside each stage's `run()`, not in the orchestrator
- **Choice**: Each stage's `run()` replaces its `for record in records: yield process(...)` with a bounded pool over `process()`, reassembling results in input order before yielding.
- **Alternatives**: Drive concurrency from `pipeline/run.py` above the stages; or extract a shared `pipeline/_llm/runner.py`.
- **Rationale**: The orchestrator is already generic over the `run()` signature and stays byte-for-byte unchanged. A shared runner module would violate the self-contained-stage principle (the sole sanctioned cross-stage import is `company_id`). Putting the pool inside `run()` means both the orchestrator and each stage's standalone `__main__.py` CLI pick up concurrency for free.

### Decision 3: Yield in input order; parallelise internally
- **Choice**: Submit all companies to the pool, then yield completed results reindexed by input position — externally indistinguishable from sequential.
- **Alternatives**: Yield in completion order.
- **Rationale**: The orchestrator materialises each batch with `list(run(...))`, so there is no streaming benefit to completion order. Preserving input order means the spec amendment is minimal ("companies are *yielded* in input order; processing MAY happen concurrently"), every existing test asserting ordered `statuses` lists still passes, and the on-disk seam is unchanged.

### Decision 4: Per-stage concurrency cap, not a global semaphore
- **Choice**: Each stage reads its own `*_CONCURRENCY` env var (e.g. `TAGLINE_EXTRACTION_CONCURRENCY`) with a conservative default.
- **Alternatives**: One module-level shared `Semaphore` across all LLM calls.
- **Rationale**: Self-containment — a cross-stage shared cap is shared mutable state that couples stages. Today the orchestrator runs stages sequentially, so per-stage is equivalent to global at runtime; the only loss is forward-compatibility with intra-wave concurrency, which is a separate future change. If that future arrives, each stage can opt into a shared cap then.

### Decision 5: 429-aware exponential backoff with jitter on the existing retry loop
- **Choice**: Each `llm.py`'s `for attempt in range(retries + 1)` loop sleeps before retrying on 429/5xx — exponential base with jitter, honouring `Retry-After` when OpenRouter sends it.
- **Alternatives**: `tenacity`/`backoff` library; or no backoff (status quo).
- **Rationale**: Under concurrency, N threads hitting the shared API key get 429'd together; immediate retries (today's behaviour) re-429 in lockstep and exhaust `retries=2` in under a second. Backoff is what makes a concurrent batch survive a rate-limit storm. A library would add a dependency the project deliberately avoids (hand-rolled retry today); the ~8-line backoff helper is duplicated per stage, same genre as the existing duplicated retry loop. The backoff base and cap are module-level constants in each `llm.py`, same genre as the existing `timeout` and `retries` constants (which are also implementation, not spec'd) — output is invariant to their exact values; they are tuned in one place per stage.

### Decision 6: fact-extraction two-phase split (decision phase, then LLM-call phase)
- **Choice**: In `fact_extraction/core.py`, run candidate extraction + branch decision for all companies first (sync, cheap), then submit only the LLM-bound companies (disambiguation / prose-fallback) to the pool.
- **Alternatives**: Pool `process()` uniformly like the other five stages.
- **Rationale**: Most fact-extraction companies resolve via `regex_single` or `empty` with zero LLM calls; pooling `process()` naively would allocate an LLM concurrency slot to threads that finish in milliseconds doing regex, starving the minority that actually block on the LLM. The two-phase split reserves the cap for real LLM work. This is stage-local implementation; the per-company output and statuses are unchanged.

## Risks / Trade-offs

- **[Risk] Backoff policy drift across the six stages** → Each `llm.py` owns its own backoff helper; tuning one without the others yields inconsistent behaviour against the shared API key. **Mitigation**: the cap default and backoff constants are named load-bearing values in `pipeline-architecture`; an Operational Pitfall notes the hand-sync obligation (same genre as the duplicated `_ADDRESS_INTENT_STEMS` across `fact-extraction` and `content-collection`).
- **[Risk] Order-keyed failure tests become non-deterministic** → The six `test_one_llm_failure_does_not_abort_batch` tests fail "the second call" via a counter; under concurrency "second" is undefined. **Mitigation**: rewrite them to key the failure off the company identity carried in the messages (translation's `tests/test_translation.py:232` already does this). Counting assertions (call counts) stay valid; ordering assertions do not.
- **[Risk] Cap too high still 429s the shared key; too low negates the speedup** → **Mitigation**: conservative default, tunable per stage via env; the backoff absorbs transient spikes.
- **[Risk] Duplicate `ThreadPoolExecutor` + backoff code across six stages is the most-duplicated code in the repo** → **Mitigation**: accepted per the self-contained-stage principle and the precedent of the six duplicated `llm.py` files; documented as deliberate so a future reader doesn't "fix" it by re-extracting a shared helper.

## Migration Plan

Pure code change, no data migration. Per-stage rollout: add backoff to each `llm.py` first (a no-op for sequential runs — just slower retries), then convert each `run()` to the pool, then do the fact-extraction two-phase split. Run each stage against `test-set/companies.json` to confirm wall-clock improvement and that output records are byte-identical to a sequential run (modulo `model`/timestamps). Rollback is a straight revert; on-disk data is regenerated each run.
