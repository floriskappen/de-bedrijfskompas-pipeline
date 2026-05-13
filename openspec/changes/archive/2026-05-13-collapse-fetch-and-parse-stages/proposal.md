# Proposal: Collapse `page-fetching` and `html-parsing` into a single `content-collection` stage

## Why

The current pipeline-architecture spec defines `page-fetching` (stage 2) and `html-parsing` (stage 3) as separate stages, each writing its own intermediate output. In practice, raw HTML is uninteresting on its own — nobody reads `data/page-fetching/<id>.json` directly, and storing it just to read it back in stage 3 wastes disk, doubles I/O, and creates a stale-intermediate failure mode (HTML from a month-old fetch parsed against today's parser logic). Merging the two avoids the round-trip and aligns the on-disk artifacts with what's actually useful downstream: cleaned markdown per page.

## What Changes

- Replace stages 2 (`page-fetching`) and 3 (`html-parsing`) with a single stage 2 named `content-collection`. The remaining stages shift up by one position.
- The new stage's job: read a company record from `data/website-resolution/<company-id>.json`, fetch the homepage and any additional in-scope pages, strip HTML boilerplate (nav, footer, scripts, ads, cookie banners), convert each page to markdown.
- **BREAKING (spec-only):** modify the pipeline-architecture spec's Output File Layout requirement. The current rule (`data/<stage>/<company-id>.json`, one file per company) is relaxed to also permit `data/<stage>/<company-id>/<page-slug>.md` (one *directory* per company, containing one markdown file per page) for stages that produce multiple per-company artifacts.
- **BREAKING (spec-only):** modify the Stage Sequence requirement to drop `html-parsing` and renumber. Downstream stage numbers (`content-summarization`, the analytical fan-out, `dataset-output`) shift up but their names and dependencies are unchanged.
- No code is added or removed in this change. This is a purely architectural refactor.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `pipeline-architecture`: three modified requirements —
  1. Stage Sequence: collapse stages 2 and 3 into `content-collection`; renumber downstream.
  2. Stage Seam Contract: relax the "JSON file(s)" wording to "structured file(s) on disk in a stage-specific format" so a stage producing markdown still satisfies the no-in-memory-handoff intent.
  3. Output File Layout: allow `data/<stage>/<company-id>/<page-slug>.<ext>` (per-company subdirectories) for stages whose output is naturally multi-document. Single-file-per-company stages remain unchanged.

## Impact

- **Specs:** `pipeline-architecture` gets two MODIFIED requirements. No new capability is created.
- **Code:** none changed by this change. The yet-to-be-written stage will follow the new contract.
- **Data:** no existing `data/page-fetching/` or `data/html-parsing/` outputs exist, so nothing to migrate.
- **Future changes:** the next implementation change (`implement-content-collection`) targets the new contract instead of the old two-stage one. Eliminates one full stage's worth of code and tests.
