# Proposal: Define pipeline architecture

## Intent
establish the pipeline's stage decomposition and data flow contract before implementing any stage. this change adds no code; it sets the structural constraints all subsequent changes must respect.

## Scope
- define the ordered list of pipeline stages:
    1. website-resolution
    2. page-fetching
    3. html-parsing
    4. content-summarization
    5. parallel stages, order doesn't matter, they depend on content summarization
        - fact-extraction
        - bullshit-scoring
        - bcorp-scoring
        - potentially other data extraction like ikigai things, tagging etc
    6. dataset-output
- define the seam contract: each stage reads data (e.g. JSON from disk in the MVP), writes data (e.g., JSON to disk in the MVP)
- define the file naming convention for stage outputs

## Out of scope
- any stage's internal behavior (covered by per-stage specs)
- the pipeline runner's implementation (covered by a later change)
- schema details for inter-stage data (defined per-stage)
