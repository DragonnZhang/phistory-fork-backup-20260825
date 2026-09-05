import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from phistory.drivers import CaptureRunContext
from phistory.drivers.dsh_web import PROMPT, _authenticate_web, _create_and_prompt_session, _rpc_when_ready
from phistory.models import CaptureTarget, VersionInfo
from phistory.registry import get_agent


@pytest.mark.parametrize("requires_auth", [False, True])
@pytest.mark.parametrize("remote_rpc", [False, True])
@pytest.mark.parametrize("variant_id", ["default", "code"])
def test_dsh_web_creates_and_prompts_session_with_browser_auth(
    tmp_path: Path, monkeypatch, requires_auth: bool, remote_rpc: bool, variant_id: str
):
    calls = []
    logins = []
    startup_requests = []
    preset_id = "ptc" if remote_rpc else "code"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            logins.append(self.path)
            if self.path == "/?token=local-test-token":
                self.send_response(303)
                self.send_header("Set-Cookie", "dsh-auth-test=local-session; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Location", "/")
            else:
                self.send_response(200 if self.headers.get("Cookie") == "dsh-auth-test=local-session" else 401)
            self.end_headers()

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not startup_requests:
                startup_requests.append(self.path)
                self.send_response(503)
                self.end_headers()
                return
            if requires_auth and self.headers.get("Cookie") != "dsh-auth-test=local-session":
                self.send_response(401)
                self.end_headers()
                return
            endpoints = ("session/create", "session/prompt") if remote_rpc else ("session.create", "session.prompt")
            if self.path not in [f"/api/{endpoint}" for endpoint in endpoints]:
                self.send_response(404)
                self.end_headers()
                return
            assert payload["method"] == self.path.removeprefix("/api/")
            arguments = payload["payload"]
            if remote_rpc:
                assert set(arguments) == {"args"}
                assert set(arguments["args"]) == {"request"}
                arguments = arguments["args"]["request"]
            preset = arguments.get("agentPreset", "standard")
            if preset not in ("standard", preset_id):
                result = {
                    "ok": False,
                    "error": {
                        "code": "agent-preset/not-found" if remote_rpc else "agent-preset-not-found",
                        "details": {"available": ["standard", preset_id]},
                    },
                }
            else:
                calls.append((self.path, arguments))
                result = {"ok": True, "value": {"sessionId": "created-session", "agentPreset": preset}}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"result": result}).encode())

        def log_message(self, *_args):
            pass

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr("phistory.drivers.dsh_web.SERVER_TIMEOUT_SECONDS", 2)
    agent = get_agent("dsh")
    target = CaptureTarget(agent, VersionInfo("1.0.0"), agent.variant(variant_id), tmp_path)
    tap_dir = tmp_path / "tap"
    tap_dir.mkdir()
    context = CaptureRunContext(target, target.prompt_path, tap_dir, tmp_path, {})
    process = SimpleNamespace(poll=lambda: None)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        if requires_auth:
            (tap_dir / "client.log").write_text(f"dsh web: http://127.0.0.1:{port}/?token=local-test-token\n")
        try:
            observed = _create_and_prompt_session(context, port, process)
        finally:
            server.shutdown()
            thread.join(timeout=5)

    expected_paths = (
        ["/api/session/create", "/api/session/prompt"] if remote_rpc else ["/api/session.create", "/api/session.prompt"]
    )
    assert [path for path, _ in calls] == expected_paths
    expected_create = {"sessionId": f"phistory-{variant_id}", "cwd": str(tmp_path)}
    if variant_id == "code":
        expected_create["agentPreset"] = preset_id
    assert calls[0][1] == expected_create
    assert calls[1][1] == {
        "requestId": f"phistory-{variant_id}-prompt",
        "sessionId": "created-session",
        "mode": "queue",
        "content": [{"type": "text", "text": PROMPT}],
    }
    assert logins == (["/?token=local-test-token", "/"] if requires_auth else [])
    assert observed == {"mode": preset_id if variant_id == "code" else "standard"}


def test_dsh_web_authenticates_only_the_launched_server(tmp_path: Path):
    opened = []
    opener = SimpleNamespace(open=lambda *args, **kwargs: opened.append(args))
    log = tmp_path / "client.log"

    assert not _authenticate_web(opener, log, 1234)
    log.write_text("dsh web: http://127.0.0.1:5678/?token=another-process\n")
    assert not _authenticate_web(opener, log, 1234)
    assert opened == []


def test_dsh_web_does_not_retry_permanent_rpc_errors(tmp_path: Path, monkeypatch):
    error = urllib.error.HTTPError("http://127.0.0.1:1234/api/session.create", 403, "Forbidden", {}, None)

    def rejected(*_args):
        raise error

    monkeypatch.setattr("phistory.drivers.dsh_web._rpc", rejected)
    monkeypatch.setattr("phistory.drivers.dsh_web.time.sleep", lambda _: pytest.fail("retried a permanent error"))
    process = SimpleNamespace(poll=lambda: None)

    with pytest.raises(urllib.error.HTTPError) as caught:
        _rpc_when_ready(1234, "session.create", {}, process, urllib.request.build_opener(), tmp_path / "client.log")

    assert caught.value is error
