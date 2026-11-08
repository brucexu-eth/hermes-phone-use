---
name: phone-use
description: Use when operating the user's phone through Pinky.
---

# Operating the user's phone (Pinky)

The phone is real and belongs to the user. Pinky on their Mac is the safety boundary: it hides
blocked apps (banking, wallets, password managers by default), enforces read-only mode, and asks the
person before risky steps. Work with it, never around it.

## Task shape

1. `phone_connect` with a one-line `task` the person will see, `read_only: true` for anything that
   only reads (order status, a route, a screenshot), and `apps` limited to what the task needs.
   Use app names as `phone_apps` lists them; call it when unsure.
2. `phone_launch`, then act on refs (`[12]`) from the latest screen. Each action returns the new screen
   or a diff, so `phone_observe` is rarely needed. Use x,y only for things without a ref, e.g. buttons
   that only appear in the screenshot (ask for `screenshot: true` and look at it).
3. Before reporting numbers (balances, data left, amounts), make sure the app finished loading:
   apps often draw `0`, `$0.00` or "Please wait..." first and fill in real values a few seconds
   later. Call `phone_observe` with `wait_ms: 5000` after a launch and report only a value that two
   consecutive reads agree on.
4. Report what you read in plain words; attach a screenshot with `MEDIA:<path>` when it helps.
5. Always end with `phone_release` (`outcome` + one-sentence `summary`).

## When the person is needed

The plugin waits on its own when Pinky answers `approval_pending` and posts one line to the chat, so
just report the outcome. Hand to the person (`phone_handoff` with a concrete `reason`) for:

- Face ID, passcodes, payment passwords, one-time codes: never type these.
- Typing into normal fields while read-only (emails, forms): either hand off with the exact text
  to enter, or ask the user to turn read-only off for this agent in Pinky.
- `paused`, `user_took_over`, `device_locked`: wait with `phone_handoff`.

After a hand-off returns, read the screen again: "handed back" does not mean the step was done.
If a field is still empty, say so and hand off again rather than guessing.

## Statuses

- `settled`: done. `uncertain`: observe before anything else, never repeat blindly.
- `approval_denied`, `blocked_by_policy`, `stale`: nothing happened; choose another way or ask.
- `blocked_by_policy · rule: Read-only`: the agent may type only into search fields.
- An app missing from `phone_apps` is blocked by the user's Pinky settings. Tell the user; only they
  can unblock it (Pinky Settings > Safety), and suggest re-blocking afterwards.

## Getting files off an iPhone

`phone_files` does not support iPhones. Prefer the app's own "export to email" to a mailbox Hermes
can read, then fetch the attachment there.

## Known app paths

- A first screen showing "Please wait..." is still loading: `phone_observe` with `wait_ms`.
