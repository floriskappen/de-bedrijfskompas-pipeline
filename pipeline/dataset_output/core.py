"""Terminal projection stage: join per-stage outputs into one frontend-facing record per company.

A pure projection — it reads the per-company files written by upstream stages, filters out
everything non-frontend-facing, joins English text with its Dutch translation, and writes one
record per company. It makes no LLM call and no network request.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

FACT_DIR = Path("data/fact-extraction")
GEOCODING_DIR = Path("data/geocoding")
SCORING_DIR = Path("data/global-scoring")
TAGLINE_DIR = Path("data/tagline-extraction")
TRANSLATION_DIR = Path("data/translation")
DEFAULT_OUT_DIR = Path("data/dataset-output")

# Load-bearing vocabularies (see specs/dataset-output/spec.md).
AXES = ("substance", "ecology", "power", "embeddedness", "posture")
LOCALES = ("en", "nl")
ADDRESS_FIELDS = ("street", "postcode", "city", "country")
FAILURE_STATUSES = frozenset({"upstream_failed", "empty", "llm_error"})


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def process(
    cid: str,
    *,
    out_dir: Path,
    write: bool,
    fact_dir: Path = FACT_DIR,
    scoring_dir: Path = SCORING_DIR,
    tagline_dir: Path = TAGLINE_DIR,
    translation_dir: Path = TRANSLATION_DIR,
    geocoding_dir: Path = GEOCODING_DIR,
) -> dict:
    """Project one company's per-stage outputs into a single record. Raises only on id collision."""
    fact = _load(fact_dir / f"{cid}.json")
    scoring = _load(scoring_dir / f"{cid}.json")
    tagline = _load(tagline_dir / f"{cid}.json")
    translation = _load(translation_dir / f"{cid}.json")
    geocoding = _load(geocoding_dir / f"{cid}.json")

    record = _assemble(cid, fact, scoring, tagline, translation, geocoding)
    if write:
        _write(record, out_dir=out_dir)
    return record


def run(
    company_ids: Iterable[str],
    *,
    out_dir: Path,
    write: bool,
    fact_dir: Path = FACT_DIR,
    scoring_dir: Path = SCORING_DIR,
    tagline_dir: Path = TAGLINE_DIR,
    translation_dir: Path = TRANSLATION_DIR,
    geocoding_dir: Path = GEOCODING_DIR,
) -> Iterator[dict]:
    """Yield one record per company. A per-company error becomes an ``upstream_failed`` record;
    only a company-id collision aborts the batch."""
    for cid in company_ids:
        try:
            yield process(
                cid,
                out_dir=out_dir,
                write=write,
                fact_dir=fact_dir,
                scoring_dir=scoring_dir,
                tagline_dir=tagline_dir,
                translation_dir=translation_dir,
                geocoding_dir=geocoding_dir,
            )
        except RuntimeError:
            raise  # company-id collision is the sole hard error
        except Exception as exc:
            failed = _empty_record(cid, status="upstream_failed")
            failed["_error"] = str(exc)
            yield failed


# ---------------------------------------------------------------------------
# Projection / record assembly
# ---------------------------------------------------------------------------


def _assemble(
    cid: str,
    fact: dict | None,
    scoring: dict | None,
    tagline: dict | None,
    translation: dict | None,
    geocoding: dict | None,
) -> dict:
    name = (fact or {}).get("name")
    website = (fact or {}).get("website")

    address = _project_address(fact)
    latlng, match_quality = _project_geocoding(geocoding)
    scores, en_scores = _project_scores(scoring)
    en_tagline = _project_tagline(tagline)
    en_tree = _en_tree(en_scores, en_tagline, has_scoring=scores is not None, has_tagline=_usable(tagline))
    nl_tree = _nl_tree(translation, mirror_scores=en_scores is not None)

    status = _status(fact, address=address, latlng=latlng, scores=scores, en_tree=en_tree, nl_tree=nl_tree)

    return {
        "company_id": cid,
        "name": name,
        "website": website,
        "status": status,
        "address": address,
        "latlng": latlng,
        "match_quality": match_quality,
        "scores": scores,
        "en": en_tree,
        "nl": nl_tree,
    }


def _project_address(fact: dict | None) -> dict | None:
    if not fact:
        return None
    addr = fact.get("address")
    if not isinstance(addr, dict) or not any(addr.get(f) for f in ADDRESS_FIELDS):
        return None
    return {f: addr.get(f) for f in ADDRESS_FIELDS}


def _project_scores(scoring: dict | None) -> tuple[dict | None, dict | None]:
    """Return (root scores block, en reasons block), or (None, None) when scoring is unusable."""
    if not _usable(scoring):
        return None, None
    src = scoring.get("scores") or {}
    scores: dict = {}
    en_scores: dict = {}
    for axis in AXES:
        ax = src.get(axis) or {}
        scores[axis] = {"score": ax.get("score"), "evidence": ax.get("evidence")}
        en_scores[axis] = {"reason": (ax.get("reason") or {}).get("en")}
    return scores, en_scores


def _project_tagline(tagline: dict | None) -> str | None:
    if not _usable(tagline):
        return None
    return (tagline.get("tagline") or {}).get("en")


def _en_tree(en_scores: dict | None, en_tagline: str | None, *, has_scoring: bool, has_tagline: bool) -> dict | None:
    if not has_scoring and not has_tagline:
        return None
    return {"tagline": en_tagline, "scores": en_scores}


def _nl_tree(translation: dict | None, *, mirror_scores: bool) -> dict | None:
    """Build the Dutch tree, resolving values by the translation stage's flat dotted keys."""
    if not _usable(translation):
        return None
    tr = translation.get("translations") or {}
    nl_scores = None
    if mirror_scores:
        nl_scores = {
            axis: {"reason": (tr.get(f"scores.{axis}.reason") or {}).get("nl")}
            for axis in AXES
        }
    return {"tagline": (tr.get("tagline") or {}).get("nl"), "scores": nl_scores}


def _project_geocoding(geocoding: dict | None) -> tuple[dict | None, str | None]:
    if not geocoding or geocoding.get("status") != "ok":
        return None, None
    latlng = geocoding.get("latlng")
    match_quality = geocoding.get("match_quality")
    if not latlng or not match_quality:
        return None, None
    return latlng, match_quality


def _status(fact: dict | None, *, address, latlng, scores, en_tree, nl_tree) -> str:
    if fact is None:
        return "upstream_failed"
    has_payload = (
        address is not None or
        latlng is not None or
        scores is not None or
        en_tree is not None or
        nl_tree is not None
    )
    return "ok" if has_payload else "empty"


def _usable(record: dict | None) -> bool:
    """A source is usable when it exists and its status is not a failure status."""
    return record is not None and record.get("status") not in FAILURE_STATUSES


def _empty_record(cid: str, *, status: str) -> dict:
    return {
        "company_id": cid,
        "name": None,
        "website": None,
        "status": status,
        "address": None,
        "latlng": None,
        "match_quality": None,
        "scores": None,
        "en": None,
        "nl": None,
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict | None:
    """Read and parse a source file, or return ``None`` if missing or unreadable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write(record: dict, *, out_dir: Path) -> None:
    cid = record.get("company_id")
    if not isinstance(cid, str) or not cid:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cid}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("name") != record.get("name"):
            raise RuntimeError(
                f"company-id collision at {out_path}: "
                f"existing name={existing.get('name')!r}, new name={record.get('name')!r}"
            )

    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
