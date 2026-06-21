## MODIFIED Requirements

### Requirement: Postcode Anchor

The stage SHALL detect Dutch postal codes using the regex `\d{4}[ \t\xa0]*[A-Z]{2}` with the letter pair uppercase in the source text. The gap between digits and letters MAY be any run of horizontal whitespace (spaces, tabs, NBSP) including none, but SHALL NOT span a line break. Lowercase letter pairs are not matched. Normalised output form: `"DDDD LL"` uppercase with single space. Each match anchors a candidate:

- Up to 80 characters of preceding context → `street` (taken backwards to the first `\n`, `|`, or `,` boundary; leading punctuation stripped).
- The matched postcode itself.
- Up to 40 characters of following context → `city`, normalised conservatively (see below).
- `country` defaults to `"NL"` (the regex is Dutch-specific).

City normalisation SHALL apply, in order, to the following context:

1. **HTML-unescape** the context first, so entities such as `&nbsp;` and `&amp;` become real characters before any boundary logic.
2. **Strip leading separators** — whitespace, NBSP, `,`, `\n`, `|` — so a separator immediately after the postcode is treated as "city follows", not an empty city. This recovers `Postcode, City` and `Postcode\nCity` layouts.
3. **Cut at the first end boundary** in the set `\n`, `,`, `|`, `(`, `)`, `•`, `·`, `;`, `:`, `–`, `—`, tab.
4. **Cut at a boilerplate label** matched case-insensitively as a word: `KVK`, `BTW`, `VAT`, `tel`, `telefoon`, `phone`, `fax`, `e-mail`/`email`, `©`, `copyright`. Label-aware boundaries are preferred over an unconditional first-digit rule because valid Dutch place names can contain digits.
5. **Strip a trailing country suffix**, spaced or fused, matched case-insensitively at the end: `the netherlands`, `netherlands`, `nederland`. Bare `NL` and `Holland` SHALL NOT be stripped.

The resulting value is the candidate's `city`, or `null` if empty after normalisation.

When the normalised following context yields no city, the stage SHALL attempt a single conservative prior-line recovery from the preceding context: split it into non-empty lines, treat the last as the street and the second-to-last as the candidate city, and accept that city **only** when the street line contains a digit and the prior line matches `^[A-Za-zÀ-ÿ'’.\- ]{2,40}$` with no digit. This recovers a strongly structured `City\nStreet+houseno\nPostcode` layout. On any doubt the city stays `null` — a wrong city is worse than `null` when a postcode is already present.

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

#### Scenario: City after a leading comma recovered

- **WHEN** a surface contains `"3584 CB, Utrecht"`
- **THEN** the candidate's `city` is `"Utrecht"`, not `null`

#### Scenario: City on the next line recovered

- **WHEN** a surface contains `"3584 CB\nUtrecht"`
- **THEN** the candidate's `city` is `"Utrecht"`

#### Scenario: Bullet and boilerplate trimmed

- **WHEN** a surface contains `"3584 CB Utrecht • KVK: 97376019 • BTW: NL868025"`
- **THEN** the candidate's `city` is `"Utrecht"`

#### Scenario: Closing parenthesis ends the city

- **WHEN** a surface contains `"3584 CB Utrecht) is gespecialiseerd in AI-consultancy"`
- **THEN** the candidate's `city` is `"Utrecht"`

#### Scenario: Boilerplate label without a bullet trimmed

- **WHEN** a surface contains `"3584 CB Utrecht KVK: 97376019"`
- **THEN** the candidate's `city` is `"Utrecht"`

#### Scenario: Fused country suffix stripped

- **WHEN** a surface contains `"3953 MJ MaarsbergenThe Netherlands"`
- **THEN** the candidate's `city` is `"Maarsbergen"`

#### Scenario: Spaced country suffix stripped

- **WHEN** a surface contains `"3811 NJ Amersfoort The Netherlands"`
- **THEN** the candidate's `city` is `"Amersfoort"`

#### Scenario: HTML entity decoded

- **WHEN** a surface contains `"3811 NJ Amersfoort&nbsp;"`
- **THEN** the candidate's `city` is `"Amersfoort"`

#### Scenario: City recovered from the line before the street

- **WHEN** a surface contains `"Amersfoort\nKoningstraat 1\n1234 AB"` and the following context carries no city
- **THEN** the candidate's `city` is `"Amersfoort"`

#### Scenario: Prior-line recovery declines on a noisy line

- **WHEN** a surface contains `"Bel ons op 030-1234567\nKoningstraat 1\n1234 AB"` and the following context carries no city
- **THEN** the candidate's `city` is `null` (the prior line contains digits)
