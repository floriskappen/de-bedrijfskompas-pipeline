"""Pipeline stage 5: global-scoring.

Reads one company's de-marketed dossier from ``data/content-summarization/<id>.md``
and writes a single JSON record to ``data/global-scoring/<id>.json`` carrying a score
for each of the five structural axes from ``docs/GLOBAL_SCORING_FRAMEWORK.md``
(substance, ecology, power, embeddedness, posture). Each axis carries a 0-100 score
(or null when there is no signal), an evidence level, and a bilingual (en + nl) reason.
Analytic, not generative: it scores a profile, it produces no composite number.
"""

from .core import process, run

__all__ = ["process", "run"]
