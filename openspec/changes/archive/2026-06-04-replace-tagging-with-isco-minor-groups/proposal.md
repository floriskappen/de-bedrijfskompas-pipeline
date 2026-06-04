## Why

The current tagging stage uses 19 hand-made capability families, which are too coarse for later ikigai matching and not grounded in a standard occupation spine. Replacing them with ISCO-08 minor groups gives the company-level tags a stable 3-digit vocabulary while staying small enough for LLM inference.

## What Changes

- **BREAKING** Replace tagging output entries from `{ family, prominence }` to `{ isco_code, prominence, confidence }`.
- Use the 130 ISCO-08 minor groups as the only allowed tagging vocabulary.
- Keep `prominence` as the project-specific signal for whether an occupation group is core, supporting, or incidental to the company.
- Add per-tag `confidence` so thin or structurally inferred tags can be downweighted later.
- Update the tagging prompt to list ISCO-08 minor groups and preserve the "serving a sector is not staffing it" inference rule.
- Update dataset output to pass through the new tag shape verbatim.
- Keep tagging out of translation: ISCO codes remain language-neutral and labels are resolved outside the LLM translation stage.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `tagging`: replace the custom 19-family capability vocabulary with ISCO-08 3-digit minor-group codes and add tag confidence.
- `dataset-output`: update the frontend-facing `capability_tags` projection contract to carry ISCO tag objects verbatim.
- `pipeline-architecture`: update the stage-sequence description so tagging is described as ISCO minor-group tagging rather than slug-family tagging.

## Impact

- Affected code: `pipeline/tagging/llm.py`, `pipeline/tagging/core.py`, `pipeline/tagging/__init__.py`, `prompts/tagging.md`, dataset-output tests and specs.
- Affected output contract: `data/tagging/<company-id>.json` and `data/dataset-output/companies.json`.
- Affected tests: tagging parser/shape tests, dataset-output pass-through/status tests, and pipeline-architecture wording tests if needed.
- No new runtime dependency is required; the ISCO vocabulary should be stored as versioned project data or constants.
