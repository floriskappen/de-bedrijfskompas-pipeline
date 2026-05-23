## Context

Both analytic stages (`tagline-extraction`, `global-scoring`) generate Dutch inline on the same reasoning call. Translation rides for free but couples reasoning quality to bilingual output, and the Dutch instruction adds output-token cost to the expensive call. The fix is a dedicated `translation` stage that fans in from both analytic outputs and handles all Dutch in one batched call per company.

## Goals / Non-Goals

**Goals:**
- New `translation` stage (stage 6): reads `data/tagline-extraction/` and `data/global-scoring/`, extracts targeted English fields, translates in one batched call, writes `nl` to `data/translation/<company>.json`
- Remove Dutch from both upstream prompts and schema; make analytic stages English-only
- Explicit target registry inside the translation stage — hand-maintained, zero auto-discovery magic

**Non-Goals:**
- en+nl join into a combined record — that belongs to the not-yet-built `dataset-output`
- Switching to a cheaper or dedicated translation model (default stays DeepSeek V4 Flash for pipeline consistency, overridable)

## Decisions

**Fan-in architecture.** Translation reads multiple upstream dirs rather than being called by each stage. Alternative: each analytic stage makes a second translation call itself. Rejected: that duplicates the translation logic across stages, which the self-contained constraint already permits but does not require — and it forfeits the batching benefit (multiple calls vs one). A proper stage is the right shape.

**Explicit target registry, not schema-generic walk.** The stage declares exactly which fields to translate (`tagline-extraction → tagline`, `global-scoring → scores.*.reason`). Alternative: walk any `{en, nl}` pair in the JSON tree automatically. Rejected: auto-discovery is invisible — a future contributor doesn't know which fields are bilingual without reading both stages. Explicit is readable and safe; manual extension cost is one line.

**`nl`-only output (`data/translation/`)**.  The translation file holds only `nl` values keyed by flat target paths (e.g. `"scores.substance.reason": {"nl": "..."}`). `en` stays in the source stage file. Alternative: emit a full bilingual copy (`en` + `nl` together). Rejected: duplicates `en`, splits ownership — translation would be co-authoring a field it doesn't own.

**Status semantics for a fan-in stage.** `ok` if at least one target was translated; `upstream_failed` only if every source for that company is missing/non-ok; `empty` if sources are ok but all targeted fields are absent; `llm_error` on call failure. Per-company, always emit a record.

**Path resolver with wildcard.** `scores.*.reason` is expanded inside the translation stage using a tiny internal helper (not shared). The `*` matches all dict keys at that level. Self-contained, consistent with the per-stage rule.

## Risks / Trade-offs

After this change `en` and `nl` for the same field live in different dirs. → `dataset-output` (future) bears the join cost; this is documented in the pipeline-architecture spec.

Analytic stage outputs become English-only — a breaking change for anything reading those files directly today (e.g. manual inspection). → Acceptable; documented in the proposal as BREAKING.

A source stage returning `llm_error` silently contributes zero targets to translation for that company. → Translation records `ok` if it translated *something*, which surfaces partial states; nothing is silently dropped.
