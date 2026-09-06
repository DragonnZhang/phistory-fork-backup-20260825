from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from phistory.drivers import CaptureExecution, CaptureRunContext
from phistory.drivers.common import tap_command
from phistory.models import CommandResult

SERVER_TIMEOUT_SECONDS = 60
CAPTURE_TIMEOUT_SECONDS = 90
PROMPT = "Reply with one short sentence."


class DshRpcError(RuntimeError):
    def __init__(self, method: str, error: dict[str, object]):
        super().__init__(f"DSH {method} failed: {error}")
        self.error = error


def run_dsh_web(context: CaptureRunContext) -> CaptureExecution:
    port = _free_port()
    argv = tap_command(context.target, context.prompt_path, context.tap_output_dir)
    argv.extend(("--host", "127.0.0.1", "--port", str(port)))
    context.tap_output_dir.mkdir(parents=True, exist_ok=True)
    log_path = context.tap_output_dir / "client.log"
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            argv,
            cwd=context.work_dir,
            env=context.env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            observed = _create_and_prompt_session(context, port, process)
            _wait_for_prompt_trace(context.tap_output_dir, process)
        finally:
            _stop_process(process)
    stdout = log_path.read_text(encoding="utf-8", errors="replace")
    if time.monotonic() - started > CAPTURE_TIMEOUT_SECONDS:
        stdout += "\nDSH Web capture exceeded its timeout."
    result = CommandResult(tuple(argv), process.returncode or 0, stdout, "")
    return CaptureExecution(tuple(argv), result, observed)


def _create_and_prompt_session(context: CaptureRunContext, port: int, process: subprocess.Popen) -> dict[str, object]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor())
    payload: dict[str, object] = {
        "sessionId": f"phistory-{context.target.variant.id}",
        "cwd": str(context.work_dir),
    }
    mode = context.target.variant.dimensions.get("mode")
    if mode:
        payload["agentPreset"] = mode
    try:
        created = _rpc_when_ready(
            port, "session.create", payload, process, opener, context.tap_output_dir / "client.log"
        )
    except DshRpcError as exc:
        details = exc.error.get("details") or {}
        available = details.get("available", []) if isinstance(details, dict) else []
        if (
            not mode
            or mode == context.target.variant.id
            or exc.error.get("code") not in ("agent-preset/not-found", "agent-preset-not-found")
            or context.target.variant.id not in available
        ):
            raise
        payload["agentPreset"] = context.target.variant.id
        created = _rpc(port, "session.create", payload, opener)
    session_id = str(created["sessionId"])
    _rpc(
        port,
        "session.prompt",
        {
            "requestId": f"phistory-{context.target.variant.id}-prompt",
            "sessionId": session_id,
            "mode": "queue",
            "content": [{"type": "text", "text": PROMPT}],
        },
        opener,
    )
    preset = created.get("agentPreset") or payload.get("agentPreset")
    return {"mode": preset} if preset else {}


def _rpc_when_ready(
    port: int,
    method: str,
    payload: dict[str, object],
    process: subprocess.Popen,
    opener: urllib.request.OpenerDirector,
    log_path: Path,
) -> dict[str, object]:
    deadline = time.monotonic() + SERVER_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"DSH Web exited before becoming ready ({process.returncode})")
        try:
            return _rpc(port, method, payload, opener)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                if _authenticate_web(opener, log_path, port):
                    return _rpc(port, method, payload, opener)
            elif exc.code not in (404, 503):
                raise
            last_error = exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"DSH Web did not become ready: {last_error}")


def _authenticate_web(opener: urllib.request.OpenerDirector, log_path: Path, port: int) -> bool:
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    for url in re.findall(r"(?m)^dsh web: (http://\S+)", log):
        parsed = urlsplit(url)
        if parsed.netloc != f"127.0.0.1:{port}" or parsed.path not in ("", "/"):
            continue
        with opener.open(url, timeout=5) as response:
            response.read()
        return True
    return False


def _rpc(
    port: int, method: str, payload: dict[str, object], opener: urllib.request.OpenerDirector
) -> dict[str, object]:
    for endpoint, arguments in ((method.replace(".", "/"), {"args": {"request": payload}}), (method, payload)):
        envelope = {
            "type": "client-request",
            "rpcId": f"phistory-{method}",
            "method": endpoint,
            "payload": arguments,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/{endpoint}",
            data=json.dumps(envelope).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(request, timeout=5) as response:
                body = json.loads(response.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or endpoint == method:
                raise
    result = body.get("result") or {}
    if not result.get("ok"):
        raise DshRpcError(method, result.get("error") or {})
    return result.get("value") or {}


def _wait_for_prompt_trace(tap_output_dir: Path, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _has_prompt_request(tap_output_dir):
            return
        if process.poll() is not None:
            raise RuntimeError(f"DSH Web exited before sending a prompt request ({process.returncode})")
        time.sleep(0.25)
    raise RuntimeError("DSH Web did not emit a prompt-bearing request")


def _has_prompt_request(tap_output_dir: Path) -> bool:
    for trace_path in tap_output_dir.glob("*/trace_*.jsonl"):
        try:
            lines = trace_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = (record.get("request") or {}).get("body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    continue
            if (
                isinstance(body, dict)
                and any(key in body for key in ("messages", "input", "system", "instructions"))
                and PROMPT in json.dumps(body, ensure_ascii=False)
            ):
                return True
    return False


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
