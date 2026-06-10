"""Tests for the website-resolution stage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tldextract

from pipeline.website_resolution import company_id, resolve, run
from pipeline.website_resolution import core as core_module

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SET = REPO_ROOT / "test-set" / "companies.json"

# Shared name->company_id vectors. The scraper repo carries a byte-identical
# copy and asserts its own company_id() against it, so both implementations
# stay aligned. See scraper/website_resolution/company_id.py.
_COMPANY_ID_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "company_id_vectors.json").read_text(
        encoding="utf-8"
    )
)


# ---------------------------------------------------------------------------
# Offline tests: company_id slugification rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [(vector["name"], vector["company_id"]) for vector in _COMPANY_ID_VECTORS],
)
def test_company_id_strips_entity_suffixes(name: str, expected: str) -> None:
    assert company_id(name) == expected


def test_company_id_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        company_id("")
    with pytest.raises(ValueError):
        company_id("   ")


# ---------------------------------------------------------------------------
# Offline tests: resolve() behavior with the search backend mocked
# ---------------------------------------------------------------------------


def test_resolve_skips_when_website_present(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []

    def fake_search(query: str) -> str | None:
        called.append(query)
        return None

    monkeypatch.setattr(core_module._search, "search", fake_search)

    result = resolve({"name": "Acme B.V.", "website": "https://acme.example"})

    assert result == {"name": "Acme B.V.", "website": "https://acme.example"}
    assert called == []


def test_resolve_succeeds_via_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_module._search,
        "search",
        lambda q: "https://acme.example",
    )

    result = resolve({"name": "Acme B.V."})

    assert result == {"name": "Acme B.V.", "website": "https://acme.example"}


def test_resolve_no_results_produces_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: None)

    result = resolve({"name": "Nonexistent X"})

    assert result["website"] is None
    assert result["status"] == "failed"
    assert "no search results" in result["error"]


def test_resolve_search_exception_produces_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(query: str) -> str | None:
        raise RuntimeError("backend down")

    monkeypatch.setattr(core_module._search, "search", boom)

    result = resolve({"name": "Acme B.V."})

    assert result["status"] == "failed"
    assert "backend down" in result["error"]


def test_resolve_missing_name_fails_without_searching(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(core_module._search, "search", lambda q: called.append(q) or None)

    result = resolve({"website": "https://acme.example"})

    assert result["status"] == "failed"
    assert "missing or empty name" in result["error"]
    assert called == []


def test_resolve_preserves_extra_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: "https://acme.example")

    result = resolve({"name": "Acme B.V.", "source": "hackernews-2026-01"})

    assert result["source"] == "hackernews-2026-01"
    assert result["website"] == "https://acme.example"


# ---------------------------------------------------------------------------
# Offline tests: run() batch + collision detection
# ---------------------------------------------------------------------------


def test_run_writes_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: f"https://{q.lower()}.example")
    monkeypatch.setattr(core_module, "SLEEP_BETWEEN_SEARCHES_SECONDS", 0.0)

    records = [{"name": "Acme B.V."}, {"name": "FooBar N.V."}]
    list(run(records, write=True, out_dir=tmp_path))

    assert (tmp_path / "acme.json").exists()
    assert (tmp_path / "foobar.json").exists()

    payload = json.loads((tmp_path / "acme.json").read_text(encoding="utf-8"))
    assert payload["name"] == "Acme B.V."
    assert payload["website"].startswith("https://")


def test_run_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: "https://acme.example")
    monkeypatch.setattr(core_module, "SLEEP_BETWEEN_SEARCHES_SECONDS", 0.0)

    results = list(run([{"name": "Acme B.V."}], write=False, out_dir=tmp_path))

    assert results[0]["website"] == "https://acme.example"
    assert list(tmp_path.iterdir()) == []


def test_run_collision_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: "https://acme.example")
    monkeypatch.setattr(core_module, "SLEEP_BETWEEN_SEARCHES_SECONDS", 0.0)

    # Pre-seed an existing file with a *different* name that slugifies to the
    # same id.
    (tmp_path / "acme.json").write_text(
        json.dumps({"name": "Acme Industries B.V.", "website": "https://other.example"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="collision"):
        list(run([{"name": "Acme B.V."}], write=True, out_dir=tmp_path))


def test_run_overwrite_same_name_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(core_module._search, "search", lambda q: "https://acme.example")
    monkeypatch.setattr(core_module, "SLEEP_BETWEEN_SEARCHES_SECONDS", 0.0)

    (tmp_path / "acme.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://old.example"}),
        encoding="utf-8",
    )

    list(run([{"name": "Acme B.V."}], write=True, out_dir=tmp_path))

    payload = json.loads((tmp_path / "acme.json").read_text(encoding="utf-8"))
    assert payload["website"] == "https://acme.example"


# ---------------------------------------------------------------------------
# Network test: the canary against the real test-set + real DDGS
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_resolves_test_set_against_known_domains() -> None:
    raw = json.loads(TEST_SET.read_text(encoding="utf-8"))

    stripped = [{"name": entry["name"]} for entry in raw]
    expected_domains = {
        entry["name"]: tldextract.extract(entry["website"]).top_domain_under_public_suffix
        for entry in raw
    }

    results = list(run(stripped, write=False, out_dir=Path()))

    failures: list[str] = []
    for entry, result in zip(raw, results):
        url = result.get("website")
        if not url:
            failures.append(f"{entry['name']}: no website resolved ({result.get('error')})")
            continue
        got = tldextract.extract(url).top_domain_under_public_suffix
        if got != expected_domains[entry["name"]]:
            failures.append(
                f"{entry['name']}: expected {expected_domains[entry['name']]!r}, got {got!r} (url={url})"
            )

    assert not failures, "\n".join(failures)
