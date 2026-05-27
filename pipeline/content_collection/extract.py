"""trafilatura wrapper plus footer text extractor."""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urljoin

import trafilatura
from lxml import etree, html as lxml_html

MIN_MARKDOWN_LENGTH: Final = 100

_INLINE_WS_RE = re.compile(r"[ \t\xa0\r\f\v]+")

# Block-level HTML elements: their boundaries become newlines in extracted text
# so downstream regex can rely on `\n` as a field separator. <br> is treated as
# a block break too (it's a visual line break in HTML).
_BLOCK_TAGS: Final = frozenset(
    [
        "address", "article", "aside", "blockquote", "br", "div", "dd", "dl",
        "dt", "fieldset", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    ]
)


def extract_markdown(html: str) -> str | None:
    """Return trafilatura-extracted markdown in precision mode.

    Precision-favoured extraction yields cleaner, denser prose at the cost of
    dropping structured side-blocks (office address cards, contact widgets,
    etc.) that trafilatura classifies as boilerplate. This is the right
    trade-off for downstream summarisation/embedding — fewer tokens, more
    signal — but it loses the address content that fact-extraction needs;
    that gap is covered by ``extract_markdown_recall`` for address-bearing
    page slugs.
    """

    return trafilatura.extract(
        html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_images=False,
        include_links=False,
        include_formatting=True,
        deduplicate=True,
        favor_precision=True,
    )


def extract_markdown_recall(html: str) -> str | None:
    """Return trafilatura-extracted markdown in recall mode.

    Recall-favoured extraction retains the structured side-blocks (address
    cards, "Our offices" sections, contact widgets) that the precision mode
    drops. Used by content-collection to produce a parallel ``.recall.md``
    file for address-bearing slugs so that fact-extraction has a surface
    where the postcode anchor can land.
    """

    return trafilatura.extract(
        html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_images=False,
        include_links=False,
        include_formatting=True,
        deduplicate=True,
        favor_recall=True,
    )


def extract_page_metadata(html: str) -> dict:
    """Return ``{title, description, sitename}`` for a page (any may be ``None``)."""

    meta = trafilatura.extract_metadata(html)
    if meta is None:
        return {"title": None, "description": None, "sitename": None}
    data = meta.as_dict() if hasattr(meta, "as_dict") else {}
    return {
        "title": data.get("title"),
        "description": data.get("description"),
        "sitename": data.get("sitename"),
    }


_SIZE_RE = re.compile(r"(\d+)\s*[xX]\s*(\d+)")


def extract_favicon_url(homepage_url: str, html: str) -> str | None:
    """Extract the best favicon URL from homepage HTML."""
    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return urljoin(homepage_url, "/favicon.ico")

    candidates = []
    for link in doc.iter("link"):
        rel = link.get("rel", "").lower().strip()
        rel_tokens = set(rel.split())
        is_favicon = (
            rel in ("icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed")
            or "icon" in rel_tokens
            or "apple-touch-icon" in rel_tokens
            or "apple-touch-icon-precomposed" in rel_tokens
        )
        if not is_favicon:
            continue

        href = link.get("href")
        if not href:
            continue

        sizes_attr = link.get("sizes", "").lower().strip()
        parsed_sizes = []

        if sizes_attr == "any":
            parsed_sizes.append(512)
        elif sizes_attr:
            for match in _SIZE_RE.finditer(sizes_attr):
                w = int(match.group(1))
                h = int(match.group(2))
                parsed_sizes.append(max(w, h))

        if not parsed_sizes:
            parsed_sizes.append(16)

        best_size = max(parsed_sizes)
        rel_priority = 0 if "shortcut" not in rel else 1
        abs_url = urljoin(homepage_url, href)
        candidates.append((abs_url, best_size, rel_priority))

    if not candidates:
        return urljoin(homepage_url, "/favicon.ico")

    larger_or_equal = [c for c in candidates if c[1] >= 512]
    smaller = [c for c in candidates if c[1] < 512]

    # Sort groups:
    # larger_or_equal sorted by size ascending, then rel_priority ascending
    larger_or_equal.sort(key=lambda c: (c[1], c[2]))
    # smaller sorted by size descending, then rel_priority ascending
    smaller.sort(key=lambda c: (-c[1], c[2]))

    ranked = larger_or_equal + smaller
    return ranked[0][0]


def extract_footer_text(html: str) -> str | None:
    """Concatenate text from all ``<footer>`` elements, normalize whitespace."""

    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return None

    # Some CMSes (e.g. Squarespace) embed <style>/<script> inside <footer>.
    # text_content() would include their bodies verbatim, so strip them
    # tree-wide first. with_tail=False preserves text that follows the
    # stripped element.
    etree.strip_elements(doc, "script", "style", "noscript", with_tail=False)

    parts: list[str] = []
    for footer in doc.iter("footer"):
        text = _text_with_block_breaks(footer)
        if text:
            parts.append(text)

    if not parts:
        return None
    return _normalise_block_text("\n".join(parts)) or None


def _text_with_block_breaks(element) -> str:
    """Extract text preserving block-level element boundaries as newlines.

    ``element.text_content()`` concatenates all descendant text with no
    separator, which fuses adjacent inline siblings into single tokens
    (``<a>LinkedIn</a><a>Instagram</a>`` becomes ``LinkedInInstagram``) and
    erases the visual structure that downstream regex relies on for field
    extraction. Walking the tree manually and emitting ``\\n`` around block
    elements preserves field boundaries that the HTML author intended.
    """
    parts: list[str] = []

    def _walk(elem) -> None:
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            is_block = child.tag in _BLOCK_TAGS
            # Block elements get hard line breaks; inline elements get a space
            # so adjacent siblings (<a>LinkedIn</a><a>Instagram</a>) don't fuse
            # into single tokens. The post-walk normaliser collapses runs of
            # horizontal whitespace so the extra spaces are harmless inside prose.
            parts.append("\n" if is_block else " ")
            _walk(child)
            parts.append("\n" if is_block else " ")
            if child.tail:
                parts.append(child.tail)

    _walk(element)
    return "".join(parts)


def _normalise_block_text(text: str) -> str:
    """Collapse intra-line whitespace and drop empty lines, but keep newlines."""
    lines = [_INLINE_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)
