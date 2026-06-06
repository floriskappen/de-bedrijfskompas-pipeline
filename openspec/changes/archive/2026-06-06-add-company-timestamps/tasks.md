## 1. Timestamp persistence in dataset-output

- [x] 1.1 Add a timestamps module to the dataset-output stage: canonicalise a record (sorted keys, `created_at`/`updated_at` stripped), SHA-256 hex over the canonical bytes, and load/write `data/dataset-output/timestamps/<company-id>.json` sidecars.
- [x] 1.2 Capture a single ISO 8601 UTC run timestamp (`YYYY-MM-DDTHH:MM:SSZ`) at stage start and thread it through record assembly.
- [x] 1.3 During record assembly, apply the lifecycle rule per record: new sidecar → both timestamps = run timestamp; matching hash → copy both verbatim; differing hash → keep `created_at`, set `updated_at` = run timestamp.
- [x] 1.4 Write/overwrite sidecars only when a record is new or its content hash changed. Skip all sidecar writes in dry-run mode while still computing timestamps in memory.

## 2. Tests

- [x] 2.1 `test_first_time_seen_writes_sidecar_and_sets_both_timestamps` covers the "First time a company is seen" scenario.
- [x] 2.2 `test_unchanged_record_preserves_timestamps_and_does_not_rewrite_sidecar` covers "Unchanged record preserves both timestamps".
- [x] 2.3 `test_changed_record_bumps_updated_at_only` covers "Changed record bumps updated_at only".
- [x] 2.4 `test_content_hash_ignores_timestamp_fields` covers "Hash excludes the timestamp fields".
- [x] 2.5 `test_single_run_shares_one_updated_at` covers "Single run shares one timestamp".
- [x] 2.6 `test_dry_run_leaves_sidecars_untouched` covers "Dry-run does not write sidecars".
- [x] 2.7 `test_fully_populated_record_includes_timestamps` and `test_root_only_holds_timestamps` cover the modified Output Record Shape scenarios.

## 3. Wire-up

- [x] 3.1 Bump `schema_version` in the `publish` stage manifest to reflect the new record shape.
- [x] 3.2 Run the stage end-to-end on the test set and confirm `companies.json` records carry `created_at` / `updated_at` and that a second run leaves both timestamps untouched.
