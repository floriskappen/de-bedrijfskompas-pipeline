## Why

The project judges companies on the five structural axes in `docs/GLOBAL_SCORING_FRAMEWORK.md` (Substance, Ecology, Power, Embeddedness, Posture) — the honest successor to the original B-Corp scaffold. The frontend's per-company pentagon and the map-overview axis filters need a structured, per-axis score with a human-readable justification. The de-marketed `content-summarization` dossier is the right input: it is already faithful and marketing-stripped, so scoring reads it rather than the raw site.

## What Changes

- Add a new stage-5 analytical stage `global-scoring` that reads the `content-summarization` dossier and produces, per company, a score for each of the five axes. Each axis carries a `score` (integer 0–100, or `null` when there is no signal), an `evidence` level (`well_evidenced` / `partial` / `no_signal`), and a bilingual `reason` (`en` then `nl`).
- The stage produces **no composite/global number** — the framework forbids collapsing the five axes into one score. It emits only the per-axis profile.
- Silence is read asymmetrically per the framework: vagueness counts *against* Substance/Ecology, is neutral for Embeddedness, and is never penalised for Power (default `no_signal`, `score: null`). These rules live in the versioned prompt.
- The reason text is generated in English first, then translated to Dutch, in the **same** LLM call (same pattern as `tagline-extraction`).
- The stage gates on the dossier frontmatter `status` being `ok`; anything else cascades to `upstream_failed` with no LLM call. It follows the `ok` / `empty` / `upstream_failed` / `llm_error` status convention and supports CLI, orchestrator, and dry-run modes. Its prompt lives versioned under `prompts/`. One DeepSeek-v4-Flash (OpenRouter) call per company, model overridable via env var.
- **BREAKING** (spec-only, no code exists yet): rename every `bcorp-scoring` reference in `pipeline-architecture` to `global-scoring`.

## Capabilities

### New Capabilities
- `global-scoring`: score the dossier on the five framework axes (0–100 + evidence level + bilingual reason per axis); gate on upstream status; emit one JSON record per company; no composite score.

### Modified Capabilities
- `pipeline-architecture`: rename `bcorp-scoring` → `global-scoring` in the Stage Sequence and Output File Layout requirements.

## Impact

- New module `pipeline/global_scoring/`; new prompt `prompts/global-scoring.md`; new output dir `data/global-scoring/<company-id>.json`.
- Reads `data/content-summarization/<company-id>.md`. Uses the existing OpenRouter client pattern (self-contained `llm.py`). No new dependencies.
- Spec edits to `openspec/specs/pipeline-architecture/spec.md` (rename only).
- The five-axis definitions and silence rules in `docs/GLOBAL_SCORING_FRAMEWORK.md` are the source of truth for the prompt; expect iterative prompt tuning against the test set during implementation.
