"""Pipeline stage 5: tagline-extraction.

Reads one company's de-marketed dossier from ``data/content-summarization/<id>.md``
and writes a single JSON record to ``data/tagline-extraction/<id>.json`` carrying an
English plain-language one-liner whose spine is "who pays this company and for
what". Generative, not analytic: it produces a sentence, it does not score. Dutch
is added downstream by the translation stage.
"""

from .core import process, run

__all__ = ["process", "run"]
