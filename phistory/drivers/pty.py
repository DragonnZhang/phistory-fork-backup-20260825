"""Drive a terminal UI the way a user does, so the capture sees the interactive surface.

CLIs that also offer a headless flag often send a different system prompt and a
different tool set there, so the interactive path has to be exercised for real:
a pseudo terminal, a typed message, and a wait for the request it triggers.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time

from phistory.drivers import CaptureExecution, CaptureRunContext
from phistory.drivers.common import captured_prompt, tap_command
from phistory.models import CommandResult

SETTLE_SECONDS = 12.0
SUBMIT_DELAY_SECONDS = 1.5
CAPTURE_TIMEOUT_SECONDS = 150.0
SHUTDOWN_SECONDS = 20.0
TERMINAL_SIZE = (45, 120)
# A TUI that believes it runs unattended will not render the interactive surface.
BATCH_ENV = ("CI", "GITHUB_ACTIONS", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def run_pty(context: CaptureRunContext) -> CaptureExecution:
    argv = tap_command(context.target, context.tap_output_dir)
    message = context.target.variant.pty_message or "Reply with one short sentence."
    transcript, returncode = _session(argv, context, message)
    result = CommandResult(tuple(argv), returncode, transcript, "")
    return CaptureExecution(tuple(argv), result, {"surface": "interactive-tty"})


def _session(argv: list[str], context: CaptureRunContext, message: str) -> tuple[str, int]:
    controller, follower = pty.openpty()
    fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", *TERMINAL_SIZE, 0, 0))
    env = {key: value for key, value in context.env.items() if key not in BATCH_ENV}
    env["TERM"] = "xterm-256color"
    process = subprocess.Popen(
        argv,
        stdin=follower,
        stdout=follower,
        stderr=follower,
        env=env,
        cwd=context.work_dir,
        start_new_session=True,
    )
    os.close(follower)

    buffer = bytearray()
    started = time.monotonic()
    typed = submitted = False
    try:
        while time.monotonic() - started < CAPTURE_TIMEOUT_SECONDS:
            elapsed = time.monotonic() - started
            _drain(controller, buffer, timeout=0.3)
            if not typed and elapsed > SETTLE_SECONDS:
                os.write(controller, message.encode())
                typed = True
            elif typed and not submitted and elapsed > SETTLE_SECONDS + SUBMIT_DELAY_SECONDS:
                os.write(controller, b"\r")
                submitted = True
            elif submitted and captured_prompt(context.tap_output_dir):
                break
            if process.poll() is not None:
                break
    finally:
        _shutdown(process)
        _drain(controller, buffer, timeout=1.0, rounds=20)
        os.close(controller)
    return buffer.decode("utf-8", errors="replace"), process.returncode or 0


def _drain(fd: int, buffer: bytearray, *, timeout: float, rounds: int = 1) -> None:
    for _ in range(rounds):
        if not select.select([fd], [], [], timeout)[0]:
            return
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        if not chunk:
            return
        buffer += chunk


def _shutdown(process: subprocess.Popen) -> None:
    """Interactive clients flush their session on SIGINT; only escalate if they hang."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        if process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except OSError:
            return
        try:
            process.wait(timeout=SHUTDOWN_SECONDS if sig == signal.SIGINT else 5)
            return
        except subprocess.TimeoutExpired:
            continue
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
