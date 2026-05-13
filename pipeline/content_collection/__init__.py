"""Pipeline stage 2: collect markdown content from each company website.

Reads upstream records from ``data/website-resolution/<company-id>.json``,
fetches a curated subset of pages, and writes one markdown file per page
plus a ``_meta.json`` sidecar at ``data/content-collection/<company-id>/``.

The job is **collection, not interpretation** — produce clean markdown
of pages likely to contain durable substance and capture a few cheap
meta-signals (page titles, footer text). Downstream stages do the LLM
work.
"""

from .core import process, run

__all__ = ["process", "run"]
