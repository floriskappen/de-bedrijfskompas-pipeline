# de-bedrijfskompas — pipeline

> Company-first discovery pipeline: scrape, extract, and de-marketing-ify company website data.

`de-bedrijfskompas` is a project to help you find companies you actually care about working at —
cutting through the marketing buzzwords on job boards and company sites so you can see what a
company *really* does, and build up a list of interesting ones over time (see
[`CONSTITUTION.md`](./CONSTITUTION.md) for the full motivation).

This repo is the **pipeline**: an offline Python batch pipeline that ingests, extracts and
transforms company website data into a structured dataset. The project is split across three
repos:

| Repo | Role |
| --- | --- |
| [de-bedrijfskompas-pipeline](https://github.com/floriskappen/de-bedrijfskompas-pipeline) (this repo) | Scrape, extract and transform company data into a structured dataset |
| [de-bedrijfskompas-scraper](https://github.com/floriskappen/de-bedrijfskompas-scraper) | Source scraper that feeds company URLs / raw data into the pipeline |
| [de-bedrijfskompas-frontend](https://github.com/floriskappen/de-bedrijfskompas-frontend) | Static frontend that consumes the pipeline's output dataset |

## Architecture

Python, offline batch pipeline, made up of multiple stages. Intermediate data is persisted
between stages so each stage has a clean input and output. LLMs are used for analysis; prompts
live in [`prompts/`](./prompts) as versioned files loaded by name — no inline prompts in code.

Pipeline stages (see [`pipeline/`](./pipeline)):

- `website_resolution` — resolve/normalize company websites
- `content_collection` — fetch and parse page content
- `fact_extraction` — extract structured facts from content
- `content_summarization` — produce concise, de-marketed summaries
- `tagline_extraction` — generate short taglines
- `translation` — translate content
- `tagging` — ISCO-based capability tagging
- `geocoding` — geocode company addresses
- `global_scoring` — score companies
- `dataset_output` — assemble the final dataset
- `publish` — publish the dataset

## Requirements

- Python >= 3.11

## License

Copyright (c) 2026 Floris Kappen. This project is licensed under the
[GNU General Public License v3.0](./LICENSE).
