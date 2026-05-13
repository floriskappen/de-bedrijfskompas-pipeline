## Context

This change is architectural and adds no code. All decisions are captured directly in the delta spec at `specs/pipeline-architecture/spec.md` as MODIFIED requirements. There is no "how" to design here — the spec *is* the design.

## Goals / Non-Goals

**Goals:**
- Lock the merged `content-collection` stage and the relaxed seam/layout rules as the contract every future change must respect.

**Non-Goals:**
- Implementing `content-collection`. That's a separate change (`implement-content-collection`).
- Choosing fetching libraries, markdown converters, link-traversal strategy, or page-slug rules — those belong to the implementation change.

## Decisions

See `specs/pipeline-architecture/spec.md`. No additional design decisions beyond what the spec commits to.

## Risks / Trade-offs

None tracked here — operational risks belong to the implementation change that targets this contract.
