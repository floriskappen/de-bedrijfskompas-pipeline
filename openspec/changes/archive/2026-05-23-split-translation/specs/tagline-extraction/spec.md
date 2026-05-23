## MODIFIED Requirements

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/tagline-extraction/<company-id>.json` containing `name`, `website`, `status`, `model`, and `tagline`. The `tagline` field SHALL be an object with an `en` string member when `status` is `ok`, and `{"en": null}` otherwise. `model` SHALL be null when no LLM call was made.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is processed successfully
- **THEN** `data/tagline-extraction/acme.json` exists with `status: "ok"`, a non-null `model`, and `tagline.en` carrying a non-empty string

#### Scenario: Null tagline on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `tagline` is `{"en": null}`

#### Scenario: Name-collision refusal

- **WHEN** `data/tagline-extraction/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

### Requirement: Tagline Content

The `en` tagline SHALL be a plain-language description a non-technical reader understands at a glance. It SHALL convey what the company actually does and who it is for, with the honest who-pays-for-what relationship coming through rather than the company's mission or self-description — but it SHALL NOT be forced into a fixed "[customer] pays [company]" template; the verb SHALL fit the company (a product company "makes"/"sells", a service company is "hired by"/"paid by"). It SHALL name the core activity rather than enumerate the full product list. It SHALL NOT repeat the company's own name, which is displayed alongside the tagline; it SHALL open with what the company does or a short descriptor (e.g. "A digital consultancy hired by…", "Sells…", "Makes…"). It SHALL use no jargon, no marketing adjectives (e.g. "innovative", "leading", "cutting-edge"), and add no facts absent from the dossier. It SHALL be one sentence; a second sentence is permitted only when the dossier is too thin or self-contradictory to convey the core in one, and that second sentence SHALL state the limitation (e.g. "However, no specific offerings are listed at the time of analysis").

#### Scenario: Honest revenue relationship comes through

- **WHEN** the dossier describes a B2B agency wrapped in mission language
- **THEN** the tagline conveys who pays the company and for what (e.g. "A digital consultancy hired by clients to design and build their software"), not the marketing mission

#### Scenario: Company name omitted

- **WHEN** a tagline is produced for a company whose name is a distinctive word
- **THEN** the `en` tagline does not contain the company's name, since it is shown next to the tagline

#### Scenario: Thin dossier gets a caveat sentence

- **WHEN** the dossier lists no concrete offerings or contradicts itself
- **THEN** the tagline states the company's apparent core and appends one caveat sentence noting the missing or conflicting information

#### Scenario: No marketing language

- **WHEN** the dossier is dense with promotional adjectives
- **THEN** the tagline contains none of them and states plainly what the company does

### Requirement: LLM Generation

The stage SHALL produce each tagline with a single LLM call via OpenRouter, returning a JSON object with an `en` string key. The prompt SHALL be loaded from a versioned file under `prompts/`, identified by name; prompts SHALL NOT be inlined in code. The default model SHALL be a DeepSeek model, overridable via the `TAGLINE_EXTRACTION_MODEL` environment variable. A response that cannot be parsed into an object with a non-empty `en` string SHALL be treated as an LLM error.

#### Scenario: Prompt loaded from versioned file

- **WHEN** the stage builds the LLM request
- **THEN** the instruction text is read from a named file under `prompts/`, not from a string literal in a `.py` module

#### Scenario: Model override honoured

- **WHEN** `TAGLINE_EXTRACTION_MODEL` is set
- **THEN** the stage calls that model instead of the DeepSeek default

#### Scenario: Malformed response is an error

- **WHEN** the model returns text that is not a JSON object with a non-empty `en` string
- **THEN** the company's record is written with `status: llm_error` and `tagline: {"en": null}`
