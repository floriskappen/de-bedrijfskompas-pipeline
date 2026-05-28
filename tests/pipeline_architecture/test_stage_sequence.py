"""Tests for the stage sequence and dependencies in the pipeline architecture."""

from __future__ import annotations

import inspect
from pathlib import Path

from pipeline import run as orch
from pipeline.translation.llm import TRANSLATION_TARGETS


def test_tagging_is_wave_4d() -> None:
    """Scenario: Stage Sequence requirement listing tagging at 4d.

    Specifically, check that:
    - 'tagging' is in the stages list.
    - It is positioned after 'global-scoring' (4c) and before 'translation' (5).
    """
    stage_names = [name for name, _ in orch.STAGES]
    assert "tagging" in stage_names

    tagging_idx = stage_names.index("tagging")
    scoring_idx = stage_names.index("global-scoring")
    translation_idx = stage_names.index("translation")

    assert scoring_idx < tagging_idx
    assert tagging_idx < translation_idx


def test_tagging_depends_only_on_content_summarization() -> None:
    """Scenario: Dossier-derived analytic stages depend only on content-summarization.

    Verify that the driver for 'tagging' is reading only from 'content-summarization'
    and writing to 'tagging'.
    """
    # We inspect the implementation of _drive_tagging in pipeline.run to ensure
    # it only resolves content_dir as content-summarization.
    # Alternatively, we can inspect the source code of _drive_tagging.
    source = inspect.getsource(orch._drive_tagging)
    assert 'data_root / "content-summarization"' in source
    assert 'data_root / "tagging"' in source
    assert "content-collection" not in source
    assert "fact-extraction" not in source
    assert "geocoding" not in source


def test_tagging_is_not_a_translation_input() -> None:
    """Scenario: Translation fans in over text-bearing dossier-derived analytic stages only.

    Verify that 'tagging' is not listed as a source stage or target for translation.
    """
    for stage_id, _ in TRANSLATION_TARGETS:
        assert stage_id != "tagging"

    # Also verify that the translation driver in pipeline.run doesn't register 'tagging'
    # as a source directory.
    source = inspect.getsource(orch._drive_translation)
    assert 'tagging' not in source
