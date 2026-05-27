## Context

The frontend application needs to display brand icons/favicons for each company. This requires the backend pipeline to discover, extract, and propagate a high-quality favicon URL from the company's website to the final dataset.

## Goals / Non-Goals

**Goals:**
- Extract absolute favicon URLs from the homepage HTML during website crawl.
- Identify the highest-quality candidate closest to the ideal size of 512x512.
- Propagate the favicon URL to the root of each company's frontend record in `companies.json`.

**Non-Goals:**
- Downloading, saving, or caching favicon image files in the pipeline.
- Validating favicon URL reachability via HTTP requests.

## Decisions

### Decision 1: Stage Selection for Extraction
- **Choice**: Extract the favicon URL during the `content-collection` stage.
- **Alternatives Considered**: Extract in `website-resolution` or create a new dedicated stage.
- **Rationale**: `content-collection` already fetches the homepage HTML. Parsing this HTML for link tags adds zero extra network overhead. Doing it in `website-resolution` would violate its no-fetch constraint, and a separate stage would duplicate HTTP requests.

### Decision 2: Favicon Selection and Ranking Heuristic
- **Choice**: Parse `<link>` tags with `rel` containing `icon` or `apple-touch-icon`. Group by size $\ge 512$ (sorted ascending) and size $< 512$ (sorted descending) to find the closest match to 512x512. Use modern link tags as a tie-breaker.
- **Alternatives Considered**: Simply select the first `<link rel="icon">` tag, or download images to inspect headers.
- **Rationale**: Downloading violates the "no download" goal. Relying on tag order is fragile since legacy 16x16 icon tags often appear first. Sorting on parsed `sizes` attribute is robust and lightweight.

### Decision 3: Fallback Logic
- **Choice**: Default to `<homepage_url>/favicon.ico` if no tags exist in HTML. If the homepage fetch fails, set `favicon_url` to `null`.
- **Alternatives Considered**: Query external favicon APIs (e.g. Google's favicon API).
- **Rationale**: External services introduce third-party dependencies, rate-limit risks, and privacy concerns. Fallback to `/favicon.ico` matches standard browser behavior.

### Decision 4: Data Propagation Pathway
- **Choice**: Save `favicon_url` to `_meta.json`. Let `fact-extraction` auto-forward the key, and update `dataset-output` to project it to the root of the company record.
- **Alternatives Considered**: Have `dataset-output` read the `content-collection` folder directly.
- **Rationale**: Keeps the pipeline architecture clean. `dataset-output` only queries stages defined in its input specs, and the existing spine dependencies are maintained.

## Risks / Trade-offs

- **[Risk]**: Website declares a very large/incorrect size attribute (e.g., `sizes="any"` or `sizes="5000x5000"`) but is actually low quality.
  - **Mitigation**: Treating `sizes="any"` as `512` prefers it for vector graphics (SVGs), but incorrect declarations are accepted as-is; we do not validate the image content.
- **[Risk]**: Fallback `/favicon.ico` does not exist on the server (returns 404).
  - **Mitigation**: Accepting this risk as standard fallback behavior. We do not issue HTTP requests to verify fallback existence to preserve speed.
