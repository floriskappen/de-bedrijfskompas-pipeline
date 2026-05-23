"""Tests for the tagline-extraction stage.

Each scenario in specs/tagline-extraction/spec.md maps to at least one named test
here; the mapping is noted in the change's tasks.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.tagline_extraction import core as core_module
from pipeline.tagline_extraction import frontmatter, llm as llm_module
from pipeline.tagline_extraction.core import load_prompt, process, run
from pipeline.tagline_extraction.llm import LLMError
from pipeline.website_resolution import company_id

REPO_ROOT = Path(__file__).resolve().parents[1]
SMALL_TEST_SET = REPO_ROOT / "test-set" / "companies.json"
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"
DOSSIER_DIR = REPO_ROOT / "data" / "content-summarization"

_TAGLINE = {"en": "A shop that sells widgets to builders."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str = "Acme B.V.", status: str = "ok", website: str = "https://acme.example") -> dict:
    return {"name": name, "website": website, "status": status}


def _proc(meta: dict, body: str = "Acme is paid by builders to supply widgets.", *, offline: bool = False, tagline: dict | None = None) -> dict:
    with patch.object(core_module.llm_module, "call", return_value=tagline or _TAGLINE) as mock:
        result = process(meta, body, out_dir=Path("/nonexistent"), write=False, offline=offline)
    result["_mock_calls"] = mock.call_count
    return result


def _dossier(tmp_path: Path, name: str, *, status: str = "ok", body: str = "Acme supplies widgets.", website: str = "https://acme.example") -> Path:
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
# Frontmatter (deterministic unit)
# ---------------------------------------------------------------------------


def test_frontmatter_parsed() -> None:
    """Scenario: Dossier body is the LLM input (frontmatter split out)."""
    text = '---\nname: "Acme B.V."\nwebsite: "https://acme.example"\nstatus: "ok"\nmodel: null\n---\n\n# Body\n\nReal content.\n'
    fields, body = frontmatter.parse(text)
    assert fields["name"] == "Acme B.V."
    assert fields["website"] == "https://acme.example"
    assert fields["status"] == "ok"
    assert fields["model"] is None
    assert body.startswith("# Body")
    assert "Real content." in body


# ---------------------------------------------------------------------------
# Input, gate, generation, status
# ---------------------------------------------------------------------------


def test_dossier_body_is_llm_input() -> None:
    """Scenario: Dossier body is the LLM input."""
    captured: dict = {}

    def _capture(messages, **kwargs):  # noqa: ANN001
        captured["user"] = messages[-1]["content"]
        return _TAGLINE

    with patch.object(core_module.llm_module, "call", _capture):
        process(_meta(), "Builders pay Acme for widgets.", out_dir=Path("/nonexistent"), write=False)
    assert "Builders pay Acme for widgets." in captured["user"]


def test_non_ok_dossier_cascades() -> None:
    """Scenario: Non-ok dossier cascades."""
    result = _proc(_meta(status="llm_error"), "irrelevant body")
    assert result["status"] == "upstream_failed"
    assert result["tagline"] == {"en": None}
    assert result["_mock_calls"] == 0


def test_ok_dossier_proceeds() -> None:
    """Scenario: Ok dossier proceeds."""
    result = _proc(_meta(status="ok"), "Builders pay Acme for widgets.")
    assert result["status"] == "ok"
    assert result["_mock_calls"] == 1


def test_missing_dossier_upstream_failed(tmp_path: Path) -> None:
    """Scenario: Missing dossier treated as upstream failure."""
    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE) as mock:
        results = list(run([_meta(name="Ghost B.V.")], out_dir=out_dir, write=True, content_dir=tmp_path))
    assert results[0]["status"] == "upstream_failed"
    assert mock.call_count == 0
    assert (out_dir / f"{company_id('Ghost B.V.')}.json").exists()


def test_empty_body_recorded() -> None:
    """Scenario: Empty body recorded."""
    result = _proc(_meta(status="ok"), "   \n  ")
    assert result["status"] == "empty"
    assert result["_mock_calls"] == 0


def test_llm_error_recorded() -> None:
    """Scenario: LLM error recorded."""
    with patch.object(core_module.llm_module, "call", side_effect=LLMError("boom")):
        result = process(_meta(), "real body", out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "llm_error"
    assert result["tagline"] == {"en": None}


def test_one_llm_failure_does_not_abort_batch(tmp_path: Path) -> None:
    """Scenario: One LLM failure does not abort batch."""
    names = ("Alpha B.V.", "Beta B.V.", "Gamma B.V.")
    for n in names:
        _dossier(tmp_path, n)
    records = [_meta(name=n) for n in names]

    call_log: list[int] = []

    def _maybe_fail(messages, **kwargs):  # noqa: ANN001
        call_log.append(1)
        if len(call_log) == 2:
            raise LLMError("second fails")
        return _TAGLINE

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", _maybe_fail):
        results = list(run(records, out_dir=out_dir, write=True, content_dir=tmp_path))

    statuses = [r["status"] for r in results]
    assert statuses.count("ok") == 2
    assert statuses.count("llm_error") == 1
    assert len(list(out_dir.glob("*.json"))) == 3  # llm_error still writes a file


def test_prompt_loaded_from_file() -> None:
    """Scenario: Prompt loaded from versioned file."""
    expected = (REPO_ROOT / "prompts" / "tagline-extraction.md").read_text(encoding="utf-8")
    assert load_prompt() == expected
    assert "who pays" in load_prompt().lower()


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def test_model_override_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Model override honoured."""
    monkeypatch.setenv("TAGLINE_EXTRACTION_MODEL", "test/override-model")
    captured: dict = {}

    def _fake_post(url, **kwargs):  # noqa: ANN001
        captured["model"] = kwargs["json"]["model"]
        return _FakeResp('{"en": "a shop"}')

    with patch.object(llm_module.httpx, "post", _fake_post):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert out == {"en": "a shop"}
    assert captured["model"] == "test/override-model"


def test_malformed_response_is_error() -> None:
    """Scenario: Malformed response is an error (missing en key)."""
    # Missing 'en' entirely → LLMError after retries.
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp('{"nl": "alleen Nederlands"}')):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])
    # Non-JSON garbage → LLMError.
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp("not json at all")):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_malformed_response_missing_en() -> None:
    """Scenario: Malformed response missing en is an llm_error on the record."""
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp('{"other": "value"}')):
        result = process(_meta(), "real body", out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "llm_error"
    assert result["tagline"] == {"en": None}


# ---------------------------------------------------------------------------
# Output record
# ---------------------------------------------------------------------------


def test_successful_record_shape(tmp_path: Path) -> None:
    """Scenario: Successful record shape."""
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE):
        process(_meta(name="Acme B.V."), "Builders pay Acme.", out_dir=tmp_path, write=True)
    rec = json.loads((tmp_path / f"{company_id('Acme B.V.')}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "ok"
    assert rec["model"]  # non-null
    assert rec["tagline"]["en"]
    assert set(rec) == {"name", "website", "status", "model", "tagline"}


def test_tagline_en_only_shape() -> None:
    """Scenario: Tagline has en and no nl key (English-only output)."""
    result = _proc(_meta(status="ok"), "Builders pay Acme for widgets.")
    assert "en" in result["tagline"]
    assert "nl" not in result["tagline"]


def test_null_tagline_on_non_ok() -> None:
    """Scenario: Null tagline on non-ok status has only en key."""
    result = _proc(_meta(status="upstream_failed"), "body")
    assert result["tagline"] == {"en": None}
    assert "nl" not in result["tagline"]


def test_null_taglines_on_non_ok() -> None:
    """Scenario: Null taglines on non-ok status."""
    result = _proc(_meta(status="upstream_failed"), "body")
    assert result["tagline"] == {"en": None}
    assert result["model"] is None


def test_name_collision_refusal(tmp_path: Path) -> None:
    """Scenario: Name-collision refusal."""
    out_path = tmp_path / f"{company_id('Acme B.V.')}.json"
    out_path.write_text(json.dumps({"name": "Acme Holding"}), encoding="utf-8")
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE):
        with pytest.raises(RuntimeError, match="collision"):
            process(_meta(name="Acme B.V."), "body", out_dir=tmp_path, write=True)


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


def test_cli_run_offline(tmp_path: Path) -> None:
    """Scenario: CLI run (offline so it needs no network)."""
    from pipeline.tagline_extraction.__main__ import main

    in_dir = tmp_path / "in"
    in_dir.mkdir()
    for n in ("Alpha B.V.", "Beta B.V."):
        _dossier(in_dir, n)
    out_dir = tmp_path / "out"
    rc = main(["--input", str(in_dir), "--out-dir", str(out_dir), "--offline"])
    assert rc == 0
    assert len(list(out_dir.glob("*.json"))) == 2


def test_dry_run_yields_without_writing(tmp_path: Path) -> None:
    """Scenario: Dry-run yields without writing."""
    _dossier(tmp_path, "Acme B.V.")
    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE):
        results = list(run([_meta(name="Acme B.V.")], out_dir=out_dir, write=False, content_dir=tmp_path))
    assert results[0]["status"] == "ok"
    assert not out_dir.exists() or not list(out_dir.glob("*.json"))


def test_offline_mode_short_circuits_llm() -> None:
    """Scenario: Offline mode short-circuits LLM."""
    result = _proc(_meta(status="ok"), "real content here", offline=True)
    assert result["status"] == "empty"
    assert result["_mock_calls"] == 0


def test_behaviour_parity_across_modes(tmp_path: Path) -> None:
    """Scenario: Behaviour parity across modes (architecture contract)."""
    _dossier(tmp_path, "Acme B.V.")
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE):
        dry = list(run([_meta(name="Acme B.V.")], out_dir=tmp_path / "o1", write=False, content_dir=tmp_path))[0]
    with patch.object(core_module.llm_module, "call", return_value=_TAGLINE):
        wet = list(run([_meta(name="Acme B.V.")], out_dir=tmp_path / "o2", write=True, content_dir=tmp_path))[0]
    assert dry == wet


def test_env_key_not_overridden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Scenario: Exported API key not overridden."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "exported-key")
    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=dotenv-key\n", encoding="utf-8")
    load_dotenv(dotenv_path=env_file, override=False)
    assert os.environ["OPENROUTER_API_KEY"] == "exported-key"


def test_no_scoring_emitted() -> None:
    """Scenario: No scoring emitted (record carries only a tagline)."""
    result = _proc(_meta(status="ok"), "Heavy marketing dossier full of synergy.")
    result.pop("_mock_calls", None)
    assert set(result) == {"name", "website", "status", "model", "tagline"}
    assert "score" not in result and "rating" not in result and "rank" not in result


# ---------------------------------------------------------------------------
# Content-quality eval — gated on OPENROUTER_API_KEY and real dossiers
# ---------------------------------------------------------------------------

_MARKETING_WORDS = (
    "innovative", "leading", "cutting-edge", "world-class", "passionate",
    "best-in-class", "state-of-the-art", "revolutionary",
)


def _require_network() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    if not DOSSIER_DIR.exists():
        pytest.skip("no content-summarization dossiers present")


def _taglines(cid: str) -> dict:
    """Run the real stage for one dossier by id; skip if absent."""
    path = DOSSIER_DIR / f"{cid}.md"
    if not path.exists():
        pytest.skip(f"{cid} dossier not present")
    fields, body = frontmatter.parse(path.read_text(encoding="utf-8"))
    meta = {"name": fields.get("name"), "website": fields.get("website"), "status": fields.get("status")}
    return process(meta, body, out_dir=Path("/nonexistent"), write=False)


@pytest.mark.network
def test_honest_revenue_relationship_comes_through() -> None:
    """Scenario: Honest revenue relationship comes through."""
    _require_network()
    result = _taglines("gravity")
    assert result["status"] == "ok"
    en = result["tagline"]["en"].lower()
    # The honest who-pays-for-what relationship is conveyed via a revenue verb,
    # however the payer is named (companies / organizations / clients / hired by ...).
    assert any(w in en for w in ("pay", "paid", "hire", "charge", "sell")), result["tagline"]["en"]
    # And it does not retreat into the vague marketing fog the stage exists to remove.
    assert "helps companies with" not in en and "digital solutions" not in en, result["tagline"]["en"]


@pytest.mark.network
def test_company_name_omitted() -> None:
    """Scenario: Company name omitted."""
    _require_network()
    for cid, name_word in (("brainial", "brainial"), ("amulet", "amulet")):
        result = _taglines(cid)
        if result["status"] != "ok":
            continue
        assert name_word not in result["tagline"]["en"].lower(), result["tagline"]["en"]


@pytest.mark.network
def test_thin_dossier_gets_caveat() -> None:
    """Scenario: Thin dossier gets a caveat sentence (constructed offering-less dossier)."""
    _require_network()
    thin = (
        "Acme B.V. is a company based in the Netherlands. The website shows a homepage "
        "with a logo and a contact form. No products, services, customers, or business "
        "activities are described anywhere in the source."
    )
    result = process(_meta(name="Acme B.V."), thin, out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "ok"
    low = result["tagline"]["en"].lower()
    caveat = ("however", "no specific", "not ", "no products", "no services", "does not", "unclear", "little", "no information")
    assert any(c in low for c in caveat), result["tagline"]["en"]


@pytest.mark.network
def test_no_marketing_language() -> None:
    """Scenario: No marketing language."""
    _require_network()
    for cid in ("gravity", "brainial"):
        result = _taglines(cid)
        if result["status"] != "ok":
            continue
        low = result["tagline"]["en"].lower()
        assert not any(w in low for w in _MARKETING_WORDS), f"{cid}: {low}"


@pytest.mark.network
def test_end_to_end_corpus() -> None:
    """Real run over the test-set dossiers; every company yields a record with a status."""
    _require_network()
    for path in (SMALL_TEST_SET, MEDIUM_TEST_SET):
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        results = list(run(records, out_dir=Path("/nonexistent"), write=False, content_dir=DOSSIER_DIR))
        assert len(results) == len(records)
        assert all("status" in r for r in results)
