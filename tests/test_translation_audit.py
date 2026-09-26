import json

from scripts.audit_translations import private_capture_markers, unredacted_trace_fields


def test_private_memory_markers_detect_embedded_channel_memory():
    text = "\n".join(
        (
            "<mem" + 'ory path="team/channel/' + 'MEMORY.md">',
            "# Channel  memory  index - #private-example",
            "</memory>",
        )
    )

    assert private_capture_markers(text) == ["memory XML", "team memory path", "channel memory index"]
    assert private_capture_markers("[PRIVATE CHANNEL MEMORY REDACTED BEFORE PUBLICATION]") == []


def test_private_capture_markers_detect_concrete_claude_session_url():
    concrete_url = "https://claude.ai/code/" + "session_example123"

    assert private_capture_markers(concrete_url) == ["Claude session URL"]
    assert private_capture_markers("https://claude.ai/code/session_…") == []


def test_private_capture_markers_detect_redaction_omissions():
    text = "Contact " + "private@example.invalid" + " and use " + "https://claude.ai/code/session_example123"

    assert private_capture_markers(text) == ["Claude session URL", "email address"]


def test_unredacted_trace_fields_detect_transport_identifiers():
    record = {
        "request_id": "request-secret",
        "request": {
            "headers": {"Authorization": "Bearer secret"},
            "body": {"metadata": {"user_id": "user-secret"}},
        },
        "response": {
            "headers": {"request-id": "response-secret"},
            "body": {"id": "message-secret"},
            "sse_events": [{"data": {"message": {"id": "event-secret"}}}],
        },
    }

    assert unredacted_trace_fields(json.dumps(record)) == [
        "line 1: request_id",
        "line 1: request header Authorization",
        "line 1: metadata user_id",
        "line 1: response header request-id",
        "line 1: response body id",
        "line 1: SSE event 0 message id",
    ]


def test_unredacted_trace_fields_accept_redacted_values():
    redacted = "<redacted>"
    record = {
        "request_id": redacted,
        "request": {
            "headers": {"Authorization": redacted, "X-Claude-Code-Session-Id": redacted},
            "body": {"metadata": {"user_id": redacted}},
        },
        "response": {
            "headers": {"anthropic-workspace-id": redacted},
            "body": {"id": redacted},
            "sse_events": [{"data": {"message": {"id": redacted}}}],
        },
    }

    assert unredacted_trace_fields(json.dumps(record)) == []
