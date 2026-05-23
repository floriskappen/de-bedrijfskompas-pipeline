## Context

`dataset-output` is the terminal stage (7) declared in `pipeline-architecture`. Every upstream stage already persists per-company files; what's missing is a single frontend-facing record per company. Unlike every prior seam, this one crosses a repo boundary: its consumer is the static Astro site (and, later, a Supabase schema), so the output shape is a published contract, not an internal handoff.

## Goals / Non-Goals

**Goals:**
- One clean, stable JSON record per company that the Astro build can render directly.
- A pure, idempotent projection: filter + join + rename, no new information, no model calls.
- A predictable schema (always-present keys) that survives a later Supabase migration.

**Non-Goals:**
- No manifest/index file, no aggregation across companies (forbidden by the architecture spec; the frontend globs the directory).
- No new extraction (e.g. KVK/email/phone from `footer_text`) — address is the only structured fact surfaced.
- No en+nl reshaping into relational tables; that's the future Supabase migration's job, out of scope here.

## Decisions

**Pure projection, no LLM.** The stage only reshapes existing per-stage outputs, so it is cheap, deterministic, and re-runnable anytime. Consequence: the *spec* is written schema-first — the output contract is the deliverable; the code is a trivial join. The shared failure vocab loses `llm_error` here (no calls), leaving `ok` / `empty` / `upstream_failed`.

**Hybrid locale-keyed shape** (over full duplication, over flat). Language-neutral data (score numbers, `evidence`, `address`) lives at root; only translatable *text* (`tagline`, per-axis `reason`) lives under `en`/`nl`. This mirrors conventional i18n (a data layer + a messages layer): the Astro gauge reads `scores.<axis>.score`, the prose reads `<locale>.scores.<axis>.reason`. Full duplication was rejected because it copies the numbers into two places that can drift; a flat shape was rejected because it couples locale to every key.

**fact-extraction spine enumeration** (over `website-resolution` seed, over require-all). One record per company that has a `fact-extraction` file; analytic + translation are left-joined when present. The seed list would emit near-empty shells for uncollected companies; requiring all upstreams would withhold genuinely useful companies (good scores but no tagline yet). fact-extraction is the natural spine: every collected company has one, and it carries the address.

**Block-level null discipline.** Top-level keys are always present; a whole block is `null` when its source stage produced nothing (`scores: null` = not scored), distinct from a null *value* inside a present block (`scores.power.score: null` + `evidence: "no_signal"` = scored, no signal). The `nl` tree mirrors `en`'s keys, nulling fields translation hasn't done. This gives the frontend a stable shape and lets it distinguish "not run" from "run, nothing found" for free.

**Per-company files, frontend globs.** Keeps the stage spec-compliant (single-file-per-company layout, no aggregated layout) and trivially regenerable. If the frontend ever wants a manifest, it builds one at its own build time from the glob — the pipeline does not own that.

**Relax the terminal dependency in `pipeline-architecture`.** The current spec requires every upstream output to exist before `dataset-output` runs, which contradicts partial-emit. The dependency is relaxed to: `fact-extraction` required (the spine); analytic stages and `translation` joined opportunistically.

## Risks / Trade-offs

- **Cross-repo contract drift** (shape changes silently break the Astro build) → spec is schema-first and tests assert the exact shape, including block-level nulls; the field set is an explicit, hand-maintained projection, not auto-discovery.
- **Hybrid shape needs two access paths** (numbers at root, prose under locale) → accepted; it's the idiomatic i18n split and avoids number duplication.
- **Supabase will reshape the document anyway** (nested trees → normalized tables) → we deliberately optimize for the frontend now rather than over-fitting an imagined schema; the projection is cheap to re-shape when that migration lands.
- **Partial records may render as half-empty company pages** → the frontend decides display; `status: ok` with explicit nulls makes "incomplete" legible rather than a silent gap.

## Open Questions

- `source_language` (a "Dutch site" badge) is excluded for now; it's a one-line addition to the projection if the frontend wants it.
