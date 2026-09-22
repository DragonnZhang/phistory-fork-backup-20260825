from scripts.audit_translations import private_capture_markers


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
