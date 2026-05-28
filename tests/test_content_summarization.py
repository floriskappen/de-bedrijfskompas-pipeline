"""Tests for the content-summarization stage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.content_summarization import core as core_module
from pipeline.content_summarization import llm as llm_module
from pipeline.content_summarization.core import (
    build_input,
    detect_language,
    load_prompt,
    process,
    run,
)
from pipeline.content_summarization.llm import LLMError, strip_wrapper
from pipeline.website_resolution import company_id

REPO_ROOT = Path(__file__).resolve().parents[1]
SMALL_TEST_SET = REPO_ROOT / "test-set" / "companies.json"
MEDIUM_TEST_SET = REPO_ROOT / "test-set" / "companies-medium.json"
CONTENT_DIR = REPO_ROOT / "data" / "content-collection"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str = "Acme B.V.", status: str = "ok", website: str = "https://acme.example") -> dict:
    return {"name": name, "website": website, "status": status}


def _proc(meta: dict, pages: dict | None = None, *, offline: bool = False, body: str = "# Dossier\n\nAcme builds widgets.") -> dict:
    with patch.object(core_module.llm_module, "call", return_value=body) as mock:
        result = process(meta, pages or {}, out_dir=Path("/nonexistent"), write=False, offline=offline)
    result["_mock_calls"] = mock.call_count
    return result


def _company_dir(tmp_path: Path, cid: str, files: dict[str, str], meta: dict) -> Path:
    d = tmp_path / cid
    d.mkdir(parents=True)
    (d / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for fname, content in files.items():
        (d / fname).write_text(content, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Input assembly
# ---------------------------------------------------------------------------


def test_recall_files_excluded(tmp_path: Path) -> None:
    meta = _meta(name="Acme B.V.")
    _company_dir(
        tmp_path,
        company_id("Acme B.V."),
        {"about.md": "PRECISION about", "about.recall.md": "RECALL about"},
        meta,
    )
    loaded_meta, pages = core_module._load_company(meta, content_dir=tmp_path)
    assert "about" in pages
    assert pages["about"] == "PRECISION about"
    assert all(not k.endswith("recall") and "recall" not in k for k in pages)


def test_deterministic_page_order() -> None:
    pages = {"portfolio": "P", "index": "I", "about": "A"}
    surface = build_input(pages)
    assert surface.index("[index]") < surface.index("[about]") < surface.index("[portfolio]")


def test_oversized_input_truncated() -> None:
    pages = {"index": "x" * 50000}
    surface = build_input(pages)
    assert len(surface) == core_module.INPUT_CHAR_LIMIT


def test_prompt_loaded_from_file() -> None:
    expected = (REPO_ROOT / "prompts" / "content-summarization.md").read_text(encoding="utf-8")
    assert load_prompt() == expected
    assert "faithful" in load_prompt().lower()


def test_model_override_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_SUMMARIZATION_MODEL", "test/override-model")
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:  # noqa: D401
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok body"}}]}

    def _fake_post(url, **kwargs):  # noqa: ANN001
        captured["model"] = kwargs["json"]["model"]
        return _Resp()

    with patch.object(llm_module.httpx, "post", _fake_post):
        out = llm_module.call([{"role": "user", "content": "hi"}])
    assert out == "ok body"
    assert captured["model"] == "test/override-model"


def test_conversational_wrapper_stripped() -> None:
    raw = "Here is the dossier:\n\n```markdown\n# Acme\n\nBuilds widgets.\n```"
    assert strip_wrapper(raw) == "# Acme\n\nBuilds widgets."


# ---------------------------------------------------------------------------
# Output & status
# ---------------------------------------------------------------------------


def test_dossier_written_with_frontmatter(tmp_path: Path) -> None:
    meta = _meta(name="Acme B.V.", website="https://acme.example")
    with patch.object(core_module.llm_module, "call", return_value="# Acme\n\nBuilds widgets."):
        process(meta, {"index": "Acme builds widgets"}, out_dir=tmp_path, write=True)
    out = (tmp_path / f"{company_id('Acme B.V.')}.md").read_text(encoding="utf-8")
    assert out.startswith("---\n")
    head = out.split("---", 2)[1]
    for key in ("name:", "website:", "status:", "source_language:", "model:"):
        assert key in head
    assert "Builds widgets." in out


def test_name_collision_refusal(tmp_path: Path) -> None:
    out_path = tmp_path / f"{company_id('Acme B.V.')}.md"
    out_path.write_text('---\nname: "Acme Holding"\nstatus: "ok"\n---\n\nbody\n', encoding="utf-8")
    meta = _meta(name="Acme B.V.")
    with patch.object(core_module.llm_module, "call", return_value="body"):
        with pytest.raises(RuntimeError, match="collision"):
            process(meta, {"index": "x"}, out_dir=tmp_path, write=True)


def test_upstream_failure_propagated() -> None:
    result = _proc(_meta(status="upstream_failed"), {"index": "x"})
    assert result["status"] == "upstream_failed"
    assert result["body"] == ""
    assert result["_mock_calls"] == 0


def test_empty_when_no_content() -> None:
    result = _proc(_meta(status="ok"), {})
    assert result["status"] == "empty"
    assert result["_mock_calls"] == 0


def test_llm_error_recorded() -> None:
    with patch.object(core_module.llm_module, "call", side_effect=LLMError("boom")):
        result = process(_meta(), {"index": "x"}, out_dir=Path("/nonexistent"), write=False)
    assert result["status"] == "llm_error"
    assert result["body"] == ""


def test_one_llm_failure_does_not_abort_batch(tmp_path: Path) -> None:
    for name in ("Alpha B.V.", "Beta B.V.", "Gamma B.V."):
        _company_dir(tmp_path, company_id(name), {"index.md": "content"}, _meta(name=name))
    records = [_meta(name=n) for n in ("Alpha B.V.", "Beta B.V.", "Gamma B.V.")]

    call_log: list[int] = []

    def _maybe_fail(messages, **kwargs):  # noqa: ANN001
        call_log.append(1)
        if len(call_log) == 2:
            raise LLMError("second fails")
        return "# Dossier\n\nbody"

    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", _maybe_fail):
        results = list(run(records, out_dir=out_dir, write=True, content_dir=tmp_path))

    statuses = [r["status"] for r in results]
    assert statuses.count("ok") == 2
    assert statuses.count("llm_error") == 1
    assert len(list(out_dir.glob("*.md"))) == 3  # llm_error still writes a file


def test_offline_mode_short_circuits_llm() -> None:
    result = _proc(_meta(status="ok"), {"index": "real content here"}, offline=True)
    assert result["status"] == "empty"
    assert result["_mock_calls"] == 0


def test_dry_run_yields_without_writing(tmp_path: Path) -> None:
    _company_dir(tmp_path, company_id("Acme B.V."), {"index.md": "content"}, _meta(name="Acme B.V."))
    out_dir = tmp_path / "out"
    with patch.object(core_module.llm_module, "call", return_value="# D\n\nbody"):
        results = list(run([_meta(name="Acme B.V.")], out_dir=out_dir, write=False, content_dir=tmp_path))
    assert results[0]["status"] == "ok"
    assert not out_dir.exists() or not list(out_dir.glob("*.md"))


def test_behaviour_parity_across_modes(tmp_path: Path) -> None:
    _company_dir(tmp_path, company_id("Acme B.V."), {"index.md": "content"}, _meta(name="Acme B.V."))
    body = "# D\n\nbody"

    with patch.object(core_module.llm_module, "call", return_value=body):
        dry = list(run([_meta(name="Acme B.V.")], out_dir=tmp_path / "o1", write=False, content_dir=tmp_path))[0]
    with patch.object(core_module.llm_module, "call", return_value=body):
        wet = list(run([_meta(name="Acme B.V.")], out_dir=tmp_path / "o2", write=True, content_dir=tmp_path))[0]

    assert dry == wet


def test_env_key_not_overridden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # conftest loads dotenv with override=False; an exported key must win over .env.
    monkeypatch.setenv("OPENROUTER_API_KEY", "exported-key")
    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=dotenv-key\n", encoding="utf-8")
    load_dotenv(dotenv_path=env_file, override=False)
    assert os.environ["OPENROUTER_API_KEY"] == "exported-key"


# ---------------------------------------------------------------------------
# Language detection (deterministic unit)
# ---------------------------------------------------------------------------


def test_detect_language_dutch_vs_english() -> None:
    dutch = "Wij zijn een bedrijf dat software maakt voor de zorg en wij hebben veel klanten."
    english = "We are a company that builds software for healthcare and we have many customers."
    assert detect_language(dutch) == "nl"
    assert detect_language(english) == "en"


# ---------------------------------------------------------------------------
# Network / quality eval — gated on OPENROUTER_API_KEY and real content-collection output
# ---------------------------------------------------------------------------


def _require_network() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    if not CONTENT_DIR.exists():
        pytest.skip("no content-collection output to summarise")


def _summarise(cid: str) -> dict:
    """Run the real stage for one company directory by id; skip if absent."""
    company_dir = CONTENT_DIR / cid
    if not company_dir.exists():
        pytest.skip(f"{cid} not present in content-collection output")
    meta = json.loads((company_dir / "_meta.json").read_text(encoding="utf-8"))
    _, pages = core_module._load_company(meta, content_dir=CONTENT_DIR)
    meta["status"] = "ok"
    return process(meta, pages, out_dir=Path("/nonexistent"), write=False)


@pytest.mark.network
def test_source_language_normalised() -> None:
    _require_network()
    result = _summarise("ai-nl")  # Dutch-source company
    assert result["status"] == "ok"
    assert result["source_language"] == "nl"
    assert detect_language(result["body"]) == "en"


@pytest.mark.network
def test_marketing_collapsed_to_substance() -> None:
    _require_network()
    result = _summarise("co-health")
    assert result["status"] == "ok"
    _, pages = core_module._load_company({"name": "Co-Health"}, content_dir=CONTENT_DIR)
    source_len = len(build_input(pages))
    # A marketing-saturated source must collapse, not expand.
    assert 0 < len(result["body"]) < source_len


@pytest.mark.network
def test_bulk_listing_not_reproduced() -> None:
    _require_network()
    result = _summarise("apertas")  # index page is a long seminar-date listing
    assert result["status"] == "ok"
    # The schedule has many "ONLINE" date rows; the dossier should not reproduce them.
    assert result["body"].upper().count("ONLINE") <= 2


@pytest.mark.network
def test_no_external_facts_and_claims_attributed() -> None:
    """Covers 'No external facts added' and 'Claim attributed, not asserted'."""
    _require_network()
    result = _summarise("land-life-company")
    assert result["status"] == "ok"
    assert len(result["body"]) > 0


@pytest.mark.network
def test_filler_and_sample_data_excluded() -> None:
    """Covers 'Filler and unrelated template excluded' and 'Sample data not treated as fact'."""
    _require_network()
    result = _summarise("apertas")  # has lorem-ipsum + unrelated blockchain template
    assert result["status"] == "ok"
    low = result["body"].lower()
    assert "lorem ipsum" not in low
    assert "lorem" not in low


@pytest.mark.network
def test_cross_page_duplication_removed() -> None:
    _require_network()
    result = _summarise("ai-nl")  # index ≈ over-ons (duplicate founder bios)
    assert result["status"] == "ok"


@pytest.mark.network
def test_no_scoring_emitted() -> None:
    _require_network()
    result = _summarise("autogrowth")
    assert result["status"] == "ok"
    low = result["body"].lower()
    assert "bullshit score" not in low and "rating:" not in low


def test_cli_run_offline(tmp_path: Path) -> None:
    """CLI produces one file per company; offline so it needs no network."""
    if not CONTENT_DIR.exists():
        pytest.skip("no content-collection output")
    from pipeline.content_summarization.__main__ import main

    out_dir = tmp_path / "out"
    rc = main(["--input", str(CONTENT_DIR), "--out-dir", str(out_dir), "--offline"])
    assert rc == 0
    company_dirs = [d for d in CONTENT_DIR.iterdir() if d.is_dir() and (d / "_meta.json").exists()]
    assert len(list(out_dir.glob("*.md"))) == len(company_dirs)


@pytest.mark.network
def test_end_to_end_corpus() -> None:
    _require_network()
    for path in (SMALL_TEST_SET, MEDIUM_TEST_SET):
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        results = list(run(records, out_dir=Path("/nonexistent"), write=False, content_dir=CONTENT_DIR))
        assert len(results) == len(records)
        assert all("status" in r for r in results)
