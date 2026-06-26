"""Tests for the tagging stage.

Each scenario in specs/tagging/spec.md maps to at least one named test here; the
mapping is noted in the change's tasks.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.tagging import core as core_module
from pipeline.tagging import frontmatter, llm as llm_module
from pipeline.tagging.core import load_prompt, process, run
from pipeline.tagging.llm import ISCO_MINOR_GROUPS, LLMError
from pipeline.website_resolution import company_id

REPO_ROOT = Path(__file__).resolve().parents[1]

_TAGS = [
    {"isco_code": "251", "prominence": "core", "confidence": "high"},
    {"isco_code": "243", "prominence": "supporting", "confidence": "high"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str = "Acme B.V.", status: str = "ok", website: str = "https://acme.example") -> dict:
    return {"name": name, "website": website, "status": status}


def _proc(meta: dict, body: str = "Acme builds SaaS for builders.", *, offline: bool = False, tags: list[dict] | None = None) -> dict:
    with patch.object(core_module.llm_module, "call", return_value=tags if tags is not None else _TAGS) as mock:
        result = process(meta, body, out_dir=Path("/nonexistent"), write=False, offline=offline)
    result["_mock_calls"] = mock.call_count
    return result


def _dossier(tmp_path: Path, name: str, *, status: str = "ok", body: str = "Acme builds SaaS.", website: str = "https://acme.example") -> Path:
    cid = company_id(name)
    path = tmp_path / f"{cid}.md"
    fm = f'---\nname: "{name}"\nwebsite: "{website}"\nstatus: "{status}"\n---\n\n{body}\n'
    path.write_text(fm, encoding="utf-8")
    return path


class _FakeResp:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def test_frontmatter_parsed() -> None:
    text = '---\nname: "Acme B.V."\nwebsite: "https://acme.example"\nstatus: "ok"\n---\n\n# Body\n'
    fields, body = frontmatter.parse(text)
    assert fields["name"] == "Acme B.V."
    assert fields["status"] == "ok"
    assert body.startswith("# Body")


# ---------------------------------------------------------------------------
# Input, gate
# ---------------------------------------------------------------------------


def test_dossier_body_is_llm_input() -> None:
    """Scenario: Dossier body is the LLM input."""
    captured: dict = {}

    def _capture(messages, **kwargs):  # noqa: ANN001
        captured["user"] = messages[-1]["content"]
        return _TAGS

    with patch.object(core_module.llm_module, "call", _capture):
        process(_meta(), "Builders pay Acme for SaaS.", out_dir=Path("/nonexistent"), write=False)
    assert "Builders pay Acme for SaaS." in captured["user"]


def test_missing_dossier_is_upstream_failed(tmp_path: Path) -> None:
    """Scenario: Missing dossier treated as upstream failure."""
    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value=_TAGS) as mock:
        results = list(run([_meta(name="Ghost B.V.")], out_dir=out_dir, write=True, content_dir=tmp_path))
    assert results[0]["status"] == "upstream_failed"
    assert results[0]["capability_tags"] is None
    assert mock.call_count == 0
    assert (out_dir / f"{company_id('Ghost B.V.')}.json").exists()


def test_non_ok_dossier_cascades() -> None:
    """Scenario: Non-ok dossier cascades."""
    result = _proc(_meta(status="llm_error"))
    assert result["status"] == "upstream_failed"
    assert result["capability_tags"] is None
    assert result["_mock_calls"] == 0


def test_ok_dossier_proceeds() -> None:
    """Scenario: Ok dossier proceeds."""
    result = _proc(_meta(status="ok"))
    assert result["status"] == "ok"
    assert result["_mock_calls"] == 1


def test_empty_body_recorded() -> None:
    result = _proc(_meta(status="ok"), "   \n  ")
    assert result["status"] == "empty"
    assert result["capability_tags"] is None
    assert result["_mock_calls"] == 0


# ---------------------------------------------------------------------------
# Vocabulary and tag shape (LLM parser)
# ---------------------------------------------------------------------------


def _post_returning(content: str):
    return lambda url, **kw: _FakeResp(content)


def test_emitted_isco_code_in_fixed_set() -> None:
    """Scenario: Emitted ISCO code is in the fixed set."""
    payload = json.dumps({"capability_tags": [{"isco_code": "251", "prominence": "core", "confidence": "high"}]})
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        tags = llm_module.call([{"role": "user", "content": "hi"}])
    assert tags == [{"isco_code": "251", "prominence": "core", "confidence": "high"}]
    assert all(t["isco_code"] in ISCO_MINOR_GROUPS for t in tags)
    assert len(ISCO_MINOR_GROUPS) == 130


def test_out_of_vocab_isco_code_is_llm_error() -> None:
    """Scenario: Out-of-vocabulary ISCO code is treated as LLM error."""
    payload = json.dumps({"capability_tags": [{"isco_code": "999", "prominence": "core", "confidence": "high"}]})
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_tag_has_isco_code_prominence_confidence() -> None:
    """Scenario: Tag carries ISCO code, prominence, and confidence."""
    payload = json.dumps({
        "capability_tags": [
            {"isco_code": "251", "prominence": "core", "confidence": "high"},
            {"isco_code": "243", "prominence": "supporting", "confidence": "low"},
        ]
    })
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        tags = llm_module.call([{"role": "user", "content": "hi"}])
    for entry in tags:
        assert set(entry.keys()) == {"isco_code", "prominence", "confidence"}
        assert entry["prominence"] in {"core", "supporting", "incidental"}
        assert entry["confidence"] in {"high", "low"}


def test_duplicate_isco_code_is_llm_error() -> None:
    """Scenario: One entry per ISCO code."""
    payload = json.dumps({
        "capability_tags": [
            {"isco_code": "251", "prominence": "core", "confidence": "high"},
            {"isco_code": "251", "prominence": "supporting", "confidence": "low"},
        ]
    })
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_invalid_prominence_is_llm_error() -> None:
    """Scenario: Invalid prominence is an LLM error."""
    payload = json.dumps({"capability_tags": [{"isco_code": "251", "prominence": "central", "confidence": "high"}]})
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_invalid_confidence_is_llm_error() -> None:
    """Scenario: Invalid confidence is an LLM error."""
    payload = json.dumps({"capability_tags": [{"isco_code": "251", "prominence": "core", "confidence": "medium"}]})
    with patch.object(llm_module.httpx, "post", _post_returning(payload)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_empty_array_parses() -> None:
    """An empty list is a valid (if rare) parse."""
    with patch.object(llm_module.httpx, "post", _post_returning('{"capability_tags": []}')):
        tags = llm_module.call([{"role": "user", "content": "hi"}])
    assert tags == []


def test_missing_capability_tags_key_is_llm_error() -> None:
    with patch.object(llm_module.httpx, "post", _post_returning('{"other": []}')):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Output record file
# ---------------------------------------------------------------------------


def test_successful_record_shape(tmp_path: Path) -> None:
    """Scenario: Successful record shape."""
    result = _proc(_meta())
    assert result["status"] == "ok"
    assert result["model"] is not None
    assert result["capability_tags"] == _TAGS

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value=_TAGS):
        process(_meta(), "body", out_dir=out_dir, write=True)
    file_path = out_dir / f"{company_id('Acme B.V.')}.json"
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    assert payload["name"] == "Acme B.V."
    assert payload["website"] == "https://acme.example"
    assert payload["status"] == "ok"
    assert payload["capability_tags"] == _TAGS


def test_null_capability_tags_on_non_ok() -> None:
    """Scenario: Null capability_tags on non-ok status."""
    for status in ("upstream_failed", "empty", "llm_error"):
        if status == "llm_error":
            with patch.object(core_module.llm_module, "call", side_effect=LLMError("boom")):
                result = process(_meta(), "body", out_dir=Path("/nonexistent"), write=False)
        elif status == "upstream_failed":
            result = _proc(_meta(status="llm_error"))
        else:
            result = _proc(_meta(status="ok"), "  ")
        assert result["status"] == status
        assert result["capability_tags"] is None


def test_empty_array_allowed_on_ok() -> None:
    """Scenario: Empty array allowed on ok."""
    result = _proc(_meta(status="ok"), tags=[])
    assert result["status"] == "ok"
    assert result["capability_tags"] == []


def test_name_collision_refusal(tmp_path: Path) -> None:
    """Scenario: Name-collision refusal."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cid = company_id("Acme B.V.")
    (out_dir / f"{cid}.json").write_text(
        json.dumps({"name": "Acme Holding", "status": "ok", "capability_tags": []}),
        encoding="utf-8",
    )
    with patch.object(core_module.llm_module, "call", return_value=_TAGS):
        with pytest.raises(RuntimeError, match="company-id collision"):
            process(_meta(name="Acme B.V."), "body", out_dir=out_dir, write=True)


# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------


def test_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Default model."""
    monkeypatch.delenv("TAGGING_MODEL", raising=False)
    assert llm_module.resolve_model() == "deepseek/deepseek-v4-flash"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Env override."""
    monkeypatch.setenv("TAGGING_MODEL", "anthropic/claude-sonnet-4")
    assert llm_module.resolve_model() == "anthropic/claude-sonnet-4"


def test_prompt_loaded_from_file() -> None:
    expected = (REPO_ROOT / "prompts" / "tagging.md").read_text(encoding="utf-8")
    assert load_prompt() == expected
    assert "capability_tags" in load_prompt()
    assert "isco_code" in load_prompt()
    assert "confidence" in load_prompt()
    assert "251 Software and applications developers and analysts" in load_prompt()
    assert "532 Personal care workers in health services" in load_prompt()
    assert "833 Heavy truck and bus drivers" in load_prompt()


def test_serving_sector_not_staffing_sector_prompt_rule() -> None:
    prompt = load_prompt()
    assert "Serving a sector is not staffing that sector" in prompt
    assert "hospital tools" in prompt
    assert "`251` or `252`" in prompt
    assert "`221`, `222`, `321`, `322`, or `532`" in prompt


def test_ordinary_business_functions_omitted_prompt_rule() -> None:
    prompt = load_prompt()
    assert "Ordinary internal functions do not count by themselves" in prompt
    assert "just because every company has some of it" in prompt
    assert "what the company sells, delivers, or fundamentally operates" in prompt


# ---------------------------------------------------------------------------
# Batch / failure isolation
# ---------------------------------------------------------------------------


def test_one_llm_failure_does_not_abort_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: One LLM failure does not abort batch (concurrent).

    Failure is keyed off the company identity carried in the messages, not call
    order, so the assertion holds under the concurrent pool.
    """
    names = ("Alpha B.V.", "Beta B.V.", "Gamma B.V.")
    for n in names:
        _dossier(tmp_path, n, body=f"{n} builds SaaS for builders.")
    records = [_meta(name=n) for n in names]
    monkeypatch.setenv("TAGGING_CONCURRENCY", "4")

    def _fail_for_beta(messages, **kwargs):  # noqa: ANN001
        if "Beta B.V." in json.dumps(messages):
            raise LLMError("beta fails")
        return _TAGS

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", _fail_for_beta):
        results = list(run(records, out_dir=out_dir, write=True, content_dir=tmp_path))

    by_name = {r["name"]: r for r in results}
    assert by_name["Alpha B.V."]["status"] == "ok"
    assert by_name["Beta B.V."]["status"] == "llm_error"
    assert by_name["Gamma B.V."]["status"] == "ok"
    assert len(list(out_dir.glob("*.json"))) == 3


def test_concurrent_yields_input_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Concurrent processing yields in input order."""
    names = ("Slow Co B.V.", "Fast Co B.V.")
    _dossier(tmp_path, names[0], body="SLOWMARKER builds SaaS for builders.")
    _dossier(tmp_path, names[1], body="FASTMARKER builds SaaS for builders.")
    records = [_meta(name=n) for n in names]
    monkeypatch.setenv("TAGGING_CONCURRENCY", "4")

    def _slow_first(messages, **kwargs):  # noqa: ANN001
        if "SLOWMARKER" in json.dumps(messages):
            time.sleep(0.3)
        return _TAGS

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", _slow_first):
        results = list(run(records, out_dir=out_dir, write=True, content_dir=tmp_path))

    assert [r["name"] for r in results] == list(names)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_end_to_end_writes_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: CLI runs the stage end-to-end."""
    in_dir = tmp_path / "summarization"
    in_dir.mkdir()
    _dossier(in_dir, "Acme B.V.")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(core_module.llm_module, "call", lambda messages, **kw: _TAGS)
    from pipeline.tagging.__main__ import main

    rc = main(["--input", str(in_dir), "--out-dir", str(out_dir)])
    assert rc == 0
    payload = json.loads((out_dir / f"{company_id('Acme B.V.')}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["capability_tags"] == _TAGS


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Scenario: Dry-run writes nothing."""
    in_dir = tmp_path / "summarization"
    in_dir.mkdir()
    _dossier(in_dir, "Acme B.V.")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(core_module.llm_module, "call", lambda messages, **kw: _TAGS)
    from pipeline.tagging.__main__ import main

    rc = main(["--input", str(in_dir), "--out-dir", str(out_dir), "--dry-run"])
    assert rc == 0
    assert not out_dir.exists() or not list(out_dir.glob("*.json"))
    out = capsys.readouterr().out
    assert "capability_tags" in out


def test_offline_skips_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Offline skips LLM."""
    in_dir = tmp_path / "summarization"
    in_dir.mkdir()
    _dossier(in_dir, "Acme B.V.")
    out_dir = tmp_path / "out"

    def _explode(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("LLM must not be called in offline mode")

    monkeypatch.setattr(core_module.llm_module, "call", _explode)
    from pipeline.tagging.__main__ import main

    rc = main(["--input", str(in_dir), "--out-dir", str(out_dir), "--offline"])
    assert rc == 0
    payload = json.loads((out_dir / f"{company_id('Acme B.V.')}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "empty"
    assert payload["model"] is None
    assert payload["capability_tags"] is None
