"""Minimal reader for the content-summarization dossier's YAML frontmatter.

Self-contained — no YAML dependency — because this stage only ever reads dossiers
written by content-summarization, whose frontmatter is a fixed set of quoted
scalar keys (``name``, ``website``, ``status``, ``source_language``, ``model``).
"""

from __future__ import annotations


def parse(text: str) -> tuple[dict[str, str | None], str]:
    """Split a dossier into (frontmatter dict, body).

    A document without a leading ``---`` block has an empty frontmatter and is
    returned whole as the body.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    fields: dict[str, str | None] = {}
    body_start = len(lines)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = i + 1
            break
        key, sep, raw = line.partition(":")
        if sep:
            fields[key.strip()] = _scalar(raw.strip())

    body = "\n".join(lines[body_start:]).lstrip("\n")
    return fields, body


def _scalar(s: str) -> str | None:
    """Unquote a frontmatter scalar; ``null`` (quoted or bare) becomes None."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return None if s == "null" else s
