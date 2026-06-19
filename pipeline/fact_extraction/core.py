"""Per-company fact extractor and batch runner for fact-extraction."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.website_resolution import company_id

from . import llm as llm_module
from .address import Candidate, extract_candidates, validate_postcode
from .prompt import build_disambiguation_messages, build_fallback_messages

FALLBACK_SURFACE_LIMIT = 2000  # chars fed to the prose-fallback LLM
DISAMBIG_MAX_CANDIDATES = 5

# Canonical address-bearing slugs, in priority order for the LLM-fallback
# surface. content-collection now also emits address pages under slug
# *variants* (``contact-2``, ``support-contact``, ``privacy-policy``,
# ``legal-information`` ...); ``is_address_intent_slug`` recognises those so
# recall preference and the fallback surface cover them too.
ADDRESS_SLUGS = (
    "contact",
    "contact-us",
    "over-ons",
    "about",
    "about-us",
    "colofon",
    "privacy",
    "disclaimer",
    "algemene-voorwaarden",
)

# Mirror of ``content_collection.crawl.is_address_intent_slug``. Stages are
# self-contained (no shared cross-stage helpers), so this copy must be kept in
# sync by hand if either side is widened.
_ADDRESS_INTENT_STEMS = (
    "contact",
    "colofon",
    "disclaimer",
    "privacy",
    "legal",
    "voorwaarden",
    "condities",
    "terms",
    "imprint",
    "impressum",
)
_ADDRESS_INTENT_TOKENS = frozenset({"about", "over", "ons"})


def is_address_intent_slug(slug: str) -> bool:
    """Return whether *slug* names a contact/legal/privacy/identity address page."""

    s = slug.lower()
    if any(stem in s for stem in _ADDRESS_INTENT_STEMS):
        return True
    return bool(set(s.split("-")) & _ADDRESS_INTENT_TOKENS)


def process(
    meta: dict,
    pages: dict[str, str],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    visible_pages: dict[str, str] | None = None,
) -> dict:
    """Extract facts for a single company. Never raises."""

    upstream_status = meta.get("status", "")
    if upstream_status in ("upstream_failed", "fetch_failed"):
        result = _skeleton(meta, status="upstream_failed")
        if write:
            _write(result, out_dir=out_dir)
        return result

    footer_text: str | None = meta.get("footer_text")
    structured_text: str | None = meta.get("structured_text")
    candidates = extract_candidates(footer_text, pages, structured_text, visible_pages)

    if len(candidates) == 1:
        result = _from_candidate(meta, candidates[0], status="regex_single")

    elif len(candidates) > 1:
        # Sole-boost shortcut: if exactly one candidate has a boost and no others do
        boosted = [c for c in candidates if c.boost]
        non_boosted = [c for c in candidates if not c.boost]
        if len(boosted) == 1 and not non_boosted:
            result = _from_candidate(meta, boosted[0], status="regex_single")
        elif len(boosted) == 1 and all(not c.boost for c in non_boosted):
            result = _from_candidate(meta, boosted[0], status="regex_single")
        elif offline:
            # In offline mode use the top-ranked candidate if a sole-boost exists
            result = _from_candidate(meta, candidates[0], status="regex_single") if boosted else _empty(meta)
        else:
            result = _disambiguate(meta, candidates[:DISAMBIG_MAX_CANDIDATES])

    else:
        # Zero candidates
        if offline:
            result = _empty(meta)
        else:
            surface = _build_fallback_surface(footer_text, pages)
            if not surface.strip():
                result = _empty(meta)
            else:
                result = _llm_fallback(meta, footer_text, pages)

    if write:
        _write(result, out_dir=out_dir)
    return result


DEFAULT_CONTENT_DIR = Path("data/content-collection")


def run(
    records: Iterable[dict],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    content_dir: Path | None = None,
) -> Iterator[dict]:
    """Yield one fact record per company. Never raises on per-company errors."""
    src = content_dir if content_dir is not None else DEFAULT_CONTENT_DIR
    for record in records:
        try:
            meta, pages, visible_pages = _load_company(record, out_dir=src)
            yield process(
                meta,
                pages,
                out_dir=out_dir,
                write=write,
                offline=offline,
                visible_pages=visible_pages,
            )
        except Exception as exc:
            failed = _skeleton(record, status="upstream_failed")
            failed["_error"] = str(exc)
            yield failed


# ---------------------------------------------------------------------------
# Resolution paths
# ---------------------------------------------------------------------------


def _disambiguate(meta: dict, candidates: list[Candidate]) -> dict:
    messages = build_disambiguation_messages(candidates)
    try:
        response = llm_module.call(messages)
        idx = response.get("hq_index")
        if idx is None or not isinstance(idx, int) or idx >= len(candidates):
            return _empty(meta)
        chosen = candidates[idx]
        return _from_candidate(meta, chosen, status="regex_disambiguated")
    except llm_module.LLMError:
        return _skeleton(meta, status="llm_error")


def _llm_fallback(
    meta: dict,
    footer_text: str | None,
    pages: dict[str, str],
) -> dict:
    surface = _build_fallback_surface(footer_text, pages)
    messages = build_fallback_messages(surface)
    try:
        response = llm_module.call(messages)
        address = _coerce_address(response)
        result = _skeleton(meta, status="llm_fallback")
        result["address"] = address
        result["source"] = meta.get("_llm_model") or llm_module.DEFAULT_MODEL
        return result
    except llm_module.LLMError:
        return _skeleton(meta, status="llm_error")


def _build_fallback_surface(footer_text: str | None, pages: dict[str, str]) -> str:
    # footer_text is intentionally excluded: the regex already scanned it fully.
    # If it contained no postcode, it's unlikely to help the LLM and may add noise.
    # Canonical address slugs lead (stable priority order); any other
    # address-intent variant present (privacy-policy, support-contact, ...)
    # follows so newly-discovered address pages still feed the fallback.
    parts: list[str] = []
    used: set[str] = set()
    for slug in ADDRESS_SLUGS:
        if slug in pages:
            parts.append(pages[slug])
            used.add(slug)
    for slug in sorted(pages):
        if slug in used or not is_address_intent_slug(slug):
            continue
        parts.append(pages[slug])
        used.add(slug)
    combined = "\n\n".join(parts)
    return combined[:FALLBACK_SURFACE_LIMIT]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _from_candidate(meta: dict, candidate: Candidate, *, status: str) -> dict:
    result = _skeleton(meta, status=status)
    result["address"] = {
        "street": candidate.street,
        "postcode": validate_postcode(candidate.postcode),
        "city": candidate.city,
        "country": candidate.country,
    }
    result["source"] = candidate.context_snippet[:200]
    return result


def _empty(meta: dict) -> dict:
    return _skeleton(meta, status="empty")


def _skeleton(meta: dict, *, status: str) -> dict:
    out = {k: v for k, v in meta.items() if k not in ("status",)}
    out["status"] = status
    out["address"] = {"street": None, "postcode": None, "city": None, "country": None}
    out["source"] = None
    return out


def _coerce_address(raw: dict) -> dict:
    address = {
        "street": raw.get("street") or None,
        "postcode": validate_postcode(raw.get("postcode")),
        "city": raw.get("city") or None,
        "country": raw.get("country") or None,
    }
    return address


def _load_company(record: dict, *, out_dir: Path) -> tuple[dict, dict[str, str], dict[str, str]]:
    """Load _meta.json plus page markdown and raw visible-text for a company."""
    name = record.get("name", "")
    cid = company_id(name)
    company_dir = out_dir / cid

    meta_path = company_dir / "_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = dict(record)
        meta["status"] = "upstream_failed"

    pages: dict[str, str] = {}

    # Prefer the recall-mode markdown when content-collection emitted one for
    # address-bearing slugs: precision mode strips structured address blocks as
    # boilerplate, so the .md file commonly lacks the postcode the regex anchor
    # needs. All other collected pages are scanned from their precision file.
    for path in sorted(company_dir.glob("*.md")):
        if path.name.endswith(".recall.md"):
            continue
        slug = path.stem
        if is_address_intent_slug(slug):
            recall_path = company_dir / f"{slug}.recall.md"
            if recall_path.exists():
                pages[slug] = recall_path.read_text(encoding="utf-8")
                continue
        pages[slug] = path.read_text(encoding="utf-8")

    # Recall-only address pages (precision .md dropped as thin).
    for recall_path in sorted(company_dir.glob("*.recall.md")):
        slug = recall_path.name[: -len(".recall.md")]
        if slug not in pages:
            pages[slug] = recall_path.read_text(encoding="utf-8")

    # Raw visible-text surfaces for address-intent pages — fed to the postcode
    # anchor only (kept out of the LLM fallback surface, which prefers the
    # cleaner markdown), so addresses trafilatura dropped can still be matched.
    visible_pages: dict[str, str] = {}
    for visible_path in sorted(company_dir.glob("*.visible.txt")):
        slug = visible_path.name[: -len(".visible.txt")]
        visible_pages[slug] = visible_path.read_text(encoding="utf-8")

    return meta, pages, visible_pages


def _write(result: dict, *, out_dir: Path) -> None:
    name = result.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return

    cid = company_id(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cid}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("name") != name:
            raise RuntimeError(
                f"company-id collision at {out_path}: "
                f"existing name={existing.get('name')!r}, new name={name!r}"
            )

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
