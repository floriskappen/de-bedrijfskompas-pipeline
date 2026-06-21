"""Per-company address geocoder and batch runner."""

from __future__ import annotations
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.website_resolution import company_id
from . import address

def process(
    fact_record: dict,
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    client = None,
) -> dict:
    """Geocode a single company's fact-extraction record. Never raises except on name collision."""
    if client is None:
        from . import pdok as client

    # Prepare base skeleton carrying other keys verbatim
    out = {k: v for k, v in fact_record.items() if k not in ("status", "latlng", "match_quality", "source")}
    out["latlng"] = None
    out["match_quality"] = None
    out["source"] = None
    out["status"] = None

    # Gate on fact-extraction success status
    upstream_status = fact_record.get("status")
    if upstream_status not in ("regex_single", "regex_disambiguated", "llm_fallback"):
        out["status"] = "upstream_failed"
        if write:
            _write(out, out_dir=out_dir)
        return out

    # Prepare address and check skip reason
    prep = address.prepare(fact_record.get("address"))
    if prep["skip_reason"] is not None:
        out["status"] = "empty"
        if write:
            _write(out, out_dir=out_dir)
        return out

    if offline:
        out["status"] = "empty"
        if write:
            _write(out, out_dir=out_dir)
        return out

    postcode_no_space = prep["postcode_no_space"]
    huisnummer = prep["huisnummer"]

    status = None
    latlng = None
    match_quality = None
    source = None

    try:
        # Tier 1: exact
        if postcode_no_space and huisnummer is not None:
            res = client.exact(postcode_no_space, huisnummer)
            if res is not None:
                latlng = res
                match_quality = "exact"
                source = "pdok"
                status = "ok"

        # Tier 2: postcode_centroid
        if status is None and postcode_no_space:
            res = client.postcode_centroid(postcode_no_space)
            if res is not None:
                latlng = res
                match_quality = "postcode_centroid"
                source = "pdok"
                status = "ok"

        # No whole-city tier: a city-only address resolves to "empty" rather than
        # a kilometre-scale pin (see geocoding spec, Tiered PDOK Lookup).
        if status is None:
            status = "empty"

    except Exception:
        status = "lookup_error"
        latlng = None
        match_quality = None
        source = None

    out["latlng"] = latlng
    out["match_quality"] = match_quality
    out["source"] = source
    out["status"] = status

    # Invariant assertion
    if status == "ok":
        assert out["latlng"] is not None
        assert out["match_quality"] is not None
        assert out["source"] is not None
    else:
        assert out["latlng"] is None
        assert out["match_quality"] is None
        assert out["source"] is None

    if write:
        _write(out, out_dir=out_dir)

    return out

def run(
    records: Iterable[dict],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    content_dir: Path | None = None,
    client = None,
) -> Iterator[dict]:
    """Yield one geocoded record per company. Never raises on per-company errors."""
    for record in records:
        try:
            yield process(record, out_dir=out_dir, write=write, offline=offline, client=client)
        except Exception as exc:
            # Propagate name-collision RuntimeError
            if isinstance(exc, RuntimeError) and "collision" in str(exc):
                raise
            
            # Catch other unexpected errors
            out = {k: v for k, v in record.items() if k not in ("status", "latlng", "match_quality", "source")}
            out["latlng"] = None
            out["match_quality"] = None
            out["source"] = None
            out["status"] = "lookup_error"
            out["_error"] = str(exc)
            yield out

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
