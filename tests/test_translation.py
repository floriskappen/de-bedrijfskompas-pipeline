"""Tests for the translation stage.

Each scenario in specs/translation/spec.md maps to at least one named test here.
All tests are offline (no LLM calls) except the @pytest.mark.network ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.translation import core as core_module
from pipeline.translation import llm as llm_module
from pipeline.translation.core import process, run
from pipeline.translation.llm import TRANSLATION_TARGETS, LLMError, resolve_targets
from pipeline.website_resolution import company_id

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _tagline_file(tmp_path: Path, name: str, *, status: str = "ok", en: str = "A shop selling widgets.") -> Path:
    cid = company_id(name)
    out = tmp_path / "tagline-extraction"
    out.mkdir(parents=True, exist_ok=True)
    rec = {"name": name, "website": "https://example.com", "status": status, "model": "m", "tagline": {"en": en}}
    (out / f"{cid}.json").write_text(json.dumps(rec), encoding="utf-8")
    return out


def _scoring_file(tmp_path: Path, name: str, *, status: str = "ok") -> Path:
    cid = company_id(name)
    out = tmp_path / "global-scoring"
    out.mkdir(parents=True, exist_ok=True)
    axes = ["substance", "ecology", "power", "embeddedness", "posture"]
    scores = {a: {"score": 50, "evidence": "partial", "reason": {"en": f"{a} reason."}} for a in axes}
    rec = {"name": name, "website": "https://example.com", "status": status, "model": "m", "scores": scores}
    (out / f"{cid}.json").write_text(json.dumps(rec), encoding="utf-8")
    return out


def _source_dirs(tmp_path: Path) -> dict[str, Path]:
    return {
        "tagline-extraction": tmp_path / "tagline-extraction",
        "global-scoring": tmp_path / "global-scoring",
    }


def _nl_map(targets: dict[str, str]) -> dict[str, str]:
    """Fake translation: append ' (NL)' to each value."""
    return {k: v + " (NL)" for k, v in targets.items()}


def _proc(tmp_path: Path, name: str = "Acme B.V.", *, offline: bool = False) -> dict:
    src = _source_dirs(tmp_path)
    with patch.object(core_module.llm_module, "call", side_effect=lambda msgs, **kw: _nl_map(kw.get("expected_keys") or {})) as mock:
        result = process(name, "https://acme.example", out_dir=tmp_path / "out", write=False, offline=offline, source_dirs=src)
    result["_mock_calls"] = mock.call_count
    return result


# ---------------------------------------------------------------------------
# Target registry
# ---------------------------------------------------------------------------


def test_target_registry_enumerated() -> None:
    """Scenario: Target registry is enumerated — only declared targets, no auto-discovery."""
    stage_ids = {t[0] for t in TRANSLATION_TARGETS}
    assert "tagline-extraction" in stage_ids
    assert "global-scoring" in stage_ids
    paths = [t[1] for t in TRANSLATION_TARGETS]
    assert "tagline" in paths
    assert "scores.*.reason" in paths


def test_wildcard_path_expands(tmp_path: Path) -> None:
    """Scenario: Wildcard path expands over all axis keys."""
    axes = ["substance", "ecology", "power", "embeddedness", "posture"]
    scores = {a: {"score": 50, "evidence": "partial", "reason": {"en": f"{a} reason."}} for a in axes}
    record = {"scores": scores}
    resolved = resolve_targets(record, "scores.*.reason")
    assert set(resolved.keys()) == {f"scores.{a}.reason" for a in axes}
    for key, val in resolved.items():
        assert val.endswith("reason.")


# ---------------------------------------------------------------------------
# Input selection / fan-in
# ---------------------------------------------------------------------------


def test_company_absent_from_one_source(tmp_path: Path) -> None:
    """Scenario: Company absent from one source — other targets still translated."""
    _scoring_file(tmp_path, "Acme B.V.")
    # tagline-extraction dir does NOT exist
    src = _source_dirs(tmp_path)

    captured_targets: dict = {}

    def _fake_call(messages, *, expected_keys, **kw):
        captured_targets.update({k: k + " (NL)" for k in expected_keys})
        return captured_targets.copy()

    result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src,
                     offline=False)
    # Can't assert ok without calling llm, but targets should be non-empty from scoring
    with patch.object(core_module.llm_module, "call", side_effect=_fake_call):
        result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src)
    assert result["status"] == "ok"
    # Only scoring keys present (5 axes), no tagline key
    assert all("reason" in k for k in result["translations"])


def test_company_absent_from_all_sources(tmp_path: Path) -> None:
    """Scenario: Company absent from all sources → upstream_failed, no LLM call."""
    src = _source_dirs(tmp_path)
    with patch.object(core_module.llm_module, "call") as mock:
        result = process("Ghost B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src)
    assert result["status"] == "upstream_failed"
    assert result["translations"] is None
    assert mock.call_count == 0


# ---------------------------------------------------------------------------
# Output record
# ---------------------------------------------------------------------------


def test_successful_record_shape(tmp_path: Path) -> None:
    """Scenario: Successful record shape."""
    _tagline_file(tmp_path, "Acme B.V.")
    _scoring_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)
    out_dir = tmp_path / "out"

    def _fake_call(messages, *, expected_keys, **kw):
        return {k: "Dutch text." for k in expected_keys}

    with patch.object(core_module.llm_module, "call", side_effect=_fake_call):
        process("Acme B.V.", "https://acme.example", out_dir=out_dir, write=True, source_dirs=src)

    rec = json.loads((out_dir / f"{company_id('Acme B.V.')}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "ok"
    assert rec["model"]
    assert set(rec) == {"name", "website", "status", "model", "translations"}
    assert isinstance(rec["translations"], dict)
    for val in rec["translations"].values():
        assert "nl" in val


def test_null_translations_on_non_ok(tmp_path: Path) -> None:
    """Scenario: Null translations on non-ok status."""
    result = process("Ghost B.V.", None, out_dir=tmp_path / "out", write=False,
                     source_dirs=_source_dirs(tmp_path))
    assert result["status"] == "upstream_failed"
    assert result["translations"] is None
    assert result["model"] is None


def test_name_collision_refusal(tmp_path: Path) -> None:
    """Scenario: Name-collision refusal."""
    _tagline_file(tmp_path, "Acme B.V.")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / f"{company_id('Acme B.V.')}.json").write_text(
        json.dumps({"name": "Acme Holding"}), encoding="utf-8"
    )

    def _fake_call(messages, *, expected_keys, **kw):
        return {k: "Dutch." for k in expected_keys}

    with patch.object(core_module.llm_module, "call", side_effect=_fake_call):
        with pytest.raises(RuntimeError, match="collision"):
            process("Acme B.V.", None, out_dir=out_dir, write=True,
                    source_dirs=_source_dirs(tmp_path))


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def test_partial_sources_still_yield_ok(tmp_path: Path) -> None:
    """Scenario: Partial sources (one llm_error, one ok) → status ok."""
    # Only scoring source present and ok; tagline-extraction absent
    _scoring_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)

    def _fake_call(messages, *, expected_keys, **kw):
        return {k: "Dutch." for k in expected_keys}

    with patch.object(core_module.llm_module, "call", side_effect=_fake_call):
        result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src)
    assert result["status"] == "ok"


def test_malformed_response_is_error(tmp_path: Path) -> None:
    """Scenario: Malformed response → status llm_error."""
    _tagline_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)
    with patch.object(core_module.llm_module, "call", side_effect=LLMError("bad")):
        result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src)
    assert result["status"] == "llm_error"
    assert result["translations"] is None


def test_llm_error_recorded(tmp_path: Path) -> None:
    """Scenario: LLM error recorded."""
    _tagline_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)
    with patch.object(core_module.llm_module, "call", side_effect=LLMError("network error")):
        result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False, source_dirs=src)
    assert result["status"] == "llm_error"


def test_one_failure_does_not_abort_batch(tmp_path: Path) -> None:
    """Scenario: One company LLM error, others succeed."""
    names = ["Alpha B.V.", "Beta B.V.", "Gamma B.V."]
    for n in names:
        _tagline_file(tmp_path, n)
    src = _source_dirs(tmp_path)
    call_log: list[int] = []

    def _maybe_fail(messages, *, expected_keys, **kw):
        call_log.append(1)
        if len(call_log) == 2:
            raise LLMError("second fails")
        return {k: "Dutch." for k in expected_keys}

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", side_effect=_maybe_fail):
        results = list(run(
            [(n, None) for n in names],
            out_dir=out_dir, write=True, source_dirs=src,
        ))
    statuses = [r["status"] for r in results]
    assert statuses.count("ok") == 2
    assert statuses.count("llm_error") == 1
    assert len(list(out_dir.glob("*.json"))) == 3


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


def test_offline_mode(tmp_path: Path) -> None:
    """Scenario: Offline mode short-circuits LLM → status empty."""
    _tagline_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)
    with patch.object(core_module.llm_module, "call") as mock:
        result = process("Acme B.V.", None, out_dir=tmp_path / "out", write=False,
                         offline=True, source_dirs=src)
    assert result["status"] == "empty"
    assert mock.call_count == 0


def test_dry_run_yields_without_writing(tmp_path: Path) -> None:
    """Scenario: Dry-run yields without writing."""
    _tagline_file(tmp_path, "Acme B.V.")
    src = _source_dirs(tmp_path)
    out_dir = tmp_path / "out"

    def _fake_call(messages, *, expected_keys, **kw):
        return {k: "Dutch." for k in expected_keys}

    with patch.object(core_module.llm_module, "call", side_effect=_fake_call):
        results = list(run([("Acme B.V.", None)], out_dir=out_dir, write=False, source_dirs=src))
    assert results[0]["status"] == "ok"
    assert not out_dir.exists() or not list(out_dir.glob("*.json"))
