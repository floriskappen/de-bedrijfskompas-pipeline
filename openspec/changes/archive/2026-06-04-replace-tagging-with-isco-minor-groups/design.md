## Context

The tagging stage is a dossier-derived analytic stage that currently emits custom capability-family slugs. Those slugs are useful for a first UI filter, but they are not standard, not detailed enough for ikigai matching, and require a large prompt section to explain project-specific boundaries.

ISCO-08 minor groups are a better canonical spine for this stage: they are occupation-side, stable, 3-digit codes, and the full set is small enough to include directly in the tagging prompt. The frontend can still group these codes into a smaller domain projection, but the pipeline output should preserve the lower-resolution occupational evidence.

## Goals / Non-Goals

**Goals:**
- Make `data/tagging/<company-id>.json` emit ISCO-08 minor-group tags.
- Keep tags language-neutral and pass them through to `dataset-output`.
- Preserve project-specific inference signals: prominence and uncertainty.
- Keep the tagging stage self-contained and consistent with the other dossier-derived analytic stages.

**Non-Goals:**
- Fetch or maintain ESCO occupation data in this change.
- Implement the frontend domain projection over ISCO codes.
- Generate Dutch labels for ISCO/ESCO concepts.
- Add ikigai matching logic.
- Make tagging a translation input.

## Decisions

**Use ISCO-08 minor groups, not sub-major groups or ESCO occupations.** Minor groups give 130 stable choices: detailed enough to distinguish software developers from ICT support technicians, doctors from care assistants, and engineers from machine operators, while still short enough for one controlled prompt. Sub-major groups are too blunt for matching; ESCO occupations are too numerous for reliable company-level inference from a public dossier.

**Store the 3-digit code as the canonical tag value.** The tag field is `isco_code`, not a generated slug or label. Codes are language-neutral, sortable by hierarchy, and roll up mechanically to sub-major and major groups by prefix. Labels can live in prompt/reference data and frontend label maps without becoming the identity.

**Keep `capability_tags` as the output block name.** The meaning remains "what occupational capability groups the company runs on." Renaming the block to `isco_tags` would make the output clearer in isolation but create unnecessary churn for dataset-output and frontend consumers that already expect a tag block.

**Add required `confidence`.** Prominence answers "how central is this group to the company"; confidence answers "how well evidenced is this inference." Keeping both prevents thin websites from being forced into false certainty and gives later matching logic a way to downweight structural guesses.

**Keep dataset-output as a verbatim pass-through.** Dataset-output should not derive sub-major groups, UI domains, or labels. Its contract is to project upstream stage output into a frontend-facing aggregate without transforming the tagging semantics.

**Keep the prompt concise around the vocabulary.** The 130 labels should be listed, grouped by sub-major group, but not explained one-by-one. The detailed guidance should focus on inference errors ISCO cannot solve, especially "serving a sector does not mean staffing it" and "ordinary internal administration does not make every company an admin company."

## Risks / Trade-offs

- **[LLM over-tags generic internal functions]** → Prompt calibration and parser tests should enforce that admin, sales, management, clerical, and finance codes are omitted unless they are part of the company's actual product or service.
- **[3-digit codes are still coarse for some tech/data work]** → This is acceptable for company tagging; ESCO occupations can be layered later for user-side matching without changing the ISCO parent spine.
- **[Breaking output shape affects consumers]** → Update tagging and dataset-output specs/tests together; downstream consumers can migrate from `family` to `isco_code`.
- **[ISCO labels are English in the prompt]** → Labels are not user-facing in this stage. Dutch UI labels should come from a later reference-data/frontend change.
