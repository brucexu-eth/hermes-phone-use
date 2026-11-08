# Hermes Phone Use

Operate your real phone from any Hermes — one on a Linux server, a VM, or another computer — and talk
to it from Telegram, Discord or Slack.

```
Telegram ─▶ Hermes (anywhere) ──HTTP MCP over Tailscale──▶ Pinky (your Mac) ──▶ iPhone / Android
          ◀── text + screenshots ◀────────────────────────  approvals and take-over stay on Pinky
```

[Pinky](https://github.com/DIYgod/pinky) does the phone side: it runs on the Mac the phone is
connected to and decides what an agent may do (blocked apps, read-only mode, approvals, take-over).
This plugin connects Hermes to it and makes it work from chat:

- **Two settings.** The Pinky URL and token; no MCP config to write.
- **Approvals wait instead of failing.** When Pinky asks the person, the tool keeps waiting (up to
  10 minutes) and posts one line to the chat, so you know to look at Pinky.
- **Screenshots come back as images** you can send to the chat.
- **The phone lease survives between tool calls**, and a new session is opened when Pinky's expires.
- **A built-in skill** with the task shape, hand-off rules and a few proven app paths.

## Setup

1. On the Mac, in Pinky: **Settings › Remote agents**, turn it on and set the address to the Mac's
   Tailscale IP, e.g. `100.101.102.103:7465`. Copy the agent token (`pinky token`).
2. On the Hermes host:

```bash
hermes plugins install brucexu-eth/hermes-phone-use   # asks for PINKY_TOKEN
hermes config set plugins.entries.hermes-phone-use.settings.url 100.101.102.103:7465
```

3. The first call shows Hermes as a new remote agent in Pinky: allow it once and pick its apps.

Then ask in chat: *"Open Google Maps on my phone. How long is the drive from JFK Airport to Times Square if I leave now? Send me a screenshot of the route."*

## Safety and disclosure

- **Pinky is the boundary.** Hermes gets only what Pinky allows; it cannot approve anything itself.
  Keep read-only mode on for agents that only need to look.
- **Network.** The plugin talks only to the URL you set. Plain HTTP is fine on a private network
  such as Tailscale; do not expose Pinky's port to the internet.
- **Data.** Screenshots are saved under `$HERMES_HOME/plugin-data/hermes-phone-use/screenshots/`.
  Screen text and images reach your model provider like any other tool output. No telemetry.
- **Limits.** The Mac must be awake with Pinky running. Face ID, passwords and codes are always
  done by you. `phone_files` does not support iPhones.

## Tests

```bash
python -m pytest -q tests   # real HTTP round trips against a local fake Pinky
```
