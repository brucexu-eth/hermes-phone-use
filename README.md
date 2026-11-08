# Hermes Phone Use

Drive the phone on your Mac from a Hermes that runs somewhere else, such as a Linux server, and get the screen back in Telegram or Discord.

```
Telegram ─▶ Hermes (Linux) ─remote_phone_exec─▶ private network (Tailscale / SSH tunnel)
          ◀─ screenshot (MEDIA:) ◀──────────────  phone-relay (Mac) ─▶ phone-harness ─▶ iPhone Mirroring
```

[phone-harness](https://github.com/phone-harness/phone-harness) drives a real iPhone through macOS iPhone Mirroring, but only from the Mac itself. Its hosted MCP covers cloud phones, not your own phone. This plugin adds the missing link: a small relay next to phone-harness and a Hermes tool that calls it.

## Setup

**On the Mac** (macOS 15+, iPhone Mirroring paired, phone-harness installed and `phone-harness doctor` green):

```bash
export PHONE_RELAY_TOKEN=$(openssl rand -hex 32)   # copy it for the Hermes side
python3 relay/phone_relay.py --host <mac-tailscale-ip> --port 8765
```

The relay uses only the Python standard library. It refuses to bind `0.0.0.0` and refuses tokens shorter than 32 characters.

**On the Hermes host:**

```bash
hermes plugins install <this repo>
hermes config set plugins.entries.hermes-phone-use.settings.relay_url http://<mac-tailscale-ip>:8765
# REMOTE_PHONE_TOKEN = the token above (prompted at install, or in Desktop → Settings → Plugins)
```

Then ask from any chat: *"Open Weather on my phone and send me a screenshot."*

## Tool

`remote_phone_exec(code, timeout_s=120)` sends Python with the phone-harness helpers (`ensure_device`, `screen`, `tap_text`, `type_text`, `swipe`, `open_app`, `screenshot`, …). The result contains stdout and stderr, and when the script called `screenshot()`, also a local `screenshot_path`. The agent shows that image in chat with `MEDIA:<path>`.

## Safety and disclosure

- **The relay runs model-written Python on the Mac with your user's permissions.** Keep it on a private network. The bearer token is the trust boundary.
- **Every call needs your approval** through Hermes's approval gate (`pre_tool_call` → approve). The `auto_run` setting turns this off. It defaults to off.
- **One script runs at a time.** A second request gets HTTP 409.
- **The relay never logs script bodies.**
- **Network.** The Hermes side talks only to the `relay_url` you configure. Screenshots are stored under `$HERMES_HOME/plugin-data/hermes-phone-use/screenshots/`. No telemetry.
- **phone-harness limits still apply.** The Mac must be awake and logged in. The iPhone stays locked and nearby, because unlocking it pauses mirroring. There is no Face ID and no multi-touch. Never ask the agent to type passwords or 2FA codes.

## Tests

```bash
python -m pytest -q tests   # real HTTP round trip: plugin → relay process → stub phone-harness
```
