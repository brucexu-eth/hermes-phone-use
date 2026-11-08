"""remote-phone: drive the phone attached to another machine (usually your Mac) from a Hermes
that runs somewhere else (a Linux server, a VM), and get the screen back in chat.

Hermes side of a two-part plugin. The Mac runs ``relay/phone_relay.py`` next to phone-harness;
this plugin registers ``remote_phone_exec``, which posts the script to that relay over a private
network (Tailscale, or an SSH tunnel) and stores the returned screenshot locally so the agent can
look at it and send it to the user (``MEDIA:<path>`` on Telegram/Discord).

Every call goes through Hermes's approval gate unless the user turns ``auto_run`` on.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

TOOL = "remote_phone_exec"
TOKEN_ENV = "REMOTE_PHONE_TOKEN"
DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S = 120, 600
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")

DESCRIPTION = (
    "Drive the user's real phone (iPhone through their Mac's iPhone Mirroring, or an Android on adb) "
    "on a remote machine through phone-relay. `code` is Python with the phone-harness helpers "
    "pre-imported (ensure_device, screen, find_text, tap_text, tap, type_text, swipe, scroll, "
    "open_app, home, wait_for_text, screenshot). print() what you need; each call is a fresh "
    "interpreter but the phone keeps its state. Call screenshot() to get the screen back: the image "
    "is saved locally and its path returned as screenshot_path; view it with vision, and show it to "
    "the user by writing MEDIA:<screenshot_path> in your reply. Ask the user before anything "
    "outward-facing or hard to undo (sending, posting, buying, deleting, changing settings). Never "
    "type passwords, PINs or 2FA codes."
)

SCHEMA = {
    "name": TOOL,
    "description": DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python using the phone-harness helpers. print() what you need back."},
            "timeout_s": {"type": "integer", "default": DEFAULT_TIMEOUT_S,
                          "description": f"Max seconds for the script (default {DEFAULT_TIMEOUT_S}, max {MAX_TIMEOUT_S})."},
        },
        "required": ["code"],
    },
}

_ctx: Any = None


def _cfg(key: str, default: Any = None) -> Any:
    try:
        return _ctx.get_config(key, default) if _ctx is not None else default
    except Exception:
        return default


def _token() -> Optional[str]:
    from agent.secret_scope import get_secret

    return get_secret(TOKEN_ENV)


def _shots_dir() -> Path:
    from hermes_constants import get_hermes_home

    d = Path(get_hermes_home()) / "plugin-data" / "remote-phone" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _available() -> bool:
    try:
        return bool(_cfg("relay_url")) and bool(_token())
    except Exception:
        return False


def _summary(code: str, limit: int = 160) -> str:
    one = " ".join(code.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def on_pre_tool_call(tool_name: str = "", args: Optional[dict] = None, **_: Any):
    if tool_name != TOOL or _cfg("auto_run", False) is True:
        return None
    code = str((args or {}).get("code") or "")
    return {"action": "approve", "rule_key": TOOL,
            "message": f"Run on your remote phone: {_summary(code)}"}


def _post(url: str, token: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url.rstrip("/") + "/exec", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("error")
        except Exception:
            detail = None
        return {"success": False, "error": f"relay answered HTTP {e.code}: {detail or e.reason}"}


def save_screenshot(shot: Optional[dict], directory: Path) -> Optional[str]:
    if not shot or not shot.get("base64"):
        return None
    name = _SAFE_NAME.sub("_", str(shot.get("name") or "screen.png"))[-80:]
    if not name.lower().endswith((".png", ".jpg", ".jpeg")):
        name += ".png"
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    path.write_bytes(base64.b64decode(shot["base64"], validate=True))
    return str(path)


def remote_phone_exec(args: dict, **_: Any) -> str:
    code = str((args or {}).get("code") or "")
    if not code.strip():
        return json.dumps({"success": False, "error": "No code. Start with: ensure_device(); print(screen_info())"})
    url, token = _cfg("relay_url"), _token()
    if not url or not token:
        return json.dumps({"success": False, "error": f"Set the relay_url setting and {TOKEN_ENV} first."})
    try:
        timeout = max(5, min(int((args or {}).get("timeout_s") or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_S
    try:
        res = _post(str(url), token, {"code": code, "timeout_s": timeout}, timeout + 15)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return json.dumps({"success": False, "error": f"phone-relay unreachable at {url}: {e}. "
                                                      "Is the Mac awake and the relay running?"})
    shot = res.pop("screenshot", None)
    try:
        path = save_screenshot(shot, _shots_dir())
    except Exception as e:
        path, res["screenshot_error"] = None, str(e)
    if path:
        res["screenshot_path"] = path
    return json.dumps(res, ensure_ascii=False)


def register(ctx: Any) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_tool(name=TOOL, toolset="remote-phone", schema=SCHEMA, handler=remote_phone_exec,
                      check_fn=_available, emoji="📱")
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
