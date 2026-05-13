"""trafilatura wrapper plus footer text extractor."""

from __future__ import annotations

import re
from typing import Final

import trafilatura
from lxml import etree, html as lxml_html

MIN_MARKDOWN_LENGTH: Final = 100

_WHITESPACE_RE = re.compile(r"\s+")


def extract_markdown(html: str) -> str | None:
    """Return trafilatura-extracted markdown, or ``None`` if nothing usable."""

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
        text = footer.text_content()
        if text:
            parts.append(text)

    if not parts:
        return None
    combined = "\n".join(parts)
    normalized = _WHITESPACE_RE.sub(" ", combined).strip()
    return normalized or None
