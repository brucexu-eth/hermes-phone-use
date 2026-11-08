#!/usr/bin/env python3
"""phone-relay: expose this Mac's phone-harness to a Hermes running on another machine.

Run it on the Mac that hosts iPhone Mirroring (or has an Android on adb). It accepts one
authenticated POST /exec at a time, pipes the script into the local ``phone-harness`` CLI and
returns stdout, stderr and the newest screenshot the script printed (base64 PNG/JPEG).

Bind it to a private interface only (a Tailscale IP, or 127.0.0.1 behind an SSH tunnel). It runs
model-written Python with this user's permissions, so the bearer token is the whole trust
boundary: generate a long random one and keep it out of shell history.

    PHONE_RELAY_TOKEN=$(openssl rand -hex 32) python3 phone_relay.py --host 100.x.y.z --port 8765

Standard library only. Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 256_000
MAX_TIMEOUT_S = 600
OUTPUT_CAP, STDERR_CAP = 50_000, 4_000
MAX_IMAGE_BYTES = 8_000_000
IMAGE_PATH = re.compile(r"(/[^\s'\"]+\.(?:png|jpe?g))", re.IGNORECASE)
_LOCK = threading.Lock()


def newest_image(stdout: str, since: float):
    for path in reversed(IMAGE_PATH.findall(stdout or "")):
        try:
            if os.path.isfile(path) and os.path.getmtime(path) >= since - 1 \
                    and os.path.getsize(path) <= MAX_IMAGE_BYTES:
                return path
        except OSError:
            continue
    return None


def run_script(command: list, code: str, timeout: int) -> dict:
    started = time.time()
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(input=code, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return {"success": False, "error": f"timed out after {timeout}s"}
    result = {"success": proc.returncode == 0, "exit_code": proc.returncode,
              "output": (out or "")[-OUTPUT_CAP:], "stderr": (err or "").strip()[-STDERR_CAP:]}
    shot = newest_image(out, started)
    if shot:
        with open(shot, "rb") as f:
            result["screenshot"] = {"name": os.path.basename(shot), "base64": base64.b64encode(f.read()).decode()}
    return result


def make_handler(token: str, command: list):
    class Handler(BaseHTTPRequestHandler):
        server_version = "phone-relay/0.1"

        def log_message(self, fmt, *args):  # one line per request, never the script body
            print(f"{self.address_string()} {fmt % args}", flush=True)

        def _send(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            sent = self.headers.get("Authorization", "")
            return hmac.compare_digest(sent.encode(), f"Bearer {token}".encode())

        def do_GET(self):
            if self.path != "/health":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            self._send(200, {"ok": True, "busy": _LOCK.locked(), "command": command[0]})

        def do_POST(self):
            if self.path != "/exec":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "body missing or too large"})
            try:
                req = json.loads(self.rfile.read(length))
                code = str(req["code"])
                timeout = max(5, min(int(req.get("timeout_s") or 120), MAX_TIMEOUT_S))
            except Exception:
                return self._send(400, {"error": "expected JSON {code, timeout_s?}"})
            if not _LOCK.acquire(blocking=False):
                return self._send(409, {"error": "phone is busy with another script"})
            try:
                self._send(200, run_script(command, code, timeout))
            except OSError as e:
                self._send(500, {"error": f"failed to launch phone-harness: {e}"})
            finally:
                _LOCK.release()

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", required=True, help="private address to bind (Tailscale IP or 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--command", default="phone-harness", help="phone-harness CLI (default: from PATH)")
    a = ap.parse_args()
    token = os.environ.get("PHONE_RELAY_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set PHONE_RELAY_TOKEN to a random secret of at least 32 characters.")
    if a.host in ("0.0.0.0", "::", ""):
        raise SystemExit("Refusing to bind every interface; pass a private address.")
    command = shlex.split(a.command)
    if not shutil.which(command[0]):
        raise SystemExit(f"{command[0]} not found; install phone-harness first.")
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(token, command))
    print(f"phone-relay listening on http://{a.host}:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
