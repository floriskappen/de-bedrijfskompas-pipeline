## MODIFIED Requirements

### Requirement: Input Record Shape

The stage SHALL read each company's input from `data/content-collection/<company-id>/`: `_meta.json` (always present; `status`, `footer_text`, `structured_text`, and `pages` are load-bearing) plus optional per-page markdown.

For each **address-intent** slug — recognised by a contact/legal/privacy/terms/imprint stem anywhere in the slug (covering `contact`, `contact-us`, `over-ons`, `about`, `about-us`, `colofon`, `privacy`, `disclaimer`, `algemene-voorwaarden` and variants such as `privacy-policy`, `support-contact`, `legal-information`), or `about`/`over`/`ons` as a whole token — the stage SHALL prefer `<slug>.recall.md` when present and fall back to `<slug>.md` otherwise. For all other collected pages it SHALL read `<slug>.md`. Any recall-only page (a `<slug>.recall.md` whose precision `<slug>.md` was dropped as thin) SHALL also be loaded.

The stage SHALL additionally load every `<slug>.visible.txt` into a separate raw visible-text surface map. These surfaces feed the postcode anchor (as `body`) but are excluded from the LLM-fallback surface.

If `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`, the stage SHALL emit `status: "upstream_failed"` without attempting extraction or any LLM call. All other input keys SHALL be carried through verbatim so downstream stages can join on company identity.

#### Scenario: Recall-mode markdown preferred

- **WHEN** both `contact.md` and `contact.recall.md` exist
- **THEN** the postcode anchor is applied against `contact.recall.md`; `contact.md` is ignored

#### Scenario: Precision markdown used when recall absent

- **WHEN** `contact.md` exists but `contact.recall.md` does not
- **THEN** the postcode anchor is applied against `contact.md`

#### Scenario: Upstream failure propagation

- **WHEN** `_meta.json.status` is `"upstream_failed"` or `"fetch_failed"`
- **THEN** no extraction is attempted and the output has `status: "upstream_failed"` with input keys preserved

#### Scenario: Extra input keys preserved

- **WHEN** `_meta.json` contains `{"name": ..., "website": ..., "source": "incubator-2026-01", ...}`
- **THEN** the output record retains `source` with the same value

### Requirement: Postcode Anchor

The stage SHALL detect Dutch postal codes using the regex `\d{4}[ \t\xa0]*[A-Z]{2}` with the letter pair uppercase in the source text. The gap between digits and letters MAY be any run of horizontal whitespace (spaces, tabs, NBSP) including none, but SHALL NOT span a line break. Lowercase letter pairs are not matched. Normalised output form: `"DDDD LL"` uppercase with single space. Each match anchors a candidate:

- Up to 80 characters of preceding context → `street` (taken backwards to the first `\n`, `|`, or `,` boundary; leading punctuation stripped).
- The matched postcode itself.
- Up to 40 characters of following context → `city` (taken forwards to the first `\n`, `,`, `|`, `(`, or `\t` boundary).
- `country` defaults to `"NL"` (the regex is Dutch-specific).

The anchor SHALL be applied to surfaces in order: `_meta.json.structured_text` (tagged `structured`), then `_meta.json.footer_text` (tagged `footer`), then every collected page's markdown content and every raw `<slug>.visible.txt` surface (both tagged `body`).

#### Scenario: Structured signal anchored first

- **WHEN** `structured_text` is `"Stadsplateau 34 3521 AZ Utrecht"` harvested from a JSON-LD `PostalAddress`
- **THEN** a `structured` candidate `{street: "Stadsplateau 34", postcode: "3521 AZ", city: "Utrecht", country: "NL"}` is produced

#### Scenario: Single clean footer hit

- **WHEN** `footer_text` is `"Europalaan 100, 3526 KS Utrecht | KVK 12345678"`
- **THEN** one `footer` candidate is produced: `{street: "Europalaan 100", postcode: "3526 KS", city: "Utrecht", country: "NL"}`

#### Scenario: Postcode on a non-address page anchored

- **WHEN** no postcode is in `structured_text` or `footer_text`, but `index.md` contains `"3526 KS Utrecht"`
- **THEN** a `body` candidate is produced from `index.md`

#### Scenario: Lowercase postcode not matched by regex

- **WHEN** the surface text contains `"3526 ks utrecht"`
- **THEN** no candidate is produced; the company falls to the LLM fallback path

#### Scenario: No-space postcode normalised

- **WHEN** the surface text contains `"3526KS Utrecht"`
- **THEN** the candidate's `postcode` is `"3526 KS"`

#### Scenario: Repeated whitespace tolerated

- **WHEN** a surface contains `"3526  KV  Utrecht"` (multiple spaces/NBSP between digits and letters)
- **THEN** a candidate with `postcode: "3526 KV"` and `city: "Utrecht"` is produced

#### Scenario: Postcode does not span a line break

- **WHEN** a surface contains a 4-digit token at the end of one line and a 2-uppercase token at the start of the next (e.g. `"2024\n\nNL"`)
- **THEN** no candidate is produced

#### Scenario: Address recovered from raw visible text

- **WHEN** the `contact` markdown carries no postcode but `contact.visible.txt` contains `"Princetonlaan 6\n3584 CB Utrecht"`
- **THEN** a `body` candidate `{street: "Princetonlaan 6", postcode: "3584 CB", city: "Utrecht"}` is produced

#### Scenario: Postcode in email rejected

- **WHEN** the surface text contains `support@1234ab.example`
- **THEN** no candidate is produced for `1234AB`

#### Scenario: Non-breaking space tolerated

- **WHEN** the surface text contains `"3526 KS Utrecht"` (non-breaking spaces)
- **THEN** a candidate with `postcode: "3526 KS"` and `city: "Utrecht"` is produced

### Requirement: Candidate Filtering and Ranking

After candidates are produced, the stage SHALL apply, in order:

1. **`Postbus` filter** — candidates whose `street` (case-insensitive, trailing punctuation tolerated) begins with `Postbus`, `P.O. Box`, or `Pb.` SHALL be discarded.
2. **Hint-based ranking** — within a 60-character window before and after each surviving candidate, capped at the nearest single newline, scan case-insensitively for:
   - **Boosts**: `bezoekadres`, `hoofdkantoor`, `vestiging`, `vestigingsadres`, `kantooradres`, `hq`, `headquarters`, `head office`, `main office`, `registered office`, `visiting address`, `office address`.
   - **Demotions**: `postadres`, `correspondentieadres`, `factuuradres`, `mailing address`, `postal address`, `po box`, `p.o. box`.
3. **Surface ranking** — at equal hint tier, `structured` candidates rank above `footer`, and `footer` above `body`.

A single surviving candidate is the `regex_single` path. Multiple survivors feed disambiguation, except: if exactly one candidate carries a boost and no others do, that candidate SHALL be emitted directly as `regex_single` without an LLM call.

#### Scenario: Postbus stripped

- **WHEN** footer text is `"Postbus 123, 3500 AA Utrecht | Bezoekadres: Europalaan 100, 3526 KS Utrecht"`
- **THEN** the `Postbus 123` candidate is discarded and the boosted `Europalaan 100` candidate is emitted as `regex_single`

#### Scenario: Boost wins without LLM

- **WHEN** two candidates remain after filtering and exactly one carries a `hoofdkantoor` label
- **THEN** the boosted candidate is emitted as `regex_single` with no LLM call

#### Scenario: Structured beats footer beats body

- **WHEN** one candidate is from `structured_text`, one from `footer_text`, and one from `about.md` body, with no hints either side
- **THEN** the structured candidate ranks first, footer second, body third; remaining ties proceed to disambiguation

#### Scenario: Postadres demoted

- **WHEN** a candidate is preceded by `Postadres:` within the hint window
- **THEN** it ranks below any non-demoted candidate

### Requirement: LLM Fallback Path

When zero candidates survive filtering, the stage SHALL attempt LLM extraction from prose. The call:

- Receives ≤2000 chars of concatenated page content drawn from the canonical address slugs (`contact`, `contact-us`, `over-ons`, `about`, `about-us`, `colofon`, `privacy`, `disclaimer`, `algemene-voorwaarden`) in that order, followed by any other address-intent slug variant present (e.g. `privacy-policy`, `support-contact`). `footer_text` and the raw `<slug>.visible.txt` surfaces are excluded — the regex already scanned the footer, and raw visible text is too noisy (nav, forms, cookie banners) to help prose extraction.
- Returns the address schema with explicit nulls for unknown fields.
- Has its emitted `postcode` re-validated against the postcode regex; a non-conforming value SHALL be dropped to null while other fields are retained.
- Sets `status: "llm_fallback"` on success, including the all-null case (the path was taken, the model said nothing was extractable).

The stage SHALL NOT call the LLM when no relevant page content was collected; in that case it emits `status: "empty"` directly.

#### Scenario: Prose-only address extracted

- **WHEN** no postcode matches anywhere but `contact.md` contains `"gevestigd in het centrum van Utrecht"` and the LLM emits `{street: null, postcode: null, city: "Utrecht", country: "NL"}`
- **THEN** those values are recorded with `status: "llm_fallback"`

#### Scenario: Invalid postcode dropped to null

- **WHEN** the LLM fallback emits `{postcode: "3526", city: "Utrecht", ...}` (incomplete postcode)
- **THEN** `postcode` is rewritten to null; `city` is retained; `status: "llm_fallback"`

#### Scenario: Fallback yields nothing

- **WHEN** the LLM fallback returns all-null fields
- **THEN** all address fields are null and `status: "llm_fallback"` (not `"empty"` — the path label is preserved)
