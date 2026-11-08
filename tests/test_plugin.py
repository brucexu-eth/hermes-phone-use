"""Real HTTP round trips against a local fake Pinky (Streamable HTTP MCP with SSE answers)."""
import base64
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("phone_use", ROOT / "__init__.py")
pu = importlib.util.module_from_spec(spec)
sys.modules["phone_use"] = pu
spec.loader.exec_module(pu)

TOKEN = "t" * 40
PNG = base64.b64encode(b"\x89PNG fake").decode()


class FakePinky(BaseHTTPRequestHandler):
    sessions: dict = {}
    calls: list = []
    pending_left = 0
    expire_next = False

    def log_message(self, *a):
        pass

    def _send(self, status, payload=None, sid=None):
        self.send_response(status)
        if sid:
            self.send_header("Mcp-Session-Id", sid)
        if payload is None:
            self.end_headers()
            return
        body = f"event: message\ndata: {json.dumps(payload)}\n\n".encode()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401)
        cls = FakePinky
        if msg["method"] == "initialize":
            cls.issued = getattr(cls, "issued", 0) + 1
            sid = f"s{cls.issued}"
            cls.sessions[sid] = True
            return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"serverInfo": {"name": "pinky"}}}, sid)
        sid = self.headers.get("Mcp-Session-Id")
        if cls.expire_next and "id" in msg:
            cls.expire_next = False
            cls.sessions.pop(sid, None)
        if sid not in cls.sessions:
            return self._send(404)
        if "id" not in msg:
            return self._send(202)
        if msg["method"] == "tools/list":
            tools = json.loads((ROOT / "pinky_tools.json").read_text())["tools"]
            return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
        args = msg["params"]["arguments"]
        cls.calls.append((sid, msg["params"]["name"], dict(args)))
        if cls.pending_left > 0:
            cls.pending_left -= 1
            text = "approval_pending · Bruce's iPhone\napproval_id: ap_42\nThe person is deciding."
            content = [{"type": "text", "text": text}]
        else:
            content = [{"type": "text", "text": "settled · Bruce's iPhone\n[1] button \"OK\""},
                       {"type": "image", "mimeType": "image/png", "data": PNG}]
        return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": content}})


@pytest.fixture
def pinky():
    FakePinky.sessions, FakePinky.calls, FakePinky.pending_left, FakePinky.expire_next = {}, [], 0, False
    FakePinky.issued = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePinky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_endpoint_accepts_short_forms():
    assert pu.endpoint("100.1.2.3:7465") == "http://100.1.2.3:7465/mcp"
    assert pu.endpoint("http://h:7465/") == "http://h:7465/mcp"
    assert pu.endpoint("https://h/mcp") == "https://h/mcp"


def test_call_keeps_session_and_saves_screenshot(pinky, tmp_path):
    client = pu.PinkyClient(pu.endpoint(pinky), TOKEN)
    out1 = pu.run_tool("phone_connect", {"task": "t", "read_only": True}, client, lambda _: None, lambda: tmp_path)
    out2 = pu.run_tool("phone_observe", {"screenshot": True}, client, lambda _: None, lambda: tmp_path)
    assert "settled" in out1 and "settled" in out2
    assert {c[0] for c in FakePinky.calls} == {"s1"}, "both calls must share one MCP session (the lease)"
    shot = out2.split("screenshot: ")[1].split(" ")[0]
    assert Path(shot).read_bytes() == base64.b64decode(PNG)
    assert f"MEDIA:{shot}" in out2


def test_approval_pending_waits_and_notifies_once(pinky, tmp_path):
    FakePinky.pending_left = 2
    told = []
    out = pu.run_tool("phone_tap", {"ref": 3}, pu.PinkyClient(pu.endpoint(pinky), TOKEN), told.append, lambda: tmp_path)
    assert "settled" in out
    assert [c[2].get("approval_id") for c in FakePinky.calls] == [None, "ap_42", "ap_42"]
    assert len(told) == 1 and "Pinky" in told[0]


def test_expired_session_is_renewed(pinky, tmp_path):
    client = pu.PinkyClient(pu.endpoint(pinky), TOKEN)
    pu.run_tool("phone_apps", {}, client, lambda _: None, lambda: tmp_path)
    FakePinky.expire_next = True
    out = pu.run_tool("phone_apps", {}, client, lambda _: None, lambda: tmp_path)
    assert "settled" in out and client.session_id == "s2"


def test_bad_token_is_reported(pinky, tmp_path):
    with pytest.raises(pu.PinkyError, match="401"):
        pu.run_tool("phone_apps", {}, pu.PinkyClient(pu.endpoint(pinky), "wrong"), lambda _: None, lambda: tmp_path)


def test_register_uses_live_tools_and_settings(pinky, monkeypatch):
    monkeypatch.setenv("PINKY_TOKEN", TOKEN)
    monkeypatch.setattr(pu, "_token", lambda: TOKEN)

    class Ctx:
        tools, sections, skills = [], [], []

        def get_config(self, key, default=None):
            return {"url": pinky}.get(key, default)

        def register_tool(self, **kw):
            self.tools.append(kw)

        def register_system_prompt_section(self, id, content, **kw):
            self.sections.append(content)

        def register_skill(self, name, path, description=""):
            self.skills.append((name, Path(path).exists()))

    ctx = Ctx()
    pu.register(ctx)
    assert len(ctx.tools) == 14 and ctx.tools[0]["check_fn"]()
    assert "phone_*" in ctx.sections[0]({}) and ctx.skills == [("phone-use", True)]
