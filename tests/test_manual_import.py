import copy
import hashlib
import json

from scripts.import_manual_trace import import_trace


def trace_record(*, suffix: str, extra_history: bool = False) -> dict:
    reminder = (
        "<system-reminder>\n"
        "Memory path: /tmp/claude/memory/team/channel/\n"
        "The following is the memory index at `team/channel/MEMORY.md`, fetched from memory-service.\n"
        f'<memory path="team/channel/MEMORY.md">private {suffix}</memory>\n'
        "</system-reminder>"
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": reminder},
                {"type": "text", "text": f"<system-reminder>Contact owner{suffix}@example.invalid</system-reminder>"},
                {"type": "text", "text": f"user input {suffix}"},
            ],
        },
        {
            "role": "system",
            "content": "<system-reminder>Scratchpad: /tmp/claude-1/-home-claude/example/scratchpad</system-reminder>",
        },
    ]
    if extra_history:
        messages.extend(
            [
                {"role": "assistant", "content": f"private answer {suffix}"},
                {"role": "user", "content": f"private follow-up {suffix}"},
            ]
        )
    return {
        "timestamp": "2026-09-26T00:00:00Z",
        "request_id": f"request-secret-{suffix}",
        "request": {
            "method": "POST",
            "path": "/v1/messages",
            "headers": {
                "Authorization": f"Bearer secret-{suffix}",
                "Host": "127.0.0.1:34567",
                "Content-Type": "application/json",
            },
            "body": {
                "model": "claude-sonnet-5",
                "system": [{"type": "text", "text": "Stable instruction."}],
                "messages": messages,
                "tools": [{"name": "read_file", "description": "Read a file.", "input_schema": {"type": "object"}}],
                "metadata": {"user_id": json.dumps({"slack_channel": f"C{suffix}12345678"})},
            },
        },
        "response": {"status": 200, "headers": {"request-id": f"response-secret-{suffix}"}},
    }


def write_record(path, record):
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_manual_import_normalizes_private_values_without_hiding_prompt_changes(tmp_path):
    first_source = tmp_path / "first.jsonl"
    second_source = tmp_path / "second.jsonl"
    first = trace_record(suffix="alpha")
    second = trace_record(suffix="bravo")
    write_record(first_source, first)
    write_record(second_source, second)

    first_target = tmp_path / "archive/first"
    second_target = tmp_path / "archive/second"
    meta = import_trace(
        first_source, first_target, agent_id="claude-tag", agent_name="Claude Tag", version="first", surface="slack"
    )
    import_trace(
        second_source, second_target, agent_id="claude-tag", agent_name="Claude Tag", version="second", surface="slack"
    )
    first_prompt = (first_target / "prompt.md").read_text()
    second_prompt = (second_target / "prompt.md").read_text()

    assert first_prompt == second_prompt
    assert "Stable instruction." in first_prompt
    assert "[PRIVATE CHANNEL MEMORY REDACTED BEFORE PUBLICATION]" in first_prompt
    assert "Scratchpad: $PHISTORY_TMP" in first_prompt
    assert "owneralpha" not in (first_target / "trace.jsonl").read_text()
    assert meta["source"]["sha256"] == hashlib.sha256(first_source.read_bytes()).hexdigest()

    changed = copy.deepcopy(second)
    changed["request"]["body"]["tools"][0]["description"] = "Read a file and return its size."
    changed["request"]["body"]["messages"].extend(
        trace_record(suffix="bravo", extra_history=True)["request"]["body"]["messages"][2:]
    )
    write_record(second_source, changed)
    third_target = tmp_path / "archive/third"
    third_meta = import_trace(
        second_source, third_target, agent_id="claude-tag", agent_name="Claude Tag", version="third", surface="slack"
    )
    third_prompt = (third_target / "prompt.md").read_text()

    assert "Read a file and return its size." in third_prompt
    assert third_prompt.count("[PRIOR CONVERSATION REDACTED BEFORE PUBLICATION]") == 1
    assert "private answer" not in third_prompt
    assert third_meta["redacted_history_message_count"] == 2
