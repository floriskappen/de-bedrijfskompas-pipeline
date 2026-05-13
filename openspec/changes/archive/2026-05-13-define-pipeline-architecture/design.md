## Context

This change is architectural and adds no code. All technical decisions are captured directly in the spec (`specs/pipeline-architecture/spec.md`) as normative requirements. There is no separate "how" to design here — the spec *is* the design.

## Goals / Non-Goals

**Goals:**
- Lock the stage sequence, seam contract, and file layout as constraints for every future stage change.

**Non-Goals:**
- Implementing any stage, the pipeline runner, or per-stage data schemas. Each of those is a separate change.

## Decisions

See `specs/pipeline-architecture/spec.md`. No additional design decisions beyond what the spec already commits to.

## Risks / Trade-offs

None tracked at this stage — risks belong to the per-stage changes that will implement against this contract.
