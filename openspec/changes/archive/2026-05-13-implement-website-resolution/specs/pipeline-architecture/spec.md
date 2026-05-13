## ADDED Requirements

### Requirement: Stage Execution Model

Every pipeline stage SHALL be implemented as a self-contained Python module that supports three execution modes:

1. **Standalone CLI**: the stage MUST be runnable from the command line as `python -m <stage-module>` (or equivalent), reading its input from disk (or the configured source for stage 1) and writing its output to disk per the Output File Layout requirement.
2. **Orchestrator-callable**: the stage MUST expose a programmatic entry point (a function) that a future pipeline orchestrator can invoke without subprocess overhead. The entry point's contract MUST match the on-disk seam — same input shape in, same output shape out — so behavior does not diverge between modes.
3. **Dry-run / no-write mode**: the stage MUST support a mode in which all logic runs (search calls, transformations, etc.) but no output files are written to disk. Dry-run mode is intended for tests; it MAY return outputs in memory to the caller.

These three modes apply to every stage in the Stage Sequence requirement, including any future analytical stages added under stage 5.

#### Scenario: Stage runs standalone from CLI

- **WHEN** a developer runs `python -m pipeline.<stage>` with the stage's expected input available
- **THEN** the stage processes the input and writes outputs to `data/<stage>/<company-id>.json` per the Output File Layout

#### Scenario: Stage callable by an orchestrator

- **WHEN** an orchestrator imports the stage's module and calls its programmatic entry point with an input record
- **THEN** the stage produces the same output it would have written to disk in CLI mode

#### Scenario: Dry-run produces no files

- **WHEN** the stage is invoked in dry-run mode against a batch of inputs
- **THEN** the stage performs its normal processing logic but writes nothing to `data/<stage>/`

#### Scenario: Behavior parity across modes

- **WHEN** the same input is processed in CLI mode, orchestrator mode, and dry-run mode
- **THEN** the resulting output record is identical in all three modes (the only difference is whether/where it is persisted)
