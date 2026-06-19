"""Dutch address extraction via postcode-anchored regex with hint-based ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Postcode regex
# ---------------------------------------------------------------------------

# Four digits, runs of horizontal whitespace (space/tab/NBSP), two letters.
# Boundary guards:
#   - not preceded by alphanumeric or @ (rejects @1234ab in email addresses)
#   - not followed by alphanumeric or . (rejects 1234ab.example domain parts)
# Require uppercase letter pair — real Dutch postcodes on company sites are always
# uppercase (e.g. "3526 KS"), so this eliminates year+word false positives like
# "launched in 2015 to incredibly" matching as postcode "2015 TO".
# Whitespace between digits and letters is `*` over *horizontal* whitespace only:
# raw-HTML visible-text surfaces sometimes render the gap as several spaces or
# NBSPs ("3526  KV  Utrecht"), but the digit/letter pair never spans a line break
# in practice, so newlines are deliberately excluded to avoid matching a stray
# 4-digit line end followed by a 2-letter line start (e.g. a year above "NL").
_POSTCODE_RE = re.compile(
    r"(?<![A-Za-z0-9@])(\d{4})[ \t\xa0]*([A-Z]{2})(?![A-Za-z0-9.])",
    re.UNICODE,
)

# Validate a standalone postcode string (post-LLM check).
_POSTCODE_VALID_RE = re.compile(r"^(\d{4})\s*([A-Za-z]{2})$")  # used for post-LLM validation only

CONTEXT_BEFORE = 80  # chars of preceding text to capture (street surface)
CONTEXT_AFTER = 40   # chars of following text to capture (city surface)
HINT_WINDOW = 60     # chars on each side to scan for lexical hints


# ---------------------------------------------------------------------------
# Hint vocabularies
# ---------------------------------------------------------------------------

BOOST_HINTS = frozenset(
    [
        # Dutch
        "bezoekadres",
        "hoofdkantoor",
        "vestiging",
        "vestigingsadres",
        "kantooradres",
        # English (for NL-based companies with English-only sites)
        "hq",
        "headquarters",
        "head office",
        "main office",
        "registered office",
        "visiting address",
        "office address",
    ]
)

DEMOTE_HINTS = frozenset(
    [
        # Dutch
        "postadres",
        "correspondentieadres",
        "factuuradres",
        # English
        "mailing address",
        "postal address",
        "po box",
        "p.o. box",
    ]
)

_POSTBUS_RE = re.compile(
    r"^(postbus|p\.o\.\s*box|pb\.?)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    street: str | None
    postcode: str  # always normalised "DDDD LL" uppercase
    city: str | None
    country: str = "NL"
    surface: str = "footer"  # "structured" | "footer" | "body"
    context_snippet: str = ""  # surrounding text for disambiguation
    boost: bool = False
    demote: bool = False

    def as_address(self) -> dict:
        return {
            "street": self.street or None,
            "postcode": self.postcode,
            "city": self.city or None,
            "country": self.country,
        }


# ---------------------------------------------------------------------------
# Postcode extraction
# ---------------------------------------------------------------------------


def _normalise_postcode(digits: str, letters: str) -> str:
    return f"{digits} {letters.upper()}"


def _strip_city(text: str) -> str:
    """Trim city context: take up to the first hard delimiter."""
    for ch in ("\n", ",", "|", "(", "\t"):
        idx = text.find(ch)
        if idx != -1:
            text = text[:idx]
    return text.strip(" \t\r\xa0")


def _strip_street(text: str) -> str:
    """Trim street context: strip trailing separator, then take from last hard boundary.

    Trailing ``\\n`` is stripped first so that block-structured footers
    (``Smallepad 32\\n3526 KS Utrecht``) yield the street on the preceding line,
    not an empty string.
    """
    text = text.rstrip(" \t\r\n\xa0,|")
    # Split on the last newline or pipe (common single-line footer field separator)
    for sep in ("\n", "|"):
        idx = text.rfind(sep)
        if idx != -1:
            text = text[idx + 1:]
            break
    return text.strip(" \t\r\xa0")


def _extract_candidates(text: str, surface: str) -> list[Candidate]:
    """Find all postcode matches in *text* and build Candidate objects."""
    candidates: list[Candidate] = []
    for m in _POSTCODE_RE.finditer(text):
        digits, letters = m.group(1), m.group(2)
        postcode = _normalise_postcode(digits, letters)

        start, end = m.start(), m.end()
        before = text[max(0, start - CONTEXT_BEFORE) : start]
        after = text[end : end + CONTEXT_AFTER]

        street_raw = _strip_street(before)
        city_raw = _strip_city(after)

        snippet_start = max(0, start - CONTEXT_BEFORE)
        snippet_end = min(len(text), end + CONTEXT_AFTER)
        snippet = text[snippet_start:snippet_end].strip()[:200]

        candidate = Candidate(
            street=street_raw or None,
            postcode=postcode,
            city=city_raw or None,
            surface=surface,
            context_snippet=snippet,
        )
        _apply_hints(text, m.start(), candidate)
        candidates.append(candidate)

    return candidates


def _hint_window(text: str, match_start: int) -> str:
    """Return the hint-scanning window around a match position.

    Scans up to HINT_WINDOW chars in each direction, stopping at the nearest
    newline (single or double) so that hints from adjacent address lines don't
    bleed across candidates.
    """
    lo = max(0, match_start - HINT_WINDOW)
    hi = min(len(text), match_start + HINT_WINDOW)
    window = text[lo:hi]
    # Clamp at the nearest newline on each side (single newline is a field boundary)
    left_cut = window.rfind("\n", 0, match_start - lo)
    if left_cut != -1:
        window = window[left_cut + 1:]
    right_cut = window.find("\n")
    if right_cut != -1:
        window = window[:right_cut]
    return window.lower()


def _apply_hints(text: str, match_start: int, candidate: Candidate) -> None:
    window = _hint_window(text, match_start)
    for hint in BOOST_HINTS:
        if hint in window:
            candidate.boost = True
            break
    for hint in DEMOTE_HINTS:
        if hint in window:
            candidate.demote = True
            break


# ---------------------------------------------------------------------------
# Filtering and ranking
# ---------------------------------------------------------------------------


def _is_postbus(candidate: Candidate) -> bool:
    street = (candidate.street or "").strip()
    return bool(_POSTBUS_RE.match(street))


def _rank_key(candidate: Candidate) -> tuple:
    boost_score = 0 if candidate.boost else (2 if candidate.demote else 1)
    surface_order = {"structured": 0, "footer": 1, "body": 2}
    surface_score = surface_order.get(candidate.surface, 3)
    return (boost_score, surface_score)


def extract_candidates(
    footer_text: str | None,
    pages: dict[str, str],
    structured_text: str | None = None,
    visible_pages: dict[str, str] | None = None,
) -> list[Candidate]:
    """Return ranked, filtered candidates from all surfaces.

    Surface priority: structured_text first, then footer_text, then page bodies
    (markdown plus any raw visible-text surfaces). Postbus candidates are
    removed. Result is sorted best-first.
    """
    raw: list[Candidate] = []
    if structured_text:
        raw.extend(_extract_candidates(structured_text, surface="structured"))
    if footer_text:
        raw.extend(_extract_candidates(footer_text, surface="footer"))
    for text in pages.values():
        raw.extend(_extract_candidates(text, surface="body"))
    # Raw visible text rescues addresses trafilatura dropped from the markdown;
    # it ranks as ``body`` (lowest) so cleaner structured/footer hits win first.
    for text in (visible_pages or {}).values():
        raw.extend(_extract_candidates(text, surface="body"))

    filtered = [c for c in raw if not _is_postbus(c)]
    filtered.sort(key=_rank_key)
    return filtered


def validate_postcode(value: str | None) -> str | None:
    """Return the normalised postcode if it matches Dutch format, else None."""
    if value is None:
        return None
    m = _POSTCODE_VALID_RE.match(value.strip())
    if not m:
        return None
    return f"{m.group(1)} {m.group(2).upper()}"
