"""Pipeline stage 3b: content-summarization.

Reads one company's precision page markdown from ``data/content-collection/<id>/``
and writes a single faithful, de-marketed, English company dossier to
``data/content-summarization/<id>.md``. The dossier is the fan-out artifact that
every wave-4 dossier-derived analytic stage consumes.
"""

from .core import process, run

__all__ = ["process", "run"]
