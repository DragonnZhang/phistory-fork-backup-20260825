from __future__ import annotations

import sys
from pathlib import Path

from phistory.models import CaptureTarget
from phistory.prompt import read_records, select_request_body
from phistory.storage import latest_trace


def captured_prompt(tap_output_dir: Path) -> bool:
    """A run succeeds when its trace holds a prompt-bearing request, whatever the client's exit code."""
    try:
        return select_request_body(read_records(latest_trace(tap_output_dir))) is not None
    except (RuntimeError, OSError):
        return False


def tap_command(target: CaptureTarget, tap_output_dir: Path) -> list[str]:
    # claude-tap only answers with dummy responses while an export path is set; the archive
    # itself is rendered from the trace, so this export is a capture-only switch we discard.
    tap_output_dir.mkdir(parents=True, exist_ok=True)
    return [
        sys.executable,
        "-m",
        "claude_tap",
        "run",
        target.agent.tap_client,
        *_tap_yolo_args(target),
        "--export-prompt",
        str(tap_output_dir / "tap-export.md"),
        "--no-live",
        "--no-open",
        "--no-update-check",
        "--output-dir",
        str(tap_output_dir),
        *_tap_mode_args(target),
        "--",
        *upstream_client_args(target.variant.run_args),
    ]


def upstream_client_args(run_args: tuple[str, ...]) -> list[str]:
    args = list(run_args)
    if args and args[0] == "--no-yolo":
        args.pop(0)
    if args and args[0] == "--":
        args.pop(0)
    return args


def _tap_mode_args(target: CaptureTarget) -> list[str]:
    if target.agent.tap_mode == "auto":
        return []
    return ["--mode", target.agent.tap_mode]


def _tap_yolo_args(target: CaptureTarget) -> list[str]:
    if target.variant.run_args[:1] == ("--no-yolo",):
        return ["--no-yolo"]
    return []
