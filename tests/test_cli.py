import json

import pytest

from phistory.cli import _parse_archived_agent_ids


def test_translation_agent_filter_accepts_manual_archive_categories(tmp_path):
    capture = tmp_path / "captures/claude-tag/2026-09-22/variants/default"
    capture.mkdir(parents=True)
    (capture / "prompt.md").write_text("# Prompt\n", encoding="utf-8")
    (capture / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    (capture / "meta.json").write_text(
        json.dumps({"agent_id": "claude-tag", "agent": "Claude Tag", "version": "2026-09-22"}),
        encoding="utf-8",
    )

    assert _parse_archived_agent_ids(tmp_path / "captures", "claude-tag") == ["claude-tag"]
    with pytest.raises(ValueError, match="unknown archived agent"):
        _parse_archived_agent_ids(tmp_path / "captures", "typo")
