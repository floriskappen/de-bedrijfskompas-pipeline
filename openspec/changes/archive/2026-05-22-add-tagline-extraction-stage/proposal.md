## Why

The frontend needs a one-glance, plain-language answer to "what does this company actually do?" — the de-marketed dossier from `content-summarization` is faithful but too long to scan. The architecture reserved a stage-5 slot for this under the name `bullshit-scoring`, but that name is a misnomer: the stage generates a short description, it does not score anything.

## What Changes

- Add a new stage-5 stage `tagline-extraction` that reads the `content-summarization` dossier and produces a bilingual (en + nl) plain-language one-liner per company.
- The tagline leads with "who pays them and for what" (customer / revenue source first), uses no jargon or marketing words, and is understandable by a non-technical reader. One sentence preferred; a second sentence is allowed only as an exception for thin or self-contradictory dossiers.
- The stage gates on the dossier's frontmatter `status` being `ok`; anything else cascades to `upstream_failed` without an LLM call. It follows the existing `ok` / `upstream_failed` / `llm_error` status convention and supports CLI, orchestrator, and dry-run modes. Its prompt lives versioned under `prompts/`.
- **BREAKING** (spec-only, no code exists yet): rename every `bullshit-scoring` reference in `pipeline-architecture` to `tagline-extraction`.
- Formalize the always-emit-a-record + shared status-vocabulary convention (already practiced by `fact-extraction` and `content-summarization`) as an explicit `pipeline-architecture` requirement, so downstream `dataset-output` can distinguish "succeeded" / "failed, here's why" / "not run".

## Capabilities

### New Capabilities
- `tagline-extraction`: distill the dossier into a bilingual, jargon-free one-liner; gate on upstream status; emit one JSON record per company.

### Modified Capabilities
- `pipeline-architecture`: rename `bullshit-scoring` → `tagline-extraction`; add a Failure Propagation requirement covering always-emit-a-record and the shared status vocabulary.
- `content-summarization`: remove the now-dead `bullshit-scoring` name from its Out-of-Scope requirement (it referenced the renamed stage as a scoring example).

## Impact

- New module `pipeline/tagline_extraction/`; new prompt `prompts/tagline-extraction.md`; new output dir `data/tagline-extraction/<company-id>.json`.
- Spec edits to `openspec/specs/pipeline-architecture/spec.md` (rename + new requirement).
- Reads `data/content-summarization/<company-id>.md`. Uses the existing OpenRouter client pattern. No new dependencies.
