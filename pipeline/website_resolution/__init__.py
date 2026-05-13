"""Pipeline stage 1: resolve a company's canonical website URL.

This package owns:

- The DDGS-backed website discovery (`search.py`).
- The per-record resolver and batch runner (`core.py`).
- The `<company-id>` derivation rule used by every downstream stage.

Company-ID slugification rule
-----------------------------
`company_id(name)` lowercases `name`, strips trailing entity suffixes
(``B.V.``, ``N.V.``, ``Holding``, ``Holdings`` — case-insensitive, with
surrounding whitespace), then slugifies the remainder via
``python-slugify``. The result is hyphen-separated ASCII.

This rule is **load-bearing**: every other stage uses these IDs to address
files under ``data/<stage>/<company-id>.json``. Changing the rule renames
every existing artifact and is therefore a breaking change for all stored
data — treat it as a versioned migration, not a refactor.
"""

from .core import company_id, resolve, run

__all__ = ["company_id", "resolve", "run"]
