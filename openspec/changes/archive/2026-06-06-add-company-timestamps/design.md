## Context

`dataset-output` currently re-derives every record from upstream per-company files on each run. There is no notion of when a company first appeared in the output or when its record last changed. We need to add lifecycle timestamps without making the stage stateful in a brittle way.

## Goals / Non-Goals

**Goals:**
- Per-company `created_at` (stable across runs) and `updated_at` (bumps only on content change) in `companies.json`.
- Persistence that survives `data/dataset-output/companies.json` being regenerated.

**Non-Goals:**
- Tracking per-field change history.
- Surfacing timestamps from upstream stages (fact-extraction, scoring, etc.).

## Decisions

**Per-company timestamp sidecars at `data/dataset-output/timestamps/<company-id>.json`.** Each file holds `{ "created_at", "updated_at", "content_hash" }`. Chosen over a single combined file so the stage stays consistent with the per-company file pattern used everywhere else in the pipeline, and so concurrent/partial runs do not contend on a shared file. Rejected: embedding timestamps in `companies.json` only — that file is a build artifact and gets rewritten wholesale.

**Content hash over the record minus the timestamp fields.** `updated_at` bumps iff the SHA-256 of the canonicalised record (sorted keys, timestamps stripped) differs from the stored `content_hash`. Chosen over deep-equality against the prior record because the hash is cheap to store and lets us decide without keeping a full prior copy.

**Timestamps captured once per run, at stage start.** All bumps in a single run share the same `updated_at` value. Chosen over per-record `datetime.now()` calls so a single pipeline run produces a coherent timestamp set.

## Risks / Trade-offs

- [Sidecar drift if a company is removed from upstream] → On read, ignore sidecars whose company is no longer in the fact-extraction spine; do not delete them (cheap, and avoids data loss on transient upstream gaps).
- [First run after this change bumps `updated_at` for every company] → Acceptable; this is a one-time effect and is the correct semantics (records did just acquire a new shape).
