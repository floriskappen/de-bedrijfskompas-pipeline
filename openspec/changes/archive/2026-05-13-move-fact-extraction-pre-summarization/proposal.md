# Proposal: Move `fact-extraction` to run before `content-summarization`

## Why

The current architecture puts `fact-extraction` downstream of `content-summarization`, so it reads a summary instead of the raw content. This is wrong for two reasons:

1. **Verbatim facts get lost in summarization.** Extracting an HQ address, founding year, or exact employee count requires the original text. A summary may paraphrase the address, drop it as "boring", or never have seen it in the first place (e.g. footer text the summarization input deliberately excluded).
2. **The split was conflating two different needs.** `content-summarization` exists to compress N pages of markdown into a small, reusable input — the *token funnel* for cheap-to-run analytic stages (bullshit-scoring, bcorp-scoring, tagging, etc). Those stages work on *themes and tone*, which a faithful summary preserves. `fact-extraction` is the only stage that needs the *exact words*, so it belongs upstream of the funnel, not after it.

Naming the principle: **stages that need verbatim content read `content-collection`; stages that work on themes read `content-summarization`.**

## What Changes

- **BREAKING (spec-only):** modify the `Stage Sequence` requirement in `pipeline-architecture` so that:
  - `fact-extraction` becomes stage 3, reading `content-collection`'s output. It runs against verbatim markdown (+ footer text and per-page metadata in `_meta.json`).
  - `content-summarization` becomes stage 4, reading `content-collection`'s output (and benefiting from the already-extracted facts as anchors when useful).
  - The theme-analytic stages (`bullshit-scoring`, `bcorp-scoring`, future `tagging` / `ikigai-matching` / etc.) become stage 5, reading the summary from `content-summarization`.
  - `dataset-output` becomes stage 6.
- No new capabilities. No code changes. Purely a re-ordering / dependency-graph correction in the architecture spec.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `pipeline-architecture`: modify `Stage Sequence` to slot `fact-extraction` before `content-summarization`, collapse the theme-analytic stages into a single layer reading the summary, and renumber `dataset-output`.

## Impact

- **Specs:** one MODIFIED requirement in `pipeline-architecture`. No new capability spec.
- **Code:** none — no stages are implemented yet that this affects.
- **Future changes affected:**
  - `implement-content-collection` (in-flight): its output now has two direct consumers (`fact-extraction` + `content-summarization`). The output contract (markdown + `_meta.json` with footer text) was already designed with both in mind, so no rework needed.
  - `implement-fact-extraction` (future): should read `data/content-collection/<id>/*.md` plus `_meta.json` (especially `footer_text`). The implementer should prioritize `index.md` and `contact.md` since those are where structured facts (HQ address, contact details) live.
  - `implement-content-summarization` (future): produces the compact prose that the stage-5 theme-analytic stages will read.
