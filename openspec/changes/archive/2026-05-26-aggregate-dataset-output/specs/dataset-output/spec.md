## MODIFIED Requirements

### Requirement: Output Layout and Execution Model

The stage SHALL write all projected company records into a single JSON file at `data/dataset-output/companies.json` containing a JSON list of company records, and SHALL support the three execution modes: standalone CLI (`python -m pipeline.dataset_output`), an orchestrator-callable entry point with the same input/output contract, and a dry-run mode that performs all logic but writes nothing. The stage SHALL raise a hard error if any duplicate `company_id` values appear in the final aggregated output list.

#### Scenario: CLI writes single aggregated file

- **WHEN** a developer runs `python -m pipeline.dataset_output` with the upstream directories populated
- **THEN** all company records are aggregated and written to `data/dataset-output/companies.json` as a JSON array

#### Scenario: Dry-run writes nothing

- **WHEN** the stage runs in dry-run mode
- **THEN** it produces the same records in memory but writes no file under `data/dataset-output/`

#### Scenario: Company-id collision refuses

- **WHEN** the aggregated record list contains duplicate `company_id` values
- **THEN** the stage raises a `RuntimeError` rather than writing
