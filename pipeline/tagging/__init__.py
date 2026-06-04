"""Pipeline stage 4d: tagging.

Reads one company's de-marketed dossier from ``data/content-summarization/<id>.md``
and writes a single JSON record to ``data/tagging/<id>.json`` carrying a list of
``{isco_code, prominence, confidence}`` capability tags drawn from the fixed
ISCO-08 minor-group vocabulary. Codes only; not a translation input.
"""

from .core import process, run

__all__ = ["process", "run"]
