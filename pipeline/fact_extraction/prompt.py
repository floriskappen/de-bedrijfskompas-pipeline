"""LLM prompt builders for fact-extraction."""

from __future__ import annotations

from .address import Candidate

ADDRESS_SCHEMA_DESC = (
    '{"street": string|null, "postcode": string|null, "city": string|null, "country": string|null}'
)

_DISAMBIG_SYSTEM = """You receive 2-4 Dutch address candidates from a company's website \
plus surrounding context. Return the index of the headquarters address.

Rules:
- Prefer "bezoekadres" (visiting address) over "postadres" (mail address)
- Prefer "hoofdkantoor" over "vestiging"
- A Postbus is never a HQ
- If unsure, return the address that appears first or most prominently

Return JSON: {"hq_index": <int>, "confidence": "high"|"medium"|"low"}"""


def build_disambiguation_messages(candidates: list[Candidate]) -> list[dict]:
    """Return messages asking the model to pick the HQ from a candidate list."""
    items = []
    for i, c in enumerate(candidates):
        items.append(
            f"{i}: street={c.street!r}, postcode={c.postcode!r}, "
            f"city={c.city!r}, context={c.context_snippet!r}"
        )
    candidate_text = "\n".join(items)

    user = f"Candidates:\n{candidate_text}"
    return [{"role": "system", "content": _DISAMBIG_SYSTEM}, {"role": "user", "content": user}]


def build_fallback_messages(surface_text: str) -> list[dict]:
    """Return messages asking the model to extract an address from prose."""
    system = (
        "You are a data extraction assistant. "
        "Extract the company's headquarters visiting address from the text below. "
        f"Respond with JSON only matching this schema: {ADDRESS_SCHEMA_DESC}. "
        "Use null for any field you cannot determine with confidence. "
        "Do not invent or guess values."
    )
    user = f"Text:\n{surface_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
