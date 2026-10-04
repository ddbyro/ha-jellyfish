# JellyFish Lighting – Home Assistant integration

Local-push HA custom integration (`custom_components/jellyfish`, domain `jellyfish`) for
JellyFish Lighting controllers, plus `jf.py`, a stdlib CLI for poking the API.

## Safety: the controller is live

- Controller: `192.168.0.224`, websocket `ws://192.168.0.224:9000/ws`
  (hostname `JellyFish-2AB3.local`, name "Home", firmware 4.6.1).
- These are the user's real house lights. **Ask before sending any `toCtlrSet`.**
  `toCtlrGet` is safe. Even "no-op" sets can change things: re-sending the
  running pattern with `state: 1` turns lights on if they were off. Check
  state first, and restore what you changed.
- Never write zone config (`zones`) without explicit approval. It changes
  port mapping and turns all lights off.

## Hardware state (as of 2026-10-03)

- One zone, `Zone`: bottom run = 80 pixels, top run = 57 pixels.
- Top run is on board port LED1 and works.
- **Bottom run is faulty**: whenever the controller drives it (tested on LED3,
  even at 20% brightness), the controller reboots about 2 s later. Likely a short in
  that run. The user is pursuing a warranty or replacement with JellyFish.
- With the bottom cable unplugged or mapped to an empty port, the controller is
  stable. Check the live zone config before assuming which port it's mapped to.

## Protocol facts (verified on firmware 4.6.1; the official PDF omits most)

- JSON text frames. Requests: `{"cmd":"toCtlrGet","get":[[resource, *args]]}` or
  `{"cmd":"toCtlrSet", ...}`. Replies: `{"cmd":"fromCtlr", <resource>: ...}`.
- Get resources: `ctlrName`, `hostName`, `version`, `timeConfig`, `zones`,
  `patternFileList`, `patternFileData <folder> <name>`, `runPattern <zone>`,
  `scheduleDaily`, `scheduleCalendar`.
- Set payloads: `runPattern`, `zones` (+ `"save": true`), `patternFileData`
  (save), `patternFileDelete`, `schedule` + `events`, `ctlrName`.
- **Get replies go only to the requester. Set replies are broadcast to every
  connected client.** This is what makes local push work, including changes from the app.
- Pattern `data`/`jsonData` is a JSON *string*. A missing field makes the
  controller ignore the command silently, so always send a complete pattern (use
  `const.build_pattern`).
- Saving `zones` resets every zone's run state to off.
- After a reboot, zones report a placeholder: `state 0`, `file ""`, no
  `activatedBy`, colors `[100,100,100]`. The coordinator uses this to detect restarts.
- The controller may not close TCP on reboot, so the client relies on an app-level
  heartbeat (`get ctlrName` every 30 s).
- `phyPort` = the board's LED1–LED4 label. Pixel indexes are 0-based. The app shows
  them 1-based, and its port picker appeared off by one. Don't trust the app's port numbers.
- The JellyFish app saves its own copy of the zone config and can overwrite changes
  made over the API. Have the user close the app when editing zones.

## Code layout

- `client.py`: async websocket client (aiohttp). Persistent connection, request/
  response matching by reply key, reconnect with backoff, health counters. No HA imports.
- `coordinator.py`: `DataUpdateCoordinator[JellyFishData]`. Full refresh on
  setup, after reconnect, and every `poll_interval` (default 300 s). Pushed
  messages are applied in `_on_message`. Restart and drop tracking lives in `Health`.
- `entity.py`: base classes. Controller entities sit on the controller device, zone
  entities on a per-zone device. `async_rerun_with` re-sends the current pattern
  with overrides.
- Platforms: `light`, `select`, `number`, `sensor`, `binary_sensor`, `button`, `text`.
- `services.py`: integration services (patterns, schedules, zone config). The
  entity services `run_custom_pattern` and `adjust_pattern` are registered in `light.py`.
- `const.py`: valid enum values, default pattern, `build_pattern`/`flatten_colors`.
- `strings.json` and `translations/en.json` are generated together and must stay identical.
- `services.yaml` must not use YAML anchors. hassfest rejects dot-prefixed keys.

## Testing

No pip or venv on the host. Tests run in podman:

```bash
podman build -t jellyfish-test -f Containerfile.test .
podman run --rm -v "$PWD":/work:Z jellyfish-test python -m pytest -q
podman run --rm -v "$PWD/custom_components/jellyfish":/github/workspace/custom_components/jellyfish:Z ghcr.io/home-assistant/hassfest
```

- `tests/fake_controller.py` is an in-process fake that reproduces the protocol facts
  above (broadcast sets, zone save resets state, `reboot()`, `drop_all()`). When you
  learn something new about the firmware, update the fake to match.
- Tests need the `socket_enabled` fixture (HA's harness blocks sockets). Assertions on
  what the fake received must wait first: use `_sets()` / `_last_run()`.
- Last validated with HA 2026.2.3 (test harness). Minimum supported HA: 2025.1.0 (`hacs.json`).

## Status / TODO

- Not yet installed in the user's real HA instance. The set paths (brightness,
  color, speed) are tested only against the fake.
- GitHub: public repo `ddbyro/ha-jellyfish` (manifest links match). Keep personal data (location, names) out of committed files.
- Default branch `main`, pushed to GitHub.
- The user is learning Go, but HA integrations must be Python. Explain non-obvious HA
  patterns when changing them.
