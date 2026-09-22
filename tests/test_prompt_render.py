import json
from pathlib import Path

import pytest

from phistory.prompt import (
    capture_ports,
    read_records,
    render_archive_markdown,
    render_markdown,
    snapshot_from_body,
    snapshot_from_trace,
)

_REMINDER = "<system-reminder>\nRepository guidance.\n</system-reminder>"

_CLAUDE_BODY = {
    "model": "claude-opus-5",
    "system": [
        {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.278; cc_entrypoint=cli;"},
        {"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}},
    ],
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": _REMINDER}, {"type": "text", "text": "hello"}]},
        {"role": "system", "content": [{"type": "text", "text": "# Environment\nYou have been invoked in CI."}]},
    ],
    "tools": [{"name": "Read", "description": "Read a file.", "input_schema": {"type": "object"}}],
}


def _trace(tmp_path: Path, *bodies: dict, headers: dict | None = None) -> Path:
    path = tmp_path / "trace.jsonl"
    request = {"headers": headers or {}}
    path.write_text(
        "\n".join(json.dumps({"request": {**request, "body": body}}) for body in bodies) + "\n",
        encoding="utf-8",
    )
    return path


def test_every_system_block_survives_with_its_cache_boundary():
    snapshot = snapshot_from_body(_CLAUDE_BODY)
    kinds = [(block.kind, block.cached) for block in snapshot.system]

    assert kinds == [("text", False), ("text", True), ("system message", False)]
    assert "cc_entrypoint=cli" in snapshot.system[0].text


def test_system_messages_between_turns_reach_the_system_section():
    """They are prompt material the SDK surface drops entirely; the archive must keep them."""
    markdown = render_markdown(snapshot_from_body(_CLAUDE_BODY))
    system_section = markdown.split("# Messages", 1)[0]

    assert "## Block 3 · system message" in system_section
    assert "You have been invoked in CI." in system_section


def test_reminder_blocks_stay_separate_from_what_the_user_typed():
    markdown = render_markdown(snapshot_from_body(_CLAUDE_BODY))

    assert "## Message 1 · user · system-reminder" in markdown
    assert "## Message 2 · user · text" in markdown
    assert markdown.index(_REMINDER) < markdown.index("## Message 2")


def test_tool_namespaces_flatten_to_the_names_a_model_can_call():
    body = {
        "instructions": "Do the work.",
        "tools": [{"type": "namespace", "name": "files", "tools": [{"name": "read"}, {"name": "write"}]}],
        "input": [{"type": "additional_tools", "tools": [{"type": "function", "name": "search"}]}],
    }

    assert [tool.name for tool in snapshot_from_body(body).tools] == ["files.read", "files.write", "search"]


def test_builtin_tools_without_a_name_are_kept_under_their_type():
    body = {"instructions": "Do the work.", "tools": [{"type": "web_search", "external_web_access": False}]}

    assert [tool.name for tool in snapshot_from_body(body).tools] == ["web_search"]


def test_routing_envelopes_keep_the_model_they_wrap(tmp_path: Path):
    body = {
        "model": "main-model",
        "request": {"system": "You are an agent.", "messages": [{"role": "user", "content": "hi"}]},
    }
    snapshot = snapshot_from_trace(_trace(tmp_path, body))

    assert snapshot.model == "main-model"
    assert snapshot.system[0].text == "You are an agent."


@pytest.mark.parametrize(
    ("body", "provider", "leading"),
    [
        ({"system": "Be brief.", "messages": [{"role": "user", "content": "hi"}]}, "anthropic", "Be brief."),
        ({"instructions": "Be brief.", "input": [{"role": "user", "content": "hi"}]}, "openai-responses", "Be brief."),
        (
            {"messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]},
            "openai-chat",
            "Be brief.",
        ),
        (
            {"systemInstruction": {"parts": [{"text": "Be brief."}]}, "contents": [{"role": "user", "parts": []}]},
            "gemini",
            "Be brief.",
        ),
    ],
)
def test_each_protocol_puts_its_instructions_in_the_system_section(body, provider, leading):
    snapshot = snapshot_from_body(body)

    assert snapshot.provider == provider
    assert snapshot.system[0].text == leading


def test_only_this_run_s_proxy_port_is_normalized(tmp_path: Path):
    body = {
        "system": "Connect to http://127.0.0.1:9222 for CDP.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    path = _trace(tmp_path, body, headers={"host": "127.0.0.1:44487"})

    assert capture_ports(read_records(path)) == {44487}


def test_rendering_the_same_trace_twice_is_stable(tmp_path: Path):
    path = _trace(tmp_path, _CLAUDE_BODY)

    assert render_archive_markdown(path) == render_archive_markdown(path)


def test_a_trace_without_a_prompt_request_is_an_error(tmp_path: Path):
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps({"request": {"body": {"ping": True}}}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        render_archive_markdown(path)
