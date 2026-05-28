## Context

The pipeline already has two dossier-derived analytic stages (`tagline-extraction`, `global-scoring`) that share a consistent shape: read the content-summarization dossier, build a versioned prompt, call OpenRouter/deepseek, write one JSON file per company. `tagging` slots into the same wave (4) with the same shape. The work in this change is mostly: pick the right tag vocabulary and pick the right output schema for downstream extension.

## Goals / Non-Goals

**Goals:**
- A per-company JSON file listing the capability families the company runs on, with a prominence qualifier.
- Tier-1 vocabulary fixed and exhaustive enough to cover the Dutch economy so the UI can rely on it for faceted filtering.
- Schema designed so tier-2 (specific) tags can be added later without breaking consumers.
- Follow the established analytic-stage code shape — no shared cross-stage helpers per `[[project_per_stage_self_contained]]`.

**Non-Goals:**
- Sector tagging (postponed; messier vocab, no chosen UI use).
- Tier-2 tag vocabulary or generation.
- Vocab-state/feedback-loop file or normalization pass.
- A confidence score (we use a 3-bucket prominence enum instead).
- Translation of tags (slugs are language-neutral).

## Decisions

**Tag record shape: flat list of `{family, prominence}`.** Easier to query and filter than a nested-by-family object. Each entry corresponds to one tier-1 family; the schema permits adding an optional `tags: [<tier-2-slug>]` field per entry in a future change, which keeps tier-1-only consumers working.

**Prominence as a 3-value enum, not a numeric score.** Values: `core`, `supporting`, `incidental`. A core capability is what the company is fundamentally built on; supporting is real but not central; incidental is mentioned-in-passing. Three buckets are easier for the LLM to produce consistently than a 0–1 score and easier for the UI to display ("core capabilities" vs "also touches").

**At most one entry per family.** The prominence qualifier already absorbs intensity; allowing duplicates invites the LLM to emit overlapping entries. Enforced by the prompt and validated when parsing the LLM response.

**Tier-1 vocabulary fixed in the prompt, not loaded from a file.** Nineteen slugs, hand-curated to cover the Dutch economy (CBS/SBI cross-check done during exploration). The prompt enumerates them with short descriptions and explicit examples of edge cases (e.g. "production-line workers → `field-trades-operators`", "management consulting → `commercial`"). No vocab-state file because tier-1 doesn't grow; if a hole is later discovered, that's a spec change, not runtime data.

**Stage is not a translation input.** Capability families are slugs, not user-facing text; the UI maps slugs to localized labels client-side. Keeps `translation`'s fan-in small.

**Stage is left-joined by `dataset-output`, not required.** Same treatment as `tagline-extraction` and `global-scoring`. Lets the pipeline ship records even when tagging hasn't run for a company.

**Model: deepseek/deepseek-v4-flash via OpenRouter.** Matches the other analytic stages; cheap and consistent with the codebase's existing LLM client pattern. Override via `TAGGING_MODEL` env var.

## Risks / Trade-offs

- **[19 families don't cover an edge case]** → The vocabulary was stress-tested against the Dutch economy during exploration; if a real company surfaces a hole, the fix is a spec change to add or rename a family. Not silent-fallible at runtime.
- **[LLM emits invalid family slug]** → `llm.py` validates each emitted `family` against the fixed set; an unknown slug raises `LLMError` and the company gets `status: llm_error`, same as other analytic stages on bad output.
- **[Prominence drift between runs]** → Inherent to LLM output; mitigated by the prompt's explicit definitions and examples, and by keeping prominence to three buckets rather than a fine-grained score. Re-running on the same dossier may produce slightly different tags; this is acceptable for the discovery UI's purposes.
- **[Tier-2 added later breaks downstream]** → Adding `tags: [...]` inside each capability entry is purely additive; existing consumers ignore the field. The schema-evolution path is the main reason to commit to the flat list shape now.
