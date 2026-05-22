## MODIFIED Requirements

### Requirement: Out of Scope

The stage SHALL NOT:

- Score, rate, or rank the company (`bcorp-scoring` and other stage-5 analytic stages are downstream).
- Produce the concise human-facing front-end description (`tagline-extraction` derives that from the dossier).
- Perform philosophical-framework mapping, tagging, or ikigai-matching.
- Extract structured facts such as the HQ address (that is `fact-extraction`).
- Re-fetch or re-parse raw HTML — it consumes only `content-collection` artefacts.

#### Scenario: No scoring emitted

- **WHEN** the source contains heavy marketing language
- **THEN** the dossier reflects the de-marketed substance but emits no score or rating
