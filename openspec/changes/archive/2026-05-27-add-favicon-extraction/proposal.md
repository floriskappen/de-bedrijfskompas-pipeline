## Why

The frontend application needs a high-quality favicon or brand logo URL to display as a visual identifier next to each company in the search UI. Currently, the pipeline does not capture or propagate favicon/logo links from company websites.

## What Changes

- **Modify content-collection**: Extend the homepage crawler to extract `<link>` icon tags, rank them based on size (preferring 512x512) and type, and save the best URL to `_meta.json` as `favicon_url` (falling back to `/favicon.ico` if none are found, or `null` if the homepage fetch fails).
- **Modify dataset-output**: Project `favicon_url` from the fact-extraction output JSON to the root level of each company record in the final `companies.json` file.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `content-collection`: Extract and save the company's favicon URL to the `_meta.json` file during website crawling.
- `dataset-output`: Project the extracted favicon URL into the final frontend-facing aggregated company list.

## Impact

- **Affected Stages**:
  - `pipeline/content_collection`: Extract favicon from homepage HTML and save to `_meta.json`.
  - `pipeline/dataset_output`: Add `favicon_url` projection to the root of the output record.
- **Affected Data Files**:
  - `data/content-collection/<company-id>/_meta.json` (adds `favicon_url`)
  - `data/fact-extraction/<company-id>.json` (automatically carries forward `favicon_url`)
  - `data/dataset-output/companies.json` (adds `favicon_url` at root)
