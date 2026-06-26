## 1. Rate-Limit-Aware Retry Backoff

- [x] 1.1 Add 429/5xx exponential backoff with jitter, honouring `Retry-After`, to the retry loop in `pipeline/fact_extraction/llm.py`
- [x] 1.2 Add the same backoff to `pipeline/content_summarization/llm.py`
- [x] 1.3 Add the same backoff to `pipeline/tagline_extraction/llm.py`
- [x] 1.4 Add the same backoff to `pipeline/global_scoring/llm.py`
- [x] 1.5 Add the same backoff to `pipeline/tagging/llm.py`
- [x] 1.6 Add the same backoff to `pipeline/translation/llm.py`

## 2. Concurrent `run()` — Five Uniform LLM Stages

Each stage replaces its `for record in records: yield process(...)` loop with a bounded `ThreadPoolExecutor` map that reindexes completed results by input position before yielding, preserves per-company failure isolation, and reads a `<STAGE>_CONCURRENCY` env var with a conservative default.

- [x] 2.1 `pipeline/content_summarization/core.py` — concurrent `run()` + `CONTENT_SUMMARIZATION_CONCURRENCY`
- [x] 2.2 `pipeline/tagline_extraction/core.py` — concurrent `run()` + `TAGLINE_EXTRACTION_CONCURRENCY`
- [x] 2.3 `pipeline/global_scoring/core.py` — concurrent `run()` + `GLOBAL_SCORING_CONCURRENCY`
- [x] 2.4 `pipeline/tagging/core.py` — concurrent `run()` + `TAGGING_CONCURRENCY`
- [x] 2.5 `pipeline/translation/core.py` — concurrent `run()` + `TRANSLATION_CONCURRENCY`

## 3. fact-extraction Two-Phase Split

- [x] 3.1 Split `pipeline/fact_extraction/core.py::process()` into a sync decision phase (load + candidate extraction + branch) that returns either a completed record (`regex_single`/`empty`/`upstream_failed`) or a pending LLM work item (`disambiguate`/`llm_fallback`)
- [x] 3.2 Rewrite `pipeline/fact_extraction/core.py::run()` to run the decision phase over all records, write the completed records, then pool only the LLM-bound work items; add `FACT_EXTRACTION_CONCURRENCY`

## 4. Tests — Scenario Coverage

- [x] 4.1 `test_llm_backs_off_on_429` (parametrized across the six LLM stages) — assert the client sleeps with exponential backoff + jitter before retrying on 429 and honours `Retry-After`. Covers **"Rate-limit retry backs off"**.
- [x] 4.2 `test_concurrent_retries_jittered_not_in_lockstep` — assert that several concurrent requests receiving 429 in the same window space their retries via jitter rather than retrying simultaneously. Covers **"Concurrent retries do not fire in lockstep"**.
- [x] 4.3 `test_concurrent_yields_input_order` (parametrized across the six LLM stages) — assert that when a later company completes before an earlier one, `run()` still yields the earlier company's record first. Covers **"Concurrent processing yields in input order"**.
- [x] 4.4 Rewrite the six `test_one_llm_failure_does_not_abort_batch` tests (`tests/test_fact_extraction.py`, `tests/test_content_summarization.py`, `tests/test_tagline_extraction.py`, `tests/test_global_scoring.py`, `tests/test_tagging.py`, `tests/test_translation.py`) to key the forced failure off the company identity carried in the messages instead of a `len(call_log) == 2` counter. Covers **"Per-company failure does not abort a concurrent batch"**.
- [x] 4.5 Confirm the existing orchestrator tests (`test_run_completes_stage_before_next`, `test_run_calls_stages_in_process`) still pass against the MODIFIED **"End-to-End Orchestrator"** scenarios (stage ordering, programmatic-not-subprocess, end-to-end run).

## 5. Verification

- [x] 5.1 Full suite green: `pytest`
- [x] 5.2 Run one stage (e.g. `tagline-extraction`) against `test-set/companies.json` and confirm wall-clock is down materially versus sequential, with output records byte-identical to a sequential run (modulo `model`/ordering-independent fields)
