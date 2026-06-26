"""Tests for the fact-extraction stage."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.fact_extraction import core as core_module
from pipeline.fact_extraction.address import Candidate, extract_candidates, validate_postcode
from pipeline.fact_extraction.core import process, run
from pipeline.fact_extraction.llm import LLMError

REPO_ROOT = Path(__file__).resolve().parents[1]
SMALL_TEST_SET = REPO_ROOT / "test-set" / "companies.json"
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(
    name: str = "Acme B.V.",
    status: str = "ok",
    footer_text: str | None = None,
    structured_text: str | None = None,
) -> dict:
    return {
        "name": name,
        "website": "https://acme.example",
        "status": status,
        "footer_text": footer_text,
        "structured_text": structured_text,
        "pages_collected": 1,
    }


def _proc(meta: dict, pages: dict | None = None, *, offline: bool = False) -> dict:
    return process(meta, pages or {}, out_dir=Path("/nonexistent"), write=False, offline=offline)


# ---------------------------------------------------------------------------
# address.py: postcode extraction
# ---------------------------------------------------------------------------


def test_single_clean_footer_hit() -> None:
    meta = _meta(footer_text="Europalaan 100, 3526 KS Utrecht | KVK 12345678")
    result = _proc(meta)
    assert result["status"] == "regex_single"
    assert result["address"]["postcode"] == "3526 KS"
    assert result["address"]["city"] == "Utrecht"
    assert result["address"]["street"] == "Europalaan 100"
    assert result["address"]["country"] == "NL"


def test_all_fields_present() -> None:
    meta = _meta(footer_text="Hoofdstraat 5, 1011 AA Amsterdam")
    result = _proc(meta)
    assert result["status"] == "regex_single"
    addr = result["address"]
    assert addr["postcode"] == "1011 AA"
    assert addr["city"] == "Amsterdam"
    assert addr["street"] is not None
    assert addr["country"] == "NL"


def test_lowercase_not_matched_by_regex() -> None:
    # Lowercase letter pairs are not matched — they're indistinguishable from prose
    # (e.g. "launched in 2015 to incredibly"). Lowercase postcodes fall to LLM fallback.
    # A contact page is required so the fallback surface is non-empty.
    meta = _meta(footer_text="Straat 1, 1234 ab Den Haag")
    pages = {"contact": "Straat 1, 1234 ab Den Haag"}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": "Straat 1", "postcode": "1234 AB", "city": "Den Haag", "country": "NL"}
        result = _proc(meta, pages)
    assert result["status"] == "llm_fallback"
    assert result["address"]["postcode"] == "1234 AB"


def test_nospace_normalised() -> None:
    meta = _meta(footer_text="Straat 1, 1234AB Den Haag")
    result = _proc(meta)
    assert result["address"]["postcode"] == "1234 AB"


def test_nonbreaking_space_tolerated() -> None:
    # Non-breaking space (\xa0) between digits and letters
    footer = "Straat 1, 3526\xa0KS Utrecht"
    meta = _meta(footer_text=footer)
    result = _proc(meta)
    assert result["address"]["postcode"] == "3526 KS"
    assert result["address"]["city"] == "Utrecht"


def test_postcode_multiple_whitespace_tolerated() -> None:
    # Raw visible-text surfaces sometimes render the gap as several spaces/NBSPs.
    meta = _meta(footer_text="Vening Meinesz building C\n3526  KV  Utrecht, The Netherlands")
    result = _proc(meta)
    assert result["address"]["postcode"] == "3526 KV"
    assert result["address"]["city"] == "Utrecht"

    meta2 = _meta(footer_text="Straat 1, 3526\xa0\xa0KS Utrecht")
    assert _proc(meta2)["address"]["postcode"] == "3526 KS"


def test_postcode_does_not_span_newline() -> None:
    # A 4-digit line end followed by a 2-uppercase line start must NOT match
    # (the digit/letter gap is horizontal whitespace only).
    meta = _meta(footer_text="Founded 2024\n\nNL based company")
    result = _proc(meta, offline=True)
    assert result["address"]["postcode"] is None


def test_postcode_in_email_rejected() -> None:
    meta = _meta(footer_text="Contact: support@1234ab.example.com for help")
    result = _proc(meta, offline=True)
    # Should find no candidates; goes to empty in offline mode
    assert result["address"]["postcode"] is None


# ---------------------------------------------------------------------------
# address.py: city normalisation
# ---------------------------------------------------------------------------


def test_city_after_leading_comma_recovered() -> None:
    meta = _meta(footer_text="Europalaan 100\n3584 CB, Utrecht")
    assert _proc(meta)["address"]["city"] == "Utrecht"


def test_city_on_next_line_recovered() -> None:
    meta = _meta(footer_text="Europalaan 100\n3584 CB\nUtrecht")
    assert _proc(meta)["address"]["city"] == "Utrecht"


def test_city_bullet_and_boilerplate_trimmed() -> None:
    meta = _meta(footer_text="3584 CB Utrecht • KVK: 97376019 • BTW: NL868025")
    assert _proc(meta)["address"]["city"] == "Utrecht"


def test_city_closing_paren_ends_city() -> None:
    meta = _meta(footer_text="3584 CB Utrecht) is gespecialiseerd in AI-consultancy")
    assert _proc(meta)["address"]["city"] == "Utrecht"


def test_city_boilerplate_label_without_bullet_trimmed() -> None:
    meta = _meta(footer_text="3584 CB Utrecht KVK: 97376019")
    assert _proc(meta)["address"]["city"] == "Utrecht"


def test_city_fused_country_suffix_stripped() -> None:
    meta = _meta(footer_text="3953 MJ MaarsbergenThe Netherlands")
    assert _proc(meta)["address"]["city"] == "Maarsbergen"


def test_city_spaced_country_suffix_stripped() -> None:
    meta = _meta(footer_text="3811 NJ Amersfoort The Netherlands")
    assert _proc(meta)["address"]["city"] == "Amersfoort"


def test_city_html_entity_decoded() -> None:
    meta = _meta(footer_text="3811 NJ Amersfoort&nbsp;")
    assert _proc(meta)["address"]["city"] == "Amersfoort"


def test_city_recovered_from_line_before_street() -> None:
    meta = _meta(footer_text="Amersfoort\nKoningstraat 1\n1234 AB")
    assert _proc(meta)["address"]["city"] == "Amersfoort"


def test_prior_line_recovery_declines_on_noisy_line() -> None:
    meta = _meta(footer_text="Bel ons op 030-1234567\nKoningstraat 1\n1234 AB")
    assert _proc(meta)["address"]["city"] is None


def test_partial_address() -> None:
    # Only city extractable via LLM fallback
    pages = {"contact": "Wij zijn gevestigd in Utrecht. Neem contact op via info@acme.example."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": "Utrecht", "country": "NL"}
        result = _proc(_meta(), pages)
    assert result["status"] == "llm_fallback"
    assert result["address"]["city"] == "Utrecht"
    assert result["address"]["street"] is None
    assert result["address"]["postcode"] is None


def test_no_address_found() -> None:
    pages = {"contact": "Contact us at info@acme.example for more information."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": None, "country": None}
        result = _proc(_meta(), pages)
    assert result["status"] == "llm_fallback"
    assert all(v is None for v in result["address"].values())


# ---------------------------------------------------------------------------
# Postbus filtering
# ---------------------------------------------------------------------------


def test_postbus_only_footer() -> None:
    meta = _meta(footer_text="Postbus 123, 3500 AA Utrecht")
    # A contact page is required so the fallback surface is non-empty after footer exclusion.
    pages = {"contact": "Wij zijn gevestigd in Utrecht."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": None, "country": None}
        result = _proc(meta, pages)
    # Postbus filtered → falls to LLM fallback path
    assert result["status"] == "llm_fallback"


def test_postbus_and_bezoekadres() -> None:
    footer = "Postbus 123, 3500 AA Utrecht | Bezoekadres: Europalaan 100, 3526 KS Utrecht"
    meta = _meta(footer_text=footer)
    result = _proc(meta)
    # Postbus stripped, bezoekadres-boosted candidate wins → regex_single, no LLM
    assert result["status"] == "regex_single"
    assert result["address"]["postcode"] == "3526 KS"


# ---------------------------------------------------------------------------
# Hint-based ranking
# ---------------------------------------------------------------------------


def test_two_postcodes_hauptkantoor_hint() -> None:
    # Only the second address is labelled hoofdkantoor → sole boost → regex_single without LLM
    footer = "Ons adres: Straat 1, 3011 AA Rotterdam\nHoofdkantoor: Europalaan 100, 3526 KS Utrecht"
    meta = _meta(footer_text=footer)
    result = _proc(meta)
    assert result["status"] == "regex_single"
    assert result["address"]["postcode"] == "3526 KS"


def test_boost_wins_without_llm() -> None:
    footer = "Branch: Kerkstraat 5, 2011 BB Haarlem\nHoofdkantoor: Hoofdstraat 1, 1011 AA Amsterdam"
    meta = _meta(footer_text=footer)
    result = _proc(meta)
    assert result["status"] == "regex_single"
    assert result["address"]["postcode"] == "1011 AA"


def test_postadres_demoted() -> None:
    # postadres candidate + unhinged candidate — unhinged ranks higher
    footer = "Postadres: Straat 1, 1234 AB Amsterdam\nStraat 2, 5678 CD Utrecht"
    meta = _meta(footer_text=footer)
    # Two candidates → disambiguation
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"hq_index": 0}  # top-ranked (non-demoted) Utrecht
        result = _proc(meta)
    # The demoted Amsterdam candidate should not be index 0
    candidates = extract_candidates(footer, {})
    assert candidates[0].postcode == "5678 CD"  # Utrecht, non-demoted ranks first


def test_footer_beats_body() -> None:
    footer = "Straat 1, 1234 AA Amsterdam"
    pages = {"contact": "Adres: Straat 2, 5678 BB Rotterdam"}
    candidates = extract_candidates(footer, pages)
    assert candidates[0].surface == "footer"
    assert candidates[0].postcode == "1234 AA"


def test_structured_text_anchored() -> None:
    meta = _meta(structured_text="Stadsplateau 34 3521 AZ Utrecht")
    result = _proc(meta)
    assert result["status"] == "regex_single"
    assert result["address"] == {
        "street": "Stadsplateau 34",
        "postcode": "3521 AZ",
        "city": "Utrecht",
        "country": "NL",
    }


def test_postcode_on_non_address_page_anchored() -> None:
    meta = _meta()
    pages = {"index": "Adres\nEuropalaan 100\n3526 KS Utrecht"}
    result = _proc(meta, pages)
    assert result["status"] == "regex_single"
    assert result["address"]["postcode"] == "3526 KS"


def test_structured_beats_footer_beats_body() -> None:
    candidates = extract_candidates(
        "Footerstraat 2, 2222 BB Rotterdam",
        {"about": "Bodystraat 3, 3333 CC Amsterdam"},
        "Structuurstraat 1, 1111 AA Utrecht",
    )
    assert [c.surface for c in candidates] == ["structured", "footer", "body"]
    assert [c.postcode for c in candidates] == ["1111 AA", "2222 BB", "3333 CC"]


# ---------------------------------------------------------------------------
# Disambiguation path
# ---------------------------------------------------------------------------


def test_two_equal_candidates_resolved() -> None:
    footer = "Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam"
    meta = _meta(footer_text=footer)
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"hq_index": 1}
        result = _proc(meta)
    assert result["status"] == "regex_disambiguated"
    assert result["address"]["postcode"] == "5678 BB"
    # Verify the call was made with both candidates
    call_args = mock_call.call_args[0][0]  # messages
    assert any("1234 AA" in str(m) for m in call_args)
    assert any("5678 BB" in str(m) for m in call_args)


def test_llm_declines_to_pick() -> None:
    footer = "Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam"
    meta = _meta(footer_text=footer)
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"hq_index": None}
        result = _proc(meta)
    assert result["status"] == "empty"


# ---------------------------------------------------------------------------
# LLM fallback path
# ---------------------------------------------------------------------------


def test_prose_only_address() -> None:
    meta = _meta(footer_text=None)
    pages = {"about": "Wij zijn gevestigd in het centrum van Utrecht."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": "Utrecht", "country": "NL"}
        result = process(meta, pages, out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "llm_fallback"
    assert result["address"]["city"] == "Utrecht"


def test_fallback_yields_nothing() -> None:
    pages = {"contact": "Contact us at info@acme.example for more information."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": None, "country": None}
        result = _proc(_meta(), pages)
    assert result["status"] == "llm_fallback"  # NOT "empty" — path label preserved


def test_invalid_postcode_dropped() -> None:
    pages = {"contact": "Wij zijn gevestigd in Utrecht. Neem contact op via info@acme.example."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": "3526", "city": "Utrecht", "country": "NL"}
        result = _proc(_meta(), pages)
    assert result["address"]["postcode"] is None
    assert result["address"]["city"] == "Utrecht"


# ---------------------------------------------------------------------------
# Status path labelling
# ---------------------------------------------------------------------------


def test_status_path_labelling() -> None:
    # Prose fallback returning all-null → llm_fallback
    pages = {"contact": "Contact us at info@acme.example for more information."}
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"street": None, "postcode": None, "city": None, "country": None}
        fallback_result = _proc(_meta(), pages)
    assert fallback_result["status"] == "llm_fallback"

    # Disambiguation declining → empty
    footer = "Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam"
    meta2 = _meta(footer_text=footer)
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.return_value = {"hq_index": None}
        disambig_result = _proc(meta2)
    assert disambig_result["status"] == "empty"


# ---------------------------------------------------------------------------
# Upstream failure
# ---------------------------------------------------------------------------


def test_upstream_failure_propagation() -> None:
    meta = _meta(status="upstream_failed")
    result = _proc(meta)
    assert result["status"] == "upstream_failed"
    assert all(v is None for v in result["address"].values())


def test_fetch_failed_propagation() -> None:
    meta = _meta(status="fetch_failed")
    result = _proc(meta)
    assert result["status"] == "upstream_failed"


# ---------------------------------------------------------------------------
# Key pass-through
# ---------------------------------------------------------------------------


def test_extra_input_keys_preserved() -> None:
    meta = _meta(footer_text="Straat 1, 1234 AA Amsterdam")
    meta["source_list"] = "incubator-2026"
    result = _proc(meta)
    assert result["source_list"] == "incubator-2026"


# ---------------------------------------------------------------------------
# Name-collision guard
# ---------------------------------------------------------------------------


def test_name_collision_refusal(tmp_path: Path) -> None:
    existing = {"name": "Acme B.V.", "status": "regex_single", "address": {}, "source": None}
    out_path = tmp_path / "acme.json"
    out_path.write_text(json.dumps(existing), encoding="utf-8")

    meta = _meta(name="Acme Holding", footer_text="Straat 1, 1234 AA Amsterdam")
    # Use write=True so it reaches the collision check
    with pytest.raises(RuntimeError, match="collision"):
        process(meta, {}, out_dir=tmp_path, write=True)


# ---------------------------------------------------------------------------
# LLM error handling
# ---------------------------------------------------------------------------


def test_llm_error_distinct_from_empty() -> None:
    footer = "Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam"
    meta = _meta(footer_text=footer)
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        mock_call.side_effect = LLMError("timeout")
        result = _proc(meta)
    assert result["status"] == "llm_error"
    assert all(v is None for v in result["address"].values())


def test_one_llm_failure_does_not_abort_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: One LLM failure does not abort batch (concurrent, two-phase).

    Failure is keyed off a marker in the company's disambiguation messages, not
    call order, so the assertion holds under the concurrent pool. Alpha resolves
    via regex (Phase 1, no LLM); Beta and Gamma both disambiguate (Phase 2 pool).
    """
    content_dir = tmp_path / "content-collection"
    monkeypatch.setenv("FACT_EXTRACTION_CONCURRENCY", "4")

    def _make_company(name: str, footer: str) -> None:
        from pipeline.website_resolution import company_id
        d = content_dir / company_id(name)
        d.mkdir(parents=True)
        meta = {"name": name, "website": "https://example.com", "status": "ok", "footer_text": footer}
        (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    _make_company("Alpha B.V.", "Straat 1, 1234 AA Amsterdam")
    _make_company("Beta B.V.", "FAILME Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam")
    _make_company("Gamma B.V.", "Straat 5, 5555 XX Eindhoven\nStraat 6, 6666 YY Arnhem")

    records = [
        {"name": "Alpha B.V.", "website": "https://alpha.example"},
        {"name": "Beta B.V.", "website": "https://beta.example"},
        {"name": "Gamma B.V.", "website": "https://gamma.example"},
    ]

    def flaky_call(messages, **kwargs):  # noqa: ANN001
        if "FAILME" in json.dumps(messages):
            raise LLMError("beta fails")
        return {"hq_index": 0}

    out_dir = tmp_path / "fact-extraction"
    with patch("pipeline.fact_extraction.core.llm_module.call", side_effect=flaky_call):
        results = list(run(records, out_dir=out_dir, write=False, content_dir=content_dir))

    by_name = {r["name"]: r for r in results}
    assert by_name["Alpha B.V."]["status"] == "regex_single"
    assert by_name["Beta B.V."]["status"] == "llm_error"
    assert by_name["Gamma B.V."]["status"] == "regex_disambiguated"


def test_concurrent_yields_input_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Concurrent processing yields in input order (two-phase).

    Both companies defer to the disambiguation LLM (Phase 2); the first is slowed.
    Even though the second completes first, ``run()`` yields the first first.
    """
    content_dir = tmp_path / "content-collection"
    monkeypatch.setenv("FACT_EXTRACTION_CONCURRENCY", "4")

    def _make_company(name: str, footer: str) -> None:
        from pipeline.website_resolution import company_id
        d = content_dir / company_id(name)
        d.mkdir(parents=True)
        meta = {"name": name, "website": "https://example.com", "status": "ok", "footer_text": footer}
        (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    _make_company("Slow Co B.V.", "SLOWMARKER Straat 1, 1234 AA Amsterdam\nStraat 2, 5678 BB Rotterdam")
    _make_company("Fast Co B.V.", "FASTMARKER Straat 5, 5555 XX Eindhoven\nStraat 6, 6666 YY Arnhem")

    records = [
        {"name": "Slow Co B.V.", "website": "https://slow.example"},
        {"name": "Fast Co B.V.", "website": "https://fast.example"},
    ]

    def _slow_first(messages, **kwargs):  # noqa: ANN001
        if "SLOWMARKER" in json.dumps(messages):
            time.sleep(0.3)
        return {"hq_index": 0}

    out_dir = tmp_path / "fact-extraction"
    with patch("pipeline.fact_extraction.core.llm_module.call", side_effect=_slow_first):
        results = list(run(records, out_dir=out_dir, write=False, content_dir=content_dir))

    assert [r["name"] for r in results] == ["Slow Co B.V.", "Fast Co B.V."]


# ---------------------------------------------------------------------------
# Dry-run and offline modes
# ---------------------------------------------------------------------------


def test_recall_md_preferred_over_md(tmp_path: Path) -> None:
    """`_load_company` SHALL prefer <slug>.recall.md over <slug>.md."""
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id

    cid = company_id("Acme B.V.")
    d = content_dir / cid
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}),
        encoding="utf-8",
    )
    # Precision file has no address; recall file does. fact-extraction must
    # pick up the recall content and resolve via regex_single.
    (d / "contact.md").write_text("Generic FAQ prose with no address whatsoever.", encoding="utf-8")
    (d / "contact.recall.md").write_text("Adres\nEuropalaan 100\n3526 KS Utrecht", encoding="utf-8")

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))
    assert len(results) == 1
    assert results[0]["status"] == "regex_single"
    assert results[0]["address"]["postcode"] == "3526 KS"


def test_md_used_when_no_recall_md(tmp_path: Path) -> None:
    """`_load_company` SHALL fall back to <slug>.md when no .recall.md exists."""
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id

    cid = company_id("Acme B.V.")
    d = content_dir / cid
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}),
        encoding="utf-8",
    )
    (d / "contact.md").write_text("Adres\nEuropalaan 100\n3526 KS Utrecht", encoding="utf-8")

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))
    assert results[0]["status"] == "regex_single"
    assert results[0]["address"]["postcode"] == "3526 KS"


def test_recall_md_preferred_for_widened_address_slug(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id

    cid = company_id("Acme B.V.")
    d = content_dir / cid
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(
        json.dumps(
            {"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}
        ),
        encoding="utf-8",
    )
    (d / "colofon.md").write_text("Generic legal prose.", encoding="utf-8")
    (d / "colofon.recall.md").write_text("Adres\nEuropalaan 100\n3526 KS Utrecht", encoding="utf-8")

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))

    assert results[0]["status"] == "regex_single"
    assert results[0]["address"]["postcode"] == "3526 KS"


def test_all_collected_pages_loaded_for_postcode_anchor(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id

    cid = company_id("Acme B.V.")
    d = content_dir / cid
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}),
        encoding="utf-8",
    )
    (d / "careers.md").write_text("Office\nEuropalaan 100\n3526 KS Utrecht", encoding="utf-8")

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))

    assert results[0]["status"] == "regex_single"
    assert results[0]["address"]["postcode"] == "3526 KS"


def test_fallback_surface_includes_widened_address_slugs() -> None:
    pages = {
        "privacy": "Privacy address prose",
        "disclaimer": "Disclaimer address prose",
        "platform": "Platform prose should not be included",
    }
    surface = core_module._build_fallback_surface(None, pages)
    assert "Privacy address prose" in surface
    assert "Disclaimer address prose" in surface
    assert "Platform prose" not in surface


def test_fallback_surface_includes_address_intent_variants() -> None:
    pages = {
        "privacy-policy": "Variant privacy prose",
        "support-contact": "Variant contact prose",
        "solutions": "Solutions prose should not be included",
    }
    surface = core_module._build_fallback_surface(None, pages)
    assert "Variant privacy prose" in surface
    assert "Variant contact prose" in surface
    assert "Solutions prose" not in surface


def test_visible_txt_recovers_dropped_address(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id

    d = content_dir / company_id("Acme B.V.")
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}),
        encoding="utf-8",
    )
    # trafilatura dropped the address from the markdown, but the raw visible-text
    # surface kept it. The postcode anchor must recover it without an LLM call.
    (d / "contact.md").write_text("Get in touch via the form below.", encoding="utf-8")
    (d / "contact.visible.txt").write_text(
        "Contact\nPrincetonlaan 6\n3584 CB Utrecht", encoding="utf-8"
    )

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))

    assert results[0]["status"] == "regex_single"
    assert results[0]["address"]["postcode"] == "3584 CB"
    assert results[0]["address"]["city"] == "Utrecht"


def test_dry_run_yields_without_writing(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id
    d = content_dir / company_id("Acme B.V.")
    d.mkdir(parents=True)
    meta = {"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": "Straat 1, 1234 AA Amsterdam"}
    (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    out_dir = tmp_path / "fact-extraction"
    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    results = list(run(records, out_dir=out_dir, write=False, content_dir=content_dir))

    assert len(results) == 1
    assert results[0]["status"] == "regex_single"
    assert not out_dir.exists() or not any(out_dir.iterdir())


def test_offline_mode_short_circuits_llm(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id
    d = content_dir / company_id("Acme B.V.")
    d.mkdir(parents=True)
    meta = {"name": "Acme B.V.", "website": "https://acme.example", "status": "ok", "footer_text": None}
    (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    records = [{"name": "Acme B.V.", "website": "https://acme.example"}]
    with patch("pipeline.fact_extraction.core.llm_module.call") as mock_call:
        results = list(run(records, out_dir=tmp_path / "out", write=False, offline=True, content_dir=content_dir))
    mock_call.assert_not_called()
    assert results[0]["address"]["postcode"] is None


def test_behaviour_parity_across_modes(tmp_path: Path) -> None:
    content_dir = tmp_path / "content-collection"
    from pipeline.website_resolution import company_id
    d = content_dir / company_id("Parity B.V.")
    d.mkdir(parents=True)
    meta = {"name": "Parity B.V.", "website": "https://parity.example", "status": "ok", "footer_text": "Straat 5, 4321 ZZ Rotterdam"}
    (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    records = [{"name": "Parity B.V.", "website": "https://parity.example"}]

    # Orchestrator mode (write=False)
    results_orch = list(run(records, out_dir=tmp_path / "out", write=False, content_dir=content_dir))

    # CLI mode (write=True)
    out_dir = tmp_path / "out2"
    list(run(records, out_dir=out_dir, write=True, content_dir=content_dir))
    written = json.loads((out_dir / f"{company_id('Parity B.V.')}.json").read_text())

    # Both should have identical address/status
    assert results_orch[0]["status"] == written["status"]
    assert results_orch[0]["address"] == written["address"]


# ---------------------------------------------------------------------------
# LLM: fence stripping
# ---------------------------------------------------------------------------


def test_fenced_llm_json_parsed() -> None:
    from pipeline.fact_extraction.llm import _parse_json

    fenced = '```json\n{"hq_index": 1}\n```'
    result = _parse_json(fenced)
    assert result == {"hq_index": 1}


# ---------------------------------------------------------------------------
# validate_postcode
# ---------------------------------------------------------------------------


def test_validate_postcode_valid() -> None:
    assert validate_postcode("3526 KS") == "3526 KS"
    assert validate_postcode("3526KS") == "3526 KS"
    assert validate_postcode("3526 ks") == "3526 KS"


def test_validate_postcode_invalid() -> None:
    assert validate_postcode("3526") is None
    assert validate_postcode("ABCD EF") is None
    assert validate_postcode(None) is None


# ---------------------------------------------------------------------------
# Network tests
# ---------------------------------------------------------------------------


@pytest.mark.network
def _run_network_test(test_set_path: Path) -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")

    companies = json.loads(test_set_path.read_text(encoding="utf-8"))
    content_dir = REPO_ROOT / "data" / "content-collection"
    if not content_dir.exists():
        pytest.skip("data/content-collection not present")

    results = list(
        run(
            companies,
            out_dir=REPO_ROOT / "data" / "fact-extraction",
            write=True,
            content_dir=content_dir,
        )
    )

    assert len(results) == len(companies), "All companies must produce a result"
    for r in results:
        assert "status" in r
        assert "address" in r

    # Companies whose footer_text contains a postcode should mostly land in regex_single
    postcode_companies = []
    for r in results:
        from pipeline.website_resolution import company_id
        cid = company_id(r.get("name", ""))
        meta_path = content_dir / cid / "_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            footer = meta.get("footer_text") or ""
            import re
            if re.search(r"\d{4}\s?[A-Z]{2}", footer, re.IGNORECASE):
                postcode_companies.append(r)

    if postcode_companies:
        regex_single_count = sum(1 for r in postcode_companies if r["status"] == "regex_single")
        ratio = regex_single_count / len(postcode_companies)
        assert ratio >= 0.5, (
            f"Expected ≥50% regex_single for postcode-footer companies, got {ratio:.0%} "
            f"({regex_single_count}/{len(postcode_companies)})"
        )


@pytest.mark.network
def test_network_small_set() -> None:
    _run_network_test(SMALL_TEST_SET)


@pytest.mark.network
def test_network_medium_set() -> None:
    _run_network_test(MEDIUM_TEST_SET)
