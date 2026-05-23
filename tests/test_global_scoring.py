"""Tests for the global-scoring stage.

Each scenario in specs/global-scoring/spec.md maps to at least one named test
here; the mapping is noted in the change's tasks.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.global_scoring import core as core_module
from pipeline.global_scoring import frontmatter, llm as llm_module
from pipeline.global_scoring.core import load_prompt, process, run
from pipeline.global_scoring.llm import AXES, LLMError
from pipeline.website_resolution import company_id

REPO_ROOT = Path(__file__).resolve().parents[1]
SMALL_TEST_SET = REPO_ROOT / "test-set" / "companies.json"
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"
DOSSIER_DIR = REPO_ROOT / "data" / "content-summarization"


def _axis(score: int | None = 60, evidence: str = "well_evidenced") -> dict:
    return {"score": score, "evidence": evidence, "reason": {"en": "Because reasons.", "nl": "Vanwege redenen."}}


def _scores(**overrides: dict) -> dict:
    """A full, valid five-axis object; pass per-axis overrides by keyword."""
    base = {a: _axis() for a in AXES}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str = "Acme B.V.", status: str = "ok", website: str = "https://acme.example") -> dict:
    return {"name": name, "website": website, "status": status}


def _proc(meta: dict, body: str = "Acme is paid by builders to supply widgets.", *, offline: bool = False, scores: dict | None = None) -> dict:
    with patch.object(core_module.llm_module, "call", return_value=scores or _scores()) as mock:
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
        return _scores()

    with patch.object(core_module.llm_module, "call", _capture):
        process(_meta(), "Builders pay Acme for widgets.", out_dir=Path("/nonexistent"), write=False)
    assert "Builders pay Acme for widgets." in captured["user"]


def test_non_ok_dossier_cascades() -> None:
    """Scenario: Non-ok dossier cascades."""
    result = _proc(_meta(status="llm_error"), "irrelevant body")
    assert result["status"] == "upstream_failed"
    assert result["scores"] is None
    assert result["_mock_calls"] == 0


def test_ok_dossier_proceeds() -> None:
    """Scenario: Ok dossier proceeds."""
    result = _proc(_meta(status="ok"), "Builders pay Acme for widgets.")
    assert result["status"] == "ok"
    assert result["_mock_calls"] == 1


def test_missing_dossier_upstream_failed(tmp_path: Path) -> None:
    """Scenario: Missing dossier treated as upstream failure."""
    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value=_scores()) as mock:
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
    assert result["scores"] is None


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
        return _scores()

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", _maybe_fail):
        results = list(run(records, out_dir=out_dir, write=True, content_dir=tmp_path))

    statuses = [r["status"] for r in results]
    assert statuses.count("ok") == 2
    assert statuses.count("llm_error") == 1
    assert len(list(out_dir.glob("*.json"))) == 3  # llm_error still writes a file


def test_prompt_loaded_from_file() -> None:
    """Scenario: Prompt loaded from versioned file."""
    expected = (REPO_ROOT / "prompts" / "global-scoring.md").read_text(encoding="utf-8")
    assert load_prompt() == expected
    assert "substance" in load_prompt().lower()


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _ok_payload() -> str:
    axes = ", ".join(
        f'"{a}": {{"score": 60, "evidence": "well_evidenced", "reason": {{"en": "ok", "nl": "oké"}}}}'
        for a in AXES
    )
    return "{" + axes + "}"


def test_model_override_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: Model override honoured."""
    monkeypatch.setenv("GLOBAL_SCORING_MODEL", "test/override-model")
    captured: dict = {}

    def _fake_post(url, **kwargs):  # noqa: ANN001
        captured["model"] = kwargs["json"]["model"]
        return _FakeResp(_ok_payload())

    with patch.object(llm_module.httpx, "post", _fake_post):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert set(out) == set(AXES)
    assert captured["model"] == "test/override-model"


def test_malformed_response_is_error() -> None:
    """Scenario: Malformed response is an error."""
    # Missing an axis → LLMError after retries.
    partial = '{"substance": {"score": 50, "evidence": "partial", "reason": {"en": "x", "nl": "x"}}}'
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp(partial)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])
    # Invalid evidence value → LLMError.
    bad_ev = _ok_payload().replace("well_evidenced", "totally_sure", 1)
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp(bad_ev)):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])
    # Non-JSON garbage → LLMError.
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp("not json at all")):
        with pytest.raises(LLMError):
            llm_module.call([{"role": "user", "content": "hi"}])


def test_inconsistent_score_evidence_normalized() -> None:
    """Scenario: Inconsistent score and evidence are normalized, not rejected."""
    # A numeric score paired with no_signal: keep the score, downgrade to partial.
    healed = _ok_payload().replace(
        '"power": {"score": 60, "evidence": "well_evidenced"',
        '"power": {"score": 60, "evidence": "no_signal"',
        1,
    )
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp(healed)):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert out["power"]["score"] == 60 and out["power"]["evidence"] == "partial"
    # A null score paired with a numeric evidence level: force no_signal.
    healed2 = _ok_payload().replace(
        '"power": {"score": 60, "evidence": "well_evidenced"',
        '"power": {"score": null, "evidence": "partial"',
        1,
    )
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp(healed2)):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert out["power"]["score"] is None and out["power"]["evidence"] == "no_signal"


def test_fence_and_wrapper_tolerated() -> None:
    """Code-fenced and {"scores": {...}}-wrapped responses still parse."""
    fenced = "```json\n{\"scores\": " + _ok_payload() + "}\n```"
    with patch.object(llm_module.httpx, "post", lambda url, **kw: _FakeResp(fenced)):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert set(out) == set(AXES)


# ---------------------------------------------------------------------------
# Per-axis entry shape (mocked-response unit)
# ---------------------------------------------------------------------------


def test_evidenced_axis_has_numeric_score() -> None:
    """Scenario: Evidenced axis carries a numeric score."""
    result = _proc(_meta(), scores=_scores(substance=_axis(80, "well_evidenced")))
    axis = result["scores"]["substance"]
    assert isinstance(axis["score"], int) and 0 <= axis["score"] <= 100
    assert axis["reason"]["en"] and axis["reason"]["nl"]


def test_no_signal_axis_has_null_score() -> None:
    """Scenario: No-signal axis carries a null score."""
    result = _proc(_meta(), scores=_scores(power=_axis(None, "no_signal")))
    axis = result["scores"]["power"]
    assert axis["score"] is None
    assert axis["evidence"] == "no_signal"
    assert axis["reason"]["en"] and axis["reason"]["nl"]


# ---------------------------------------------------------------------------
# Output record
# ---------------------------------------------------------------------------


def test_successful_record_shape(tmp_path: Path) -> None:
    """Scenario: Successful record shape."""
    with patch.object(core_module.llm_module, "call", return_value=_scores()):
        process(_meta(name="Acme B.V."), "Builders pay Acme.", out_dir=tmp_path, write=True)
    rec = json.loads((tmp_path / f"{company_id('Acme B.V.')}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "ok"
    assert rec["model"]  # non-null
    assert set(rec) == {"name", "website", "status", "model", "scores"}


def test_all_five_axes_present() -> None:
    """Scenario: All five axes present."""
    result = _proc(_meta(status="ok"))
    assert set(result["scores"]) == set(AXES)


def test_no_composite_score() -> None:
    """Scenario: No composite score."""
    result = _proc(_meta(status="ok"))
    result.pop("_mock_calls", None)
    assert set(result) == {"name", "website", "status", "model", "scores"}
    for key in ("overall", "total", "average", "composite", "weighted", "score"):
        assert key not in result


def test_null_scores_on_non_ok() -> None:
    """Scenario: Null scores on non-ok status."""
    result = _proc(_meta(status="upstream_failed"), "body")
    assert result["scores"] is None
    assert result["model"] is None


def test_name_collision_refusal(tmp_path: Path) -> None:
    """Scenario: Name-collision refusal."""
    out_path = tmp_path / f"{company_id('Acme B.V.')}.json"
    out_path.write_text(json.dumps({"name": "Acme Holding"}), encoding="utf-8")
    with patch.object(core_module.llm_module, "call", return_value=_scores()):
        with pytest.raises(RuntimeError, match="collision"):
            process(_meta(name="Acme B.V."), "body", out_dir=tmp_path, write=True)


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


def test_cli_run_offline(tmp_path: Path) -> None:
    """Scenario: CLI run (offline so it needs no network)."""
    from pipeline.global_scoring.__main__ import main

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
    with patch.object(core_module.llm_module, "call", return_value=_scores()):
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
    with patch.object(core_module.llm_module, "call", return_value=_scores()):
        dry = list(run([_meta(name="Acme B.V.")], out_dir=tmp_path / "o1", write=False, content_dir=tmp_path))[0]
    with patch.object(core_module.llm_module, "call", return_value=_scores()):
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


def test_only_five_axis_profile_emitted() -> None:
    """Scenario: Only the five-axis profile emitted."""
    result = _proc(_meta(status="ok"), "Heavy marketing dossier full of synergy.")
    result.pop("_mock_calls", None)
    assert set(result) == {"name", "website", "status", "model", "scores"}
    assert "tagline" not in result and "tags" not in result and "match" not in result


# ---------------------------------------------------------------------------
# Content-quality eval — gated on OPENROUTER_API_KEY and real dossiers
# ---------------------------------------------------------------------------


def _require_network() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    if not DOSSIER_DIR.exists():
        pytest.skip("no content-summarization dossiers present")


def _score(cid: str) -> dict:
    """Run the real stage for one dossier by id; skip if absent."""
    path = DOSSIER_DIR / f"{cid}.md"
    if not path.exists():
        pytest.skip(f"{cid} dossier not present")
    fields, body = frontmatter.parse(path.read_text(encoding="utf-8"))
    meta = {"name": fields.get("name"), "website": fields.get("website"), "status": fields.get("status")}
    return process(meta, body, out_dir=Path("/nonexistent"), write=False)


@pytest.mark.network
def test_power_silence_is_unknown() -> None:
    """Scenario: Power silence is unknown, not penalised."""
    _require_network()
    # A dossier with a clear activity but no ownership/governance detail.
    body = (
        "The company is a digital agency that builds websites and apps for business "
        "clients who pay it on a project basis. It lists services and a few case studies. "
        "Nothing is said about who owns the company, how it is governed, or how decisions "
        "or pay are shared internally."
    )
    result = process(_meta(name="Acme B.V."), body, out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "ok"
    power = result["scores"]["power"]
    assert power["evidence"] == "no_signal" and power["score"] is None, power


@pytest.mark.network
def test_substance_vagueness_counts_against() -> None:
    """Scenario: Substance vagueness counts against."""
    _require_network()
    body = (
        "The company describes itself as a partner that empowers organisations to unlock "
        "their potential and drive transformation. It never states what it actually sells, "
        "who its customers are, or how it makes money."
    )
    result = process(_meta(name="Vague B.V."), body, out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "ok"
    substance = result["scores"]["substance"]
    assert substance["evidence"] != "no_signal", substance
    assert substance["score"] is not None and substance["score"] <= 40, substance


@pytest.mark.network
def test_reason_explains_rather_than_quotes() -> None:
    """Scenario: Reason explains rather than quotes."""
    _require_network()
    result = _score("gravity")
    if result["status"] != "ok":
        pytest.skip("gravity not scorable")
    for axis in result["scores"].values():
        assert '"' not in axis["reason"]["en"], axis["reason"]["en"]


@pytest.mark.network
def test_bilingual_parity() -> None:
    """Scenario: Bilingual parity."""
    _require_network()
    result = _score("land-life-company")
    if result["status"] != "ok":
        pytest.skip("land-life-company not scorable")
    for name, axis in result["scores"].items():
        en, nl = axis["reason"]["en"], axis["reason"]["nl"]
        assert en and nl, name
        assert en != nl, name  # an actual Dutch rendering, not a copy


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
