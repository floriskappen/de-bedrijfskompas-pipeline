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
        cleaned_street = re.sub(r"(?<=\d)[a-zA-Z]+", "", street)
        match = re.search(r"\b(\d+)\b", cleaned_street)
        if match:
            huisnummer = int(match.group(1))
            
    return {
        "postcode_no_space": postcode_no_space,
        "huisnummer": huisnummer,
        "city": city,
        "skip_reason": None,
    }
