"""Address preparation helpers for geocoding stage."""

from __future__ import annotations
import re

def prepare(address: dict | None) -> dict:
    """Prepare address dictionary for PDOK query.
    
    Returns a dict with:
        - postcode_no_space: str or None
        - huisnummer: int or None
        - city: str or None
        - skip_reason: "non_nl", "no_anchor", or None
    """
    if not address:
        return {
            "postcode_no_space": None,
            "huisnummer": None,
            "city": None,
            "skip_reason": "no_anchor",
        }
    
    country = address.get("country")
    if country is not None and country != "NL":
        return {
            "postcode_no_space": None,
            "huisnummer": None,
            "city": None,
            "skip_reason": "non_nl",
        }
    
    postcode = address.get("postcode")
    city = address.get("city")
    
    if not postcode and not city:
        return {
            "postcode_no_space": None,
            "huisnummer": None,
            "city": None,
            "skip_reason": "no_anchor",
        }
    
    postcode_no_space = postcode.replace(" ", "") if postcode else None
    
    street = address.get("street")
    huisnummer = None
    if street:
        # First run of digits is the base house number; trailing letters and
        # additions (e.g. "8c1" -> 8) are excluded. PDOK indexes suffixed
        # addresses under this base number, so it resolves the rooftop.
        match = re.search(r"\d+", street)
        if match:
            huisnummer = int(match.group(0))
            
    return {
        "postcode_no_space": postcode_no_space,
        "huisnummer": huisnummer,
        "city": city,
        "skip_reason": None,
    }
