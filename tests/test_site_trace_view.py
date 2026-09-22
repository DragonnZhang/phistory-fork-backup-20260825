"""Run the viewer's own trace parser so prompt structure is verified, not assumed."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from phistory.site import _HTML

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the viewer script")

_EXPORTS = ("normalizeTraceRecord", "contentBlocks", "blockLabel")
_RECORD = {
    "request": {
        "path": "/v1/messages",
        "headers": {"host": "127.0.0.1:1234"},
        "body": {
            "model": "claude-opus-5",
            "system": [
                {"type": "text", "text": "x-anthropic-billing-header: cc_entrypoint=cli;"},
                {"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}},
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "<system-reminder>\nGuidance.\n</system-reminder>"},
                        {"type": "text", "text": "hello"},
                    ],
                },
                {"role": "system", "content": [{"type": "text", "text": "# Environment\nInvoked in CI."}]},
            ],
            "tools": [{"name": "Read", "description": "Read a file.", "input_schema": {"type": "object"}}],
        },
    },
    "response": {"status": 200},
}


def _detail() -> dict:
    script = max(re.findall(r"<script>(.*?)</script>", _HTML, re.S), key=len)
    # Top-level function declarations are pure; evaluating them needs no DOM.
    definitions = "\n\n".join(re.findall(r"^(?:async )?function [\s\S]*?^}", script, re.M))
    program = (
        definitions
        + f"\n;const api = {{ {', '.join(_EXPORTS)} }};"
        + "\nconst record = JSON.parse(process.argv[2]);"
        + "\nconsole.log(JSON.stringify(api.normalizeTraceRecord(record, 0, 1)));"
    )
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "viewer.js"
        script_path.write_text(program, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path), json.dumps(_RECORD)], capture_output=True, text=True, timeout=120
        )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def test_viewer_labels_cache_boundaries_and_interleaved_system_messages():
    detail = _detail()
    system = [(block["label"], block["text"][:24]) for block in detail["systemBlocks"]]

    assert system[0][0] == ""
    assert system[1][0] == "cached"
    assert system[2][0] == "system message"
    assert "Invoked in CI." in detail["systemBlocks"][2]["text"]


def test_viewer_keeps_reminder_blocks_apart_from_the_typed_message():
    detail = _detail()
    messages = [(message["role"], message["label"], message["text"]) for message in detail["messages"]]

    assert [(role, label) for role, label, _ in messages] == [("user", "system-reminder"), ("user", "")]
    assert messages[1][2] == "hello"
