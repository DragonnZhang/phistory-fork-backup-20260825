"""Import one manually supplied Claude Tag request with repeatable redaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from phistory.prompt import render_archive_markdown, snapshot_from_trace
from scripts.audit_translations import private_capture_markers, unredacted_trace_fields

MEMORY_INDEX = re.compile(
    r"(?m)^The following is the memory index at [^\n]*\n"
    r"<memory\s+path=(?:\"[^\"]*\"|'[^']*')[^>]*>.*?</memory>",
    re.IGNORECASE | re.DOTALL,
)
MEMORY_BLOCK = re.compile(r"<memory\s+path=(?:\"[^\"]*\"|'[^']*')[^>]*>.*?</memory>", re.IGNORECASE | re.DOTALL)
SESSION_URL = re.compile(r"https://claude\.ai/(?:code|session-lens)/session_[A-Za-z0-9]+", re.IGNORECASE)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SCRATCHPAD = re.compile(r"/tmp/claude-[^\s`\"<>]+/scratchpad")
HOME = re.compile(r"/(?:data00/)?home/[A-Za-z0-9._-]+")
LOCAL_HOST = re.compile(r"(?:127\.0\.0\.1|localhost):\d+")

REDACTIONS = (
    "authorization and transport identifiers",
    "organization, workspace, Slack, and user metadata",
    "private memory content, session links, and email addresses",
    "local home, memory, and scratchpad paths",
    "captured user, assistant, tool-result, and response content",
)


def sanitize_record(record: dict) -> tuple[dict, int]:
    """Keep prompt instructions and tools while removing private runtime context."""
    result = deepcopy(record)
    request = result["request"]
    body = request["body"]
    messages = body["messages"]
    if not messages or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), list):
        raise ValueError("expected the first message to contain user content blocks")

    sensitive_values = {record.get("request_id")}
    source_headers = request.get("headers", {})
    for key in (
        "Authorization",
        "X-Claude-Code-Session-Id",
        "x-claude-remote-container-id",
        "x-claude-remote-session-id",
    ):
        sensitive_values.add(source_headers.get(key))
    metadata = body.get("metadata", {})
    if isinstance(metadata, dict):
        user_id = metadata.get("user_id")
        sensitive_values.add(user_id)
        if isinstance(user_id, str):
            try:
                user_data = json.loads(user_id)
            except json.JSONDecodeError:
                user_data = {}
            if isinstance(user_data, dict):
                sensitive_values.update(
                    user_data.get(key) for key in ("slack_channel", "device_id", "session_id", "account_uuid")
                )
    response = record.get("response", {})
    if isinstance(response, dict):
        sensitive_values.update(
            response.get("headers", {}).get(key)
            for key in ("request-id", "anthropic-organization-id", "anthropic-workspace-id", "traceresponse", "cf-ray")
        )
        response_body = response.get("body", {})
        if isinstance(response_body, dict):
            sensitive_values.add(response_body.get("id"))
    sensitive_values = {value for value in sensitive_values if isinstance(value, str) and len(value) >= 12}

    def scrub(text: str) -> str:
        text = MEMORY_INDEX.sub("[PRIVATE CHANNEL MEMORY REDACTED BEFORE PUBLICATION]", text)
        text = MEMORY_BLOCK.sub("[PRIVATE CHANNEL MEMORY REDACTED BEFORE PUBLICATION]", text)
        text = SCRATCHPAD.sub("$PHISTORY_TMP", text)
        text = text.replace("/tmp/claude/memory/team/channel/", "$PHISTORY_MEMORY_CHANNEL/")
        text = text.replace("/tmp/claude/memory/team/silo/", "$PHISTORY_MEMORY_SILO/")
        for value in sorted(sensitive_values, key=len, reverse=True):
            text = text.replace(value, "<redacted>")
        text = SESSION_URL.sub("[PRIVATE CLAUDE SESSION LINK REDACTED BEFORE PUBLICATION]", text)
        text = EMAIL.sub("[PRIVATE EMAIL REDACTED BEFORE PUBLICATION]", text)
        text = text.replace("team/channel/MEMORY.md", "[PRIVATE MEMORY PATH REDACTED]")
        text = HOME.sub("$PHISTORY_USER_HOME", text)
        return LOCAL_HOST.sub("127.0.0.1:$PHISTORY_PORT", text)

    def scrub_strings(value):
        if isinstance(value, dict):
            return {key: scrub_strings(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub_strings(item) for item in value]
        return scrub(value) if isinstance(value, str) else value

    first = deepcopy(messages[0])
    reminders = [
        block
        for block in first["content"]
        if isinstance(block, dict)
        and isinstance(block.get("text"), str)
        and block["text"].lstrip().startswith("<system-reminder>")
    ]
    first["content"] = reminders + [{"type": "text", "text": "[CAPTURED USER CONTENT REDACTED BEFORE PUBLICATION]"}]
    later_system = [message for message in messages[1:] if message.get("role") == "system"]
    history_count = sum(message.get("role") != "system" for message in messages[1:])
    body["messages"] = [first, *later_system]
    if history_count:
        body["messages"].append(
            {"role": "user", "content": [{"type": "text", "text": "[PRIOR CONVERSATION REDACTED BEFORE PUBLICATION]"}]}
        )
    if isinstance(metadata, dict) and "user_id" in metadata:
        metadata["user_id"] = "<redacted>"
    request["headers"] = {
        key: value
        for key, value in source_headers.items()
        if key in ("Content-Type", "User-Agent", "anthropic-version")
    }
    request["headers"]["Authorization"] = "<redacted>"
    request["headers"]["Host"] = "127.0.0.1:$PHISTORY_PORT"
    result["request_id"] = "<redacted>"
    result["request"]["body"] = scrub_strings(body)
    result["response"] = {
        "status": response.get("status") if isinstance(response, dict) else None,
        "body": {
            "model": body.get("model"),
            "content": [{"type": "text", "text": "[CAPTURED RESPONSE CONTENT REDACTED BEFORE PUBLICATION]"}],
        },
    }
    return result, history_count


def import_trace(source: Path, target: Path, *, agent_id: str, agent_name: str, version: str, surface: str) -> dict:
    lines = source.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ValueError("manual source must contain exactly one JSON record")
    record = json.loads(lines[0])
    if not isinstance(record, dict):
        raise ValueError("manual source must contain a JSON object")
    sanitized, history_count = sanitize_record(record)
    trace = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")) + "\n"
    markers = private_capture_markers(trace)
    fields = unredacted_trace_fields(trace)
    if markers or fields:
        raise ValueError(f"manual trace still contains private fields: {markers + fields}")

    with TemporaryDirectory(prefix="phistory-manual-") as temporary:
        staged = Path(temporary)
        trace_path = staged / "trace.jsonl"
        trace_path.write_text(trace, encoding="utf-8")
        prompt = render_archive_markdown(trace_path)
        if markers := private_capture_markers(prompt):
            raise ValueError(f"rendered prompt still contains private fields: {markers}")
        (staged / "prompt.md").write_text(prompt, encoding="utf-8")
        snapshot = snapshot_from_trace(trace_path)
        meta = {
            "agent_id": agent_id,
            "agent": agent_name,
            "version": version,
            "variant": {"id": "default", "label": "Default", "dimensions": {"surface": surface}},
            "requested": {"surface": surface},
            "observed": snapshot.observation,
            "published_at": record["timestamp"],
            "captured_at": record["timestamp"],
            "target": "manually imported trace",
            "trace_redacted": True,
            "redactions": list(REDACTIONS),
            "redacted_history_message_count": history_count,
            "source": {"kind": "user-provided trace", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        }
        (staged / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        target.mkdir(parents=True, exist_ok=True)
        for name in ("trace.jsonl", "prompt.md", "meta.json"):
            shutil.copyfile(staged / name, target / name)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("version")
    parser.add_argument("--agent-id", default="claude-tag")
    parser.add_argument("--agent-name", default="Claude Tag")
    parser.add_argument("--surface", default="slack")
    parser.add_argument("--root", type=Path, default=Path("captures"))
    args = parser.parse_args()
    target = args.root / args.agent_id / args.version / "variants/default"
    meta = import_trace(
        args.source,
        target,
        agent_id=args.agent_id,
        agent_name=args.agent_name,
        version=args.version,
        surface=args.surface,
    )
    print(f"imported {target}: {meta['observed']}; redacted history messages: {meta['redacted_history_message_count']}")


if __name__ == "__main__":
    main()
