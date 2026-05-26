"""PDOK Locatieserver client for geocoding stage."""

from __future__ import annotations
import urllib.request
import urllib.parse
import urllib.error
import json
import re

class PDOKError(Exception):
    """Raised when a PDOK query fails due to network, non-2xx, or parse errors."""
    pass

def _query_pdok(fq_filters: list[str], timeout: float = 5.0) -> dict | None:
    """Execute a PDOK locatieserver search query and parse the first result centroid."""
    params = [("fq", f) for f in fq_filters] + [("rows", "1")]
    query_str = urllib.parse.urlencode(params)
    url = f"https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?{query_str}"
    
    headers = {"User-Agent": "de-bedrijfskompas-pipeline/0.1.0"}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            if status_code != 200:
                raise PDOKError(f"HTTP error: {status_code}")
            raw_data = response.read()
            data = json.loads(raw_data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise PDOKError(f"HTTP Error {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise PDOKError(f"URL Error: {e.reason}") from e
    except TimeoutError as e:
        raise PDOKError(f"Timeout: {e}") from e
    except Exception as e:
        raise PDOKError(f"Query error: {e}") from e

    try:
        resp = data.get("response", {})
        num_found = resp.get("numFound", 0)
        if num_found == 0:
            return None
        
        docs = resp.get("docs", [])
        if not docs:
            raise PDOKError("Response docs is empty but numFound > 0")
        
        doc = docs[0]
        centroide_ll = doc.get("centroide_ll")
        if not centroide_ll:
            raise PDOKError("centroide_ll missing or empty in doc")
        
        # Parse POINT(lng lat)
        match = re.match(r"^POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)$", centroide_ll, re.IGNORECASE)
        if not match:
            raise PDOKError(f"Unparseable centroide_ll format: {centroide_ll}")
        
        lng = float(match.group(1))
        lat = float(match.group(2))
        return {"lat": lat, "lng": lng}
    except PDOKError:
        raise
    except Exception as e:
        raise PDOKError(f"Unparseable response content: {e}") from e

def exact(postcode: str, huisnummer: int, timeout: float = 5.0) -> dict | None:
    """Query PDOK exact address rooftop tier."""
    fq_filters = ["type:adres", f"postcode:{postcode}", f"huisnummer:{huisnummer}"]
    return _query_pdok(fq_filters, timeout=timeout)

def postcode_centroid(postcode: str, timeout: float = 5.0) -> dict | None:
    """Query PDOK postcode centroid tier."""
    fq_filters = ["type:postcode", f"postcode:{postcode}"]
    return _query_pdok(fq_filters, timeout=timeout)

def city_centroid(city: str, timeout: float = 5.0) -> dict | None:
    """Query PDOK city centroid tier."""
    fq_filters = ["type:woonplaats", f"woonplaatsnaam:{city}"]
    return _query_pdok(fq_filters, timeout=timeout)
