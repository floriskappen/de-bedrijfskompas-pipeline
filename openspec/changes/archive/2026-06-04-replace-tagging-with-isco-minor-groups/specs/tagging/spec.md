## ADDED Requirements

### Requirement: ISCO Minor Group Vocabulary

The stage SHALL draw every emitted `isco_code` value from the fixed ISCO-08 minor-group vocabulary below, and SHALL NOT emit any code outside it. The vocabulary SHALL be embedded in the versioned prompt under `prompts/tagging.md`, grouped by sub-major group, with the 3-digit code as the canonical value.

- `111` Legislators and senior officials
- `112` Managing directors and chief executives
- `121` Business services and administration managers
- `122` Sales, marketing and development managers
- `131` Production managers in agriculture, forestry and fisheries
- `132` Manufacturing, mining, construction, and distribution managers
- `133` Information and communications technology service managers
- `134` Professional services managers
- `141` Hotel and restaurant managers
- `142` Retail and wholesale trade managers
- `143` Other services managers
- `211` Physical and earth science professionals
- `212` Mathematicians, actuaries and statisticians
- `213` Life science professionals
- `214` Engineering professionals (excluding electrotechnology)
- `215` Electrotechnology engineers
- `216` Architects, planners, surveyors and designers
- `221` Medical doctors
- `222` Nursing and midwifery professionals
- `223` Traditional and complementary medicine professionals
- `224` Paramedical practitioners
- `225` Veterinarians
- `226` Other health professionals
- `231` University and higher education teachers
- `232` Vocational education teachers
- `233` Secondary education teachers
- `234` Primary school and early childhood teachers
- `235` Other teaching professionals
- `241` Finance professionals
- `242` Administration professionals
- `243` Sales, marketing and public relations professionals
- `251` Software and applications developers and analysts
- `252` Database and network professionals
- `261` Legal professionals
- `262` Librarians, archivists and curators
- `263` Social and religious professionals
- `264` Authors, journalists and linguists
- `265` Creative and performing artists
- `311` Physical and engineering science technicians
- `312` Mining, manufacturing and construction supervisors
- `313` Process control technicians
- `314` Life science technicians and related associate professionals
- `315` Ship and aircraft controllers and technicians
- `321` Medical and pharmaceutical technicians
- `322` Nursing and midwifery associate professionals
- `323` Traditional and complementary medicine associate professionals
- `324` Veterinary technicians and assistants
- `325` Other health associate professionals
- `331` Financial and mathematical associate professionals
- `332` Sales and purchasing agents and brokers
- `333` Business services agents
- `334` Administrative and specialized secretaries
- `335` Regulatory government associate professionals
- `341` Legal, social and religious associate professionals
- `342` Sports and fitness workers
- `343` Artistic, cultural and culinary associate professionals
- `351` Information and communications technology operations and user support technicians
- `352` Telecommunications and broadcasting technicians
- `411` General office clerks
- `412` Secretaries (general)
- `413` Keyboard operators
- `421` Tellers, money collectors and related clerks
- `422` Client information workers
- `431` Numerical clerks
- `432` Material-recording and transport clerks
- `441` Other clerical support workers
- `511` Travel attendants, conductors and guides
- `512` Cooks
- `513` Waiters and bartenders
- `514` Hairdressers, beauticians and related workers
- `515` Building and housekeeping supervisors
- `516` Other personal services workers
- `521` Street and market salespersons
- `522` Shop salespersons
- `523` Cashiers and ticket clerks
- `524` Other sales workers
- `531` Child care workers and teachers' aides
- `532` Personal care workers in health services
- `541` Protective services workers
- `611` Market gardeners and crop growers
- `612` Animal producers
- `613` Mixed crop and animal producers
- `621` Forestry and related workers
- `622` Fishery workers, hunters and trappers
- `631` Subsistence crop farmers
- `632` Subsistence livestock farmers
- `633` Subsistence mixed crop and livestock farmers
- `634` Subsistence fishers, hunters, trappers and gatherers
- `711` Building frame and related trades workers
- `712` Building finishers and related trades workers
- `713` Painters, building structure cleaners and related trades workers
- `721` Sheet and structural metal workers, moulders and welders, and related workers
- `722` Blacksmiths, toolmakers and related trades workers
- `723` Machinery mechanics and repairers
- `731` Handicraft workers
- `732` Printing trades workers
- `741` Electrical equipment installers and repairers
- `742` Electronics and telecommunications installers and repairers
- `751` Food processing and related trades workers
- `752` Wood treaters, cabinet-makers and related trades workers
- `753` Garment and related trades workers
- `754` Other craft and related workers
- `811` Mining and mineral processing plant operators
- `812` Metal processing and finishing plant operators
- `813` Chemical and photographic products plant and machine operators
- `814` Rubber, plastic and paper products machine operators
- `815` Textile, fur and leather products machine operators
- `816` Food and related products machine operators
- `817` Wood processing and papermaking plant operators
- `818` Other stationary plant and machine operators
- `821` Assemblers
- `831` Locomotive engine drivers and related workers
- `832` Car, van and motorcycle drivers
- `833` Heavy truck and bus drivers
- `834` Mobile plant operators
- `835` Ships' deck crews and related workers
- `911` Domestic, hotel and office cleaners and helpers
- `912` Vehicle, window, laundry and other hand cleaning workers
- `921` Agricultural, forestry and fishery labourers
- `931` Mining and construction labourers
- `932` Manufacturing labourers
- `933` Transport and storage labourers
- `941` Food preparation assistants
- `951` Street and related service workers
- `952` Street vendors (excluding food)
- `961` Refuse workers
- `962` Other elementary workers
- `011` Commissioned armed forces officers
- `021` Non-commissioned armed forces officers
- `031` Armed forces occupations, other ranks

#### Scenario: Emitted ISCO code is in the fixed set

- **WHEN** the stage produces a capability tag for any company
- **THEN** its `isco_code` value is one of the 130 listed 3-digit strings

#### Scenario: Out-of-vocabulary ISCO code is treated as LLM error

- **WHEN** the LLM returns a tag whose `isco_code` is not in the fixed set
- **THEN** the stage writes `status: llm_error` and `capability_tags: null` for that company, rather than emitting the unknown code

### Requirement: ISCO Capability Tag Shape

Each emitted capability tag SHALL be an object with exactly three members: `isco_code` (one of the fixed 3-digit strings), `prominence` (exactly one of `core`, `supporting`, `incidental`), and `confidence` (exactly one of `high`, `low`). `core` denotes an occupation group the company is fundamentally built on; `supporting` denotes an occupation group that is real and ongoing but not central; `incidental` denotes an occupation group mentioned in passing. `high` confidence denotes a dossier-evidenced inference; `low` confidence denotes a structural guess from thin or indirect evidence. At most one entry per `isco_code` SHALL appear in a company's `capability_tags` list.

#### Scenario: Tag carries ISCO code, prominence, and confidence

- **WHEN** the stage emits a capability tag
- **THEN** the tag object has exactly `isco_code`, `prominence`, and `confidence`

#### Scenario: One entry per ISCO code

- **WHEN** the LLM returns two entries with the same `isco_code`
- **THEN** the stage writes `status: llm_error` and `capability_tags: null` rather than emitting duplicates

#### Scenario: Invalid confidence is an LLM error

- **WHEN** the LLM returns a tag with a `confidence` outside `high` / `low`
- **THEN** the stage writes `status: llm_error` and `capability_tags: null`

### Requirement: Occupational Inference Discipline

The stage SHALL tag occupational groups the company itself appears to staff or rely on internally, not the customer sector the company serves. Ordinary internal administration, management, sales, clerical, finance, legal, and HR functions SHALL be omitted unless those functions are part of the company's actual product, service, or operating model.

#### Scenario: Serving a sector is not staffing that sector

- **WHEN** a software company builds tools for hospitals but the dossier does not show internal clinical staff providing care
- **THEN** the stage MAY emit ICT codes such as `251` or `252`, and MUST NOT emit health codes such as `221`, `222`, `321`, `322`, or `532`

#### Scenario: Ordinary business functions are omitted

- **WHEN** a company appears to have ordinary internal sales, management, finance, legal, HR, or clerical functions only because it is a functioning company
- **THEN** the stage MUST NOT emit the corresponding ISCO codes unless the dossier shows those functions are part of what the company sells, delivers, or fundamentally operates

## MODIFIED Requirements

### Requirement: Output Record File

For each company the stage SHALL write one JSON file at `data/tagging/<company-id>.json` containing `name`, `website`, `status`, `model`, and `capability_tags`. The `capability_tags` field SHALL be a JSON array of ISCO capability-tag objects (possibly empty) when `status` is `ok`, and `null` otherwise. `model` SHALL be null when no LLM call was made.

Downstream stages join this file to other stage outputs by `<company-id>` (the filename). A company-id collision with a differing `name` SHALL be a hard error: the stage SHALL NOT overwrite an existing file whose stored `name` differs from the current record's name; it SHALL raise.

#### Scenario: Successful record shape

- **WHEN** company `acme` is processed successfully
- **THEN** `data/tagging/acme.json` exists with `status: "ok"`, a non-null `model`, and `capability_tags` as an array of ISCO tag objects (possibly empty)

#### Scenario: Null capability_tags on non-ok status

- **WHEN** a company's record has any status other than `ok`
- **THEN** its `capability_tags` is `null` (not an empty array)

#### Scenario: Empty array allowed on ok

- **WHEN** the LLM returns no applicable occupational capability groups for an `ok` dossier
- **THEN** `capability_tags` is `[]` and `status` remains `ok`

#### Scenario: Name-collision refusal

- **WHEN** `data/tagging/acme.json` exists with `name: "Acme B.V."` and the current record has the same id but `name: "Acme Holding"`
- **THEN** the stage raises rather than overwriting

## REMOVED Requirements

### Requirement: Capability Family Vocabulary

**Reason**: The custom 19-family slug vocabulary is replaced by the standard ISCO-08 minor-group vocabulary.

**Migration**: Emit `isco_code` on each `capability_tags` entry and validate against the 130-code ISCO-08 minor-group set.

### Requirement: Capability Tag Shape

**Reason**: The tag object shape now carries ISCO code identity and confidence in addition to prominence.

**Migration**: Replace `{ family, prominence }` entries with `{ isco_code, prominence, confidence }` entries.
