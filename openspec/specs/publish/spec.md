# publish Specification

## Purpose
TBD - created by archiving change add-pipeline-orchestrator-and-publish. Update Purpose after archive.
## Requirements
### Requirement: Input File

The stage SHALL read `data/dataset-output/companies.json` as its single input. If the file is absent or not parseable as JSON, the stage SHALL exit non-zero without contacting any remote service.

#### Scenario: Missing input

- **WHEN** `data/dataset-output/companies.json` does not exist
- **THEN** the stage exits non-zero and no GitHub API call is made

#### Scenario: Malformed input

- **WHEN** `data/dataset-output/companies.json` exists but is not valid JSON
- **THEN** the stage exits non-zero and no GitHub API call is made

### Requirement: Manifest Shape

The stage SHALL produce a `manifest.json` sidecar with these keys, all required:

- `generated_at`: ISO 8601 UTC string with second precision (`YYYY-MM-DDTHH:MM:SSZ`), captured at publish time.
- `pipeline_git_sha`: the SHA of `HEAD` in the pipeline repo at publish time (full or short form, as returned by `git rev-parse HEAD`).
- `company_count`: integer length of the input JSON array.
- `schema_version`: integer constant, initially `1`, bumped manually when the `companies.json` record shape changes in a way the frontend must adapt to.

#### Scenario: Manifest matches data

- **WHEN** the input contains 5,231 records and publish runs at `2026-05-27T14:30:00Z` with pipeline HEAD `a7ed347`
- **THEN** the manifest is `{"generated_at": "2026-05-27T14:30:00Z", "pipeline_git_sha": "a7ed347", "company_count": 5231, "schema_version": 1}`

### Requirement: Release Tag and Asset Naming

The stage SHALL create one GitHub Release per invocation. The release tag and name SHALL both be the UTC timestamp formatted as `YYYY-MM-DDTHH-MM-SSZ` — the same instant as `manifest.generated_at`, with `:` replaced by `-` for tag-name safety. The release SHALL carry exactly two assets with these fixed filenames, regardless of when they were generated:

- `companies.json`
- `manifest.json`

#### Scenario: Standard release

- **WHEN** publish runs at the instant `2026-05-27T14:30:00Z`
- **THEN** the resulting release has tag and name `2026-05-27T14-30-00Z` and carries assets named `companies.json` and `manifest.json`

#### Scenario: Tag collision

- **WHEN** publish runs within the same UTC second as an existing release on the pipeline repo
- **THEN** the stage exits non-zero

### Requirement: Upload Mechanism

The stage SHALL invoke the `gh` CLI to create the release and upload assets. It SHALL NOT call the GitHub REST API directly. Authentication SHALL be whatever `gh` is configured with (interactive login or `GH_TOKEN`).

#### Scenario: gh not installed

- **WHEN** `gh` is not available on PATH
- **THEN** the stage exits non-zero before generating the manifest

#### Scenario: gh not authenticated

- **WHEN** `gh` is installed but lacks credentials for the pipeline repo
- **THEN** the stage exits non-zero and `data/dataset-output/companies.json` is left untouched

### Requirement: Execution Modes

The stage SHALL be runnable as `python -m pipeline.publish`. It SHALL support a `--dry-run` mode that performs all local logic (manifest generation, tag derivation) but invokes no `gh` commands and writes nothing to disk.

#### Scenario: Standalone invocation

- **WHEN** an operator runs `python -m pipeline.publish` after a successful pipeline run
- **THEN** a release is created and two assets are uploaded

#### Scenario: Dry-run

- **WHEN** `python -m pipeline.publish --dry-run` is invoked
- **THEN** the stage prints the intended tag and the manifest body to stdout, performs no upload, writes no files, and exits zero

