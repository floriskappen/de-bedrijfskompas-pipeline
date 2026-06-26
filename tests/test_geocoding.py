"""Tests for the geocoding stage."""

from __future__ import annotations
import json
import urllib.request
import urllib.error
import urllib.parse
import pytest
from pathlib import Path

from pipeline.geocoding import pdok, address, core
from pipeline.geocoding.__main__ import main as cli_main

# Mock Response Class for urllib
class MockResponse:
    def __init__(self, data: bytes, status: int = 200, reason: str = "OK"):
        self.data = data
        self.status = status
        self.reason = reason
        
    def read(self) -> bytes:
        return self.data
        
    def getcode(self) -> int:
        return self.status
        
    def __enter__(self) -> MockResponse:
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

# Mock PDOK Client for core tests
class MockPDOKClient:
    def __init__(self, exact_res=None, postcode_res=None, street_res=None, should_raise=False):
        self.exact_res = exact_res
        self.postcode_res = postcode_res
        self.street_res = street_res
        self.should_raise = should_raise
        self.calls = []

    def exact(self, postcode, huisnummer):
        self.calls.append(("exact", postcode, huisnummer))
        if self.should_raise:
            raise pdok.PDOKError("Mock error")
        return self.exact_res

    def street(self, straatnaam, huisnummer, woonplaatsnaam):
        self.calls.append(("street", straatnaam, huisnummer, woonplaatsnaam))
        if self.should_raise:
            raise pdok.PDOKError("Mock error")
        return self.street_res

    def postcode_centroid(self, postcode):
        self.calls.append(("postcode_centroid", postcode))
        if self.should_raise:
            raise pdok.PDOKError("Mock error")
        return self.postcode_res

# ---------------------------------------------------------------------------
# PDOK Client Tests
# ---------------------------------------------------------------------------

def test_centroide_ll_parsed_lng_lat_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that POINT(lng lat) has lng and lat correctly swapped to lat, lng."""
    def mock_urlopen(req: urllib.request.Request, timeout: float | None = None) -> MockResponse:
        payload = {
            "response": {
                "numFound": 1,
                "docs": [
                    {"centroide_ll": "POINT(5.17259687 52.08263581)"}
                ]
            }
        }
        return MockResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    # Query exact
    res = pdok.exact("3584DW", 771)
    assert res is not None
    assert res["lat"] == 52.08263581
    assert res["lng"] == 5.17259687

def test_pdok_error_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that transport failure / non-2xx status raises PDOKError."""
    def mock_urlopen_http_error(req: urllib.request.Request, timeout: float | None = None) -> MockResponse:
        raise urllib.error.HTTPError("https://api.pdok.nl", 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_http_error)
    
    with pytest.raises(pdok.PDOKError):
        pdok.exact("3584DW", 771)

def test_street_query_builds_strict_fq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the street tier builds strict fq filters (type/straatnaam/huisnummer/woonplaatsnaam), no free-text q."""
    captured_url = {}

    def mock_urlopen(req: urllib.request.Request, timeout: float | None = None) -> MockResponse:
        captured_url["url"] = req.full_url
        payload = {"response": {"numFound": 1, "docs": [{"centroide_ll": "POINT(5.1 52.0)"}]}}
        return MockResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = pdok.street("Europalaan", 100, "Utrecht")
    assert res == {"lat": 52.0, "lng": 5.1}

    parsed = urllib.parse.urlparse(captured_url["url"])
    params = urllib.parse.parse_qs(parsed.query)
    assert "q" not in params  # no free-text q param
    assert params["fq"] == ["type:adres", 'straatnaam:"Europalaan"', "huisnummer:100", 'woonplaatsnaam:"Utrecht"']

# ---------------------------------------------------------------------------
# Address Preparation Tests
# ---------------------------------------------------------------------------

def test_postcode_space_stripped() -> None:
    """Verify postcode spaces are stripped."""
    addr = {"postcode": "3584 DW", "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["postcode_no_space"] == "3584DW"
    assert prep["skip_reason"] is None

def test_house_number_parsed() -> None:
    """Verify house number is parsed from street name."""
    addr = {"street": "Cambridgelaan 771", "postcode": "3584DW", "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["huisnummer"] == 771
    assert prep["skip_reason"] is None

def test_suffix_letter_ignored() -> None:
    """Verify suffix letter is ignored."""
    addr = {"street": "Europalaan 100a", "postcode": "3526KS", "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["huisnummer"] == 100
    assert prep["skip_reason"] is None

def test_letter_and_addition_suffix_reduced_to_base() -> None:
    """Verify 'Turbinestraat 8c1' yields base house number 8, not 81."""
    addr = {"street": "Turbinestraat 8c1", "postcode": "3903LW", "city": "Veenendaal", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["huisnummer"] == 8

def test_hyphenated_range_takes_first_number() -> None:
    """Verify 'Smallepad 5-7' yields the first house number 5."""
    addr = {"street": "Smallepad 5-7", "postcode": "3526KS", "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["huisnummer"] == 5

def test_no_digit_street_has_no_house_number() -> None:
    """Verify a street with no digits (e.g. '<br>') yields no house number."""
    addr = {"street": "<br>", "postcode": "3526KS", "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["huisnummer"] is None
    assert prep["straatnaam"] is None
    assert prep["skip_reason"] is None

def test_street_name_parsed() -> None:
    """Verify the street name is parsed as the text before the house-number token."""
    addr = {"street": "Europalaan 100", "postcode": None, "city": "Utrecht", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["straatnaam"] == "Europalaan"
    assert prep["huisnummer"] == 100
    assert prep["skip_reason"] is None

def test_garbled_street_yields_street_name() -> None:
    """Verify a street with trailing postcode/PoBox cruft still yields the street name."""
    addr = {"street": "Parnassusweg 793, 1082 LZ, P.O. Box 7895", "postcode": "1008 AB", "city": "Amsterdam", "country": "NL"}
    prep = address.prepare(addr)
    assert prep["straatnaam"] == "Parnassusweg"
    assert prep["huisnummer"] == 793
    assert prep["skip_reason"] is None

def test_non_nl_skip_reason() -> None:
    """Verify non-NL addresses are skipped with 'non_nl' skip_reason."""
    addr = {"street": "Rue de la Loi 16", "postcode": "1000", "city": "Brussels", "country": "BE"}
    prep = address.prepare(addr)
    assert prep["skip_reason"] == "non_nl"

def test_no_anchor_skip_reason() -> None:
    """Verify missing postcode and city causes 'no_anchor' skip_reason."""
    addr = {"street": "Unknown Street", "postcode": None, "city": None, "country": "NL"}
    prep = address.prepare(addr)
    assert prep["skip_reason"] == "no_anchor"

# ---------------------------------------------------------------------------
# Core geocoding logic tests (gating, tiered lookup, and errors)
# ---------------------------------------------------------------------------

def test_upstream_success_proceeds(tmp_path: Path) -> None:
    """WHEN the fact-extraction record has a success status, THEN the stage proceeds to lookup."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert len(client.calls) == 1

def test_upstream_non_success_cascades(tmp_path: Path) -> None:
    """WHEN the fact-extraction record has a non-success status, THEN status=upstream_failed, no HTTP."""
    rec = {
        "name": "Acme B.V.",
        "status": "upstream_failed",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "upstream_failed"
    assert res["latlng"] is None
    assert len(client.calls) == 0

def test_extra_input_keys_preserved(tmp_path: Path) -> None:
    """WHEN the fact-extraction record has extra keys, THEN they are preserved verbatim."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "source": "hackernews-2026-01",
        "custom_metadata": {"id": 123},
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["source"] == "pdok"  # Standard schema key overwritten by pdok
    assert res["custom_metadata"] == {"id": 123}

def test_exact_tier_hits(tmp_path: Path) -> None:
    """WHEN the exact tier returns a hit, THEN exact is used and postcode/city are not called."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.1, "lng": 5.1})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert res["match_quality"] == "exact"
    assert res["latlng"] == {"lat": 52.1, "lng": 5.1}
    assert client.calls == [("exact", "3526KS", 100)]

def test_exact_falls_through_to_street(tmp_path: Path) -> None:
    """WHEN exact is skipped (no postcode) but street+city are present, THEN the street tier hits and postcode_centroid is not attempted."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": None, "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(street_res={"lat": 52.0642, "lng": 5.1085})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert res["match_quality"] == "street"
    assert res["latlng"] == {"lat": 52.0642, "lng": 5.1085}
    assert client.calls == [("street", "Europalaan", 100, "Utrecht")]

def test_street_tier_hits_on_garbled_postcode(tmp_path: Path) -> None:
    """WHEN exact misses on a PoBox postcode but street+city resolve, THEN street hits and postcode_centroid is not attempted."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Parnassusweg 793", "postcode": "1008 AB", "city": "Amsterdam", "country": "NL"}
    }
    client = MockPDOKClient(exact_res=None, street_res={"lat": 52.3375, "lng": 4.8694})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert res["match_quality"] == "street"
    assert client.calls == [("exact", "1008AB", 793), ("street", "Parnassusweg", 793, "Amsterdam")]

def test_street_falls_through_to_postcode(tmp_path: Path) -> None:
    """WHEN exact and street both miss but postcode_centroid hits, THEN postcode_centroid is used."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res=None, street_res=None, postcode_res={"lat": 52.2, "lng": 5.2})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert res["match_quality"] == "postcode_centroid"
    assert res["latlng"] == {"lat": 52.2, "lng": 5.2}
    assert client.calls == [("exact", "3526KS", 100), ("street", "Europalaan", 100, "Utrecht"), ("postcode_centroid", "3526KS")]

def test_street_tier_skipped_when_city_missing(tmp_path: Path) -> None:
    """WHEN street is present but city is null, THEN the street tier is not queried (city needed to disambiguate)."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": None, "country": "NL"}
    }
    client = MockPDOKClient(exact_res=None, postcode_res={"lat": 52.2, "lng": 5.2})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["match_quality"] == "postcode_centroid"
    assert not any(c[0] == "street" for c in client.calls)

def test_all_tiers_empty(tmp_path: Path) -> None:
    """WHEN all three tiers return 0 docs, THEN status=empty, latlng/match_quality/source all null."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res=None, street_res=None, postcode_res=None)
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "empty"
    assert res["latlng"] is None
    assert res["match_quality"] is None
    assert res["source"] is None
    # No whole-city tier: resolution stops after postcode_centroid.
    assert client.calls == [("exact", "3526KS", 100), ("street", "Europalaan", 100, "Utrecht"), ("postcode_centroid", "3526KS")]

def test_successful_street_hit(tmp_path: Path) -> None:
    """Verify a street-tier hit produces the full output schema: latlng set, match_quality=street, source=pdok, status=ok."""
    rec = {
        "name": "Amulet",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": None, "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(street_res={"lat": 52.06424, "lng": 5.10854})
    core.process(rec, out_dir=tmp_path, write=True, client=client)

    out_file = tmp_path / "amulet.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["match_quality"] == "street"
    assert data["source"] == "pdok"
    assert data["latlng"] == {"lat": 52.06424, "lng": 5.10854}

def test_city_only_address_makes_no_request(tmp_path: Path) -> None:
    """WHEN only a city is available (no postcode), THEN no HTTP call and status=empty."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": None, "postcode": None, "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "empty"
    assert res["latlng"] is None
    assert res["match_quality"] is None
    assert len(client.calls) == 0

def test_tier_skipped_when_input_unavailable(tmp_path: Path) -> None:
    """WHEN postcode is available but no house number, THEN exact tier is skipped."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan NoNumber", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(postcode_res={"lat": 52.2, "lng": 5.2})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "ok"
    assert res["match_quality"] == "postcode_centroid"
    assert client.calls == [("postcode_centroid", "3526KS")]

def test_non_nl_emits_empty_without_http(tmp_path: Path) -> None:
    """WHEN address is non-NL, THEN status=empty, no HTTP call."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Rue de la Loi 16", "postcode": "1000", "city": "Brussels", "country": "BE"}
    }
    client = MockPDOKClient(exact_res={"lat": 50.0, "lng": 4.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "empty"
    assert res["latlng"] is None
    assert len(client.calls) == 0

def test_no_anchor_emits_empty_without_http(tmp_path: Path) -> None:
    """WHEN postcode and city are both null, THEN status=empty, no HTTP call."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": None, "city": None, "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "empty"
    assert res["latlng"] is None
    assert len(client.calls) == 0

def test_lookup_error_recorded(tmp_path: Path) -> None:
    """WHEN client throws an error, THEN status=lookup_error, latlng=None."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(should_raise=True)
    res = core.process(rec, out_dir=tmp_path, write=False, client=client)
    assert res["status"] == "lookup_error"
    assert res["latlng"] is None
    assert res["match_quality"] is None
    assert res["source"] is None

def test_one_failure_does_not_abort_batch(tmp_path: Path) -> None:
    """WHEN one record fails with HTTP error, THEN others still succeed."""
    records = [
        {
            "name": "Company One",
            "status": "regex_single",
            "address": {"street": "Street 1", "postcode": "1111 AA", "city": "City", "country": "NL"}
        },
        {
            "name": "Company Two Fail",
            "status": "regex_single",
            "address": {"street": "Street 2", "postcode": "2222 BB", "city": "City", "country": "NL"}
        },
        {
            "name": "Company Three",
            "status": "regex_single",
            "address": {"street": "Street 3", "postcode": "3333 CC", "city": "City", "country": "NL"}
        }
    ]
    
    class MixedClient:
        def exact(self, postcode, huisnummer):
            if postcode == "2222BB":
                raise pdok.PDOKError("Simulated timeout")
            return {"lat": 52.0, "lng": 5.0}
        def postcode_centroid(self, postcode):
            return None

    results = list(core.run(records, out_dir=tmp_path, write=False, client=MixedClient()))
    assert len(results) == 3
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "lookup_error"
    assert results[2]["status"] == "ok"

# ---------------------------------------------------------------------------
# Output Writer and Invariant Tests
# ---------------------------------------------------------------------------

def test_successful_write_shape(tmp_path: Path) -> None:
    """Verify that a successful resolution writes the exact schema layout to disk."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(exact_res={"lat": 52.0826, "lng": 5.1726})
    core.process(rec, out_dir=tmp_path, write=True, client=client)
    
    out_file = tmp_path / "acme.json"
    assert out_file.exists()
    
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["name"] == "Acme B.V."
    assert data["latlng"] == {"lat": 52.0826, "lng": 5.1726}
    assert data["match_quality"] == "exact"
    assert data["source"] == "pdok"
    assert data["status"] == "ok"

def test_all_null_together_on_failure(tmp_path: Path) -> None:
    """Verify that non-ok status has latlng, match_quality, and source all null."""
    rec = {
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    client = MockPDOKClient(should_raise=True)
    core.process(rec, out_dir=tmp_path, write=True, client=client)
    
    out_file = tmp_path / "acme.json"
    assert out_file.exists()
    
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["status"] == "lookup_error"
    assert data["latlng"] is None
    assert data["match_quality"] is None
    assert data["source"] is None

def test_name_collision_refusal(tmp_path: Path) -> None:
    """Verify that if target file exists with a different name, it raises rather than overwrites."""
    # Pre-seed file with name "Acme Holding B.V."
    (tmp_path / "acme.json").write_text(
        json.dumps({"name": "Acme Holding B.V.", "status": "ok"}),
        encoding="utf-8"
    )
    
    rec = {
        "name": "Acme B.V.",  # Slugifies to "acme" as well
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }
    
    client = MockPDOKClient(exact_res={"lat": 52.0, "lng": 5.0})
    
    with pytest.raises(RuntimeError, match="collision"):
        core.process(rec, out_dir=tmp_path, write=True, client=client)

# ---------------------------------------------------------------------------
# CLI & Parity & Cache Tests
# ---------------------------------------------------------------------------

def test_cli_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that the CLI runs and writes expected outputs."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }))

    # Mock pdok exact method
    monkeypatch.setattr(pdok, "exact", lambda pc, hn: {"lat": 52.0, "lng": 5.0})

    out_dir = tmp_path / "geocoding"
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir)])

    assert (out_dir / "acme.json").exists()
    written = json.loads((out_dir / "acme.json").read_text(encoding="utf-8"))
    assert written["status"] == "ok"
    assert written["latlng"] == {"lat": 52.0, "lng": 5.0}

def test_dry_run_yields_without_writing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Verify that dry-run mode prints records to stdout and writes nothing to disk."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }))

    monkeypatch.setattr(pdok, "exact", lambda pc, hn: {"lat": 52.0, "lng": 5.0})

    out_dir = tmp_path / "geocoding"
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir), "--dry-run"])

    assert not out_dir.exists() or not list(out_dir.iterdir())
    
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["name"] == "Acme B.V."
    assert data["latlng"] == {"lat": 52.0, "lng": 5.0}

def test_offline_mode_short_circuits_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that offline mode skips HTTP calls and marks records as status=empty."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }))

    called = False
    def mock_exact(pc, hn):
        nonlocal called
        called = True
        return {"lat": 52.0, "lng": 5.0}
    monkeypatch.setattr(pdok, "exact", mock_exact)

    out_dir = tmp_path / "geocoding"
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir), "--offline"])

    assert (out_dir / "acme.json").exists()
    written = json.loads((out_dir / "acme.json").read_text(encoding="utf-8"))
    assert written["status"] == "empty"
    assert written["latlng"] is None
    assert not called

def test_behaviour_parity_across_modes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Verify that dry-run record == written record for the same input."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }))

    monkeypatch.setattr(pdok, "exact", lambda pc, hn: {"lat": 52.0, "lng": 5.0})

    out_dir = tmp_path / "geocoding"
    
    # Run in dry-run mode
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir), "--dry-run"])
    captured = capsys.readouterr()
    dry_record = json.loads(captured.out.strip())

    # Run in normal mode
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir)])
    written_record = json.loads((out_dir / "acme.json").read_text(encoding="utf-8"))

    assert dry_record == written_record

def test_non_nl_not_queried_globally(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify non-NL country does not query PDOK and returns empty."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Rue de la Loi 16", "postcode": "1000", "city": "Brussels", "country": "BE"}
    }))

    called = False
    def mock_exact(pc, hn):
        nonlocal called
        called = True
        return {"lat": 52.0, "lng": 5.0}
    monkeypatch.setattr(pdok, "exact", mock_exact)

    out_dir = tmp_path / "geocoding"
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir)])
    
    written = json.loads((out_dir / "acme.json").read_text(encoding="utf-8"))
    assert written["status"] == "empty"
    assert not called

def test_no_response_cache_persisted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that multiple runs execute queries without caching responses on disk."""
    input_dir = tmp_path / "fact-extraction"
    input_dir.mkdir()
    (input_dir / "acme.json").write_text(json.dumps({
        "name": "Acme B.V.",
        "status": "regex_single",
        "address": {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}
    }))

    calls = 0
    def mock_exact(pc, hn):
        nonlocal calls
        calls += 1
        return {"lat": 52.0, "lng": 5.0}
    monkeypatch.setattr(pdok, "exact", mock_exact)

    out_dir = tmp_path / "geocoding"
    
    # Run once
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir)])
    # Run twice
    cli_main(["--input", str(input_dir), "--out-dir", str(out_dir)])

    assert calls == 2
