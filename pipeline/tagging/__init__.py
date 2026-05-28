"""Pipeline stage 4d: tagging.

Reads one company's de-marketed dossier from ``data/content-summarization/<id>.md``
and writes a single JSON record to ``data/tagging/<id>.json`` carrying a list of
``{family, prominence}`` capability tags drawn from a fixed 19-slug vocabulary.
Slugs only; not a translation input.
"""

from .core import process, run

__all__ = ["process", "run"]
