## Context

This change is architectural and adds no code. The decision is captured directly in the delta spec at `specs/pipeline-architecture/spec.md` as a MODIFIED requirement.

## Goals / Non-Goals

**Goals:**
- Lock the linear order `content-collection → fact-extraction → content-summarization → theme analytics → dataset-output` so the upcoming implementation changes target the correct dependency graph.

**Non-Goals:**
- Implementing any of the affected stages. Each is its own implementation change.
- Deciding whether `content-summarization` should also receive `fact-extraction`'s output as anchoring input — that's an implementation-time decision for `implement-content-summarization`.

## Decisions

See `specs/pipeline-architecture/spec.md`. No additional design decisions beyond what the spec commits to.

## Risks / Trade-offs

None tracked here — operational risks belong to the implementation changes that target this contract.
