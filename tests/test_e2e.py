"""End-to-end over real HTTP: plugin tool -> phone_relay.py process -> stub phone-harness CLI.

The stub stands in for phone-harness on a Mac: it runs the script with a screenshot() helper
that writes a real PNG and prints its path, exactly like phone-harness's helper.
"""
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).parents[1]
TOKEN = "t" * 40
spec = importlib.util.spec_from_file_location("remote_phone", ROOT / "__init__.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


class Ctx:
    def __init__(self, **cfg):
        self.cfg = cfg

    def get_config(self, key, default=None):
        return self.cfg.get(key, default)


@pytest.fixture(scope="module")
def relay(tmp_path_factory):
    d = tmp_path_factory.mktemp("relay")
    stub = d / "phone-harness"
    stub.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys, time
        def screenshot():
            p = {str(d)!r} + "/shot-%d.png" % time.time_ns()
            open(p, "wb").write({PNG!r})
            print(p)
            return p
        def screen_info():
            return {{"platform": "stub-iphone", "w": 1, "h": 1}}
        exec(sys.stdin.read())
        """))
    stub.chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PHONE_RELAY_TOKEN=TOKEN)
    proc = subprocess.Popen([sys.executable, str(ROOT / "relay" / "phone_relay.py"), "--host", "127.0.0.1",
                             "--port", str(port), "--command", str(stub)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(5)


@pytest.fixture
def plugin(relay, tmp_path, monkeypatch):
    rp._ctx = Ctx(relay_url=relay)
    monkeypatch.setattr(rp, "_token", lambda: TOKEN)
    monkeypatch.setattr(rp, "_shots_dir", lambda: tmp_path)
    return tmp_path


def test_exec_returns_output_and_screenshot(plugin):
    res = json.loads(rp.remote_phone_exec({"code": "print(screen_info()); screenshot()"}))
    assert res["success"] and "stub-iphone" in res["output"]
    shot = pathlib.Path(res["screenshot_path"])
    assert shot.parent == plugin and shot.read_bytes() == PNG


def test_script_error_is_reported(plugin):
    res = json.loads(rp.remote_phone_exec({"code": "raise SystemExit(3)"}))
    assert res["success"] is False and res["exit_code"] == 3 and "screenshot_path" not in res


def test_wrong_token_is_rejected(relay):
    req = urllib.request.Request(relay + "/health", headers={"Authorization": "Bearer nope"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401
    assert "401" in rp._post(relay, "nope", {"code": "print(1)"}, 5)["error"]


def test_timeout_kills_script(plugin):
    res = json.loads(rp.remote_phone_exec({"code": "import time; time.sleep(30)", "timeout_s": 5}))
    assert res["success"] is False and "timed out" in res["error"]


def test_unreachable_relay(monkeypatch):
    rp._ctx = Ctx(relay_url="http://127.0.0.1:1")
    monkeypatch.setattr(rp, "_token", lambda: TOKEN)
    res = json.loads(rp.remote_phone_exec({"code": "print(1)"}))
    assert res["success"] is False and "unreachable" in res["error"]


def test_every_call_needs_approval_unless_auto_run():
    rp._ctx = Ctx(relay_url="x")
    d = rp.on_pre_tool_call(tool_name="remote_phone_exec", args={"code": "tap_text('Send')"})
    assert d["action"] == "approve" and "tap_text('Send')" in d["message"]
    assert rp.on_pre_tool_call(tool_name="terminal", args={}) is None
    rp._ctx = Ctx(relay_url="x", auto_run=True)
    assert rp.on_pre_tool_call(tool_name="remote_phone_exec", args={"code": "x"}) is None
