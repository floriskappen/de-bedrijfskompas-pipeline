## MODIFIED Requirements

### Requirement: Per-Axis Entry Shape

Each axis entry SHALL be an object with three members: `score`, `evidence`, and `reason`. `score` SHALL be an integer in the inclusive range 0–100, or `null`. `evidence` SHALL be exactly one of the fixed vocabulary `well_evidenced`, `partial`, `no_signal`. `reason` SHALL be an object with a non-empty `en` string member. The stage SHALL enforce the score↔evidence invariant by normalization, not rejection: a numeric `score` returned with `evidence: no_signal` keeps its score and is recorded as `evidence: partial`; a `null` score returned with a numeric evidence level is recorded as `evidence: no_signal`. In the persisted output a `null` score therefore always carries `evidence: no_signal`, and a numeric score never does. Only genuinely unusable axis output (a missing entry, an evidence value outside the vocabulary, a non-integer non-null score, or an empty/missing `reason.en`) is treated as an LLM error.

#### Scenario: Evidenced axis carries a numeric score

- **WHEN** an axis is `well_evidenced` or `partial`
- **THEN** its `score` is an integer 0–100 and its `reason.en` is non-empty

#### Scenario: No-signal axis carries a null score

- **WHEN** an axis has `evidence: no_signal`
- **THEN** its `score` is `null` and its `reason.en` explains that the dossier gives no signal for that axis

#### Scenario: Inconsistent score and evidence are normalized, not rejected

- **WHEN** the model returns a numeric `score` paired with `evidence: no_signal` for one axis (or a `null` score paired with a numeric evidence level)
- **THEN** the stage normalizes that axis (keeping the numeric score as `partial`, or forcing `no_signal` for the null score) and still produces the company's full five-axis record, rather than discarding it as an LLM error

### Requirement: Reason Content

Each axis `reason.en` SHALL state, in plain language, why that axis received its score, grounded in the dossier's substance. Because the dossier is an internal artefact never shown to the user, the reason SHALL NOT quote or cite the dossier or the source website; it SHALL explain the judgement in its own words. It SHALL use no marketing adjectives and add no facts absent from the dossier.

#### Scenario: Reason explains rather than quotes

- **WHEN** an axis score is justified
- **THEN** its `reason.en` paraphrases the judgement in plain language and contains no quotation of dossier or website text

### Requirement: LLM Generation

The stage SHALL produce each company's scores with a single LLM call via OpenRouter, returning a JSON object covering all five axes. The prompt SHALL be loaded from a versioned file under `prompts/`, identified by name; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `GLOBAL_SCORING_MODEL` environment variable. A response that cannot be parsed and validated into the five-axis schema (all axes present, each with a valid `score`, `evidence`, and non-empty `reason.en`) SHALL be treated as an LLM error.

#### Scenario: Prompt loaded from versioned file

- **WHEN** the stage builds the LLM request
- **THEN** the instruction text is read from a named file under `prompts/`, not from a string literal in a `.py` module

#### Scenario: Model override honoured

- **WHEN** `GLOBAL_SCORING_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Malformed response is an error

- **WHEN** the model returns text that does not validate into the five-axis schema
- **THEN** the company's record is written with `status: llm_error` and `scores: null`
