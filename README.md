# JellyFish Lighting (Local) for Home Assistant

Local-push integration for [JellyFish Lighting](https://jellyfishlighting.com/) controllers.
It talks to the controller's websocket API (`ws://<controller>:9000/ws`) directly, with no
cloud and no external Python dependencies. Unofficial; not endorsed by JellyFish Lighting.

## Features

**Control (per zone, plus an "All zones" light when there are several zones)**
- Light: on/off, RGB color, brightness, and every saved pattern as an HA *effect*
- Select: pattern, direction, effect (Twinkle/Lightning), pattern type, effect between pixels
- Number: speed, pattern brightness, effect value, space between pixels, skip, LEDs per block
- Text: controller name (as shown in the app)

**Diagnostics & health**
- Connected (binary sensor), firmware version, firmware update flag
- Restarts detected and last restart: the controller reboots back to an "off" placeholder
  state, and the integration recognizes that after a reconnect
- Connection drops, last connected, websocket latency, last message
- Per zone: active pattern, activated by (app, schedule, network), port map in the board's
  LED1-LED4 terms (e.g. `LED3 0-79, LED1 0-56`), pixel count
- Daily and calendar schedule sensors (events in attributes), saved pattern count
- Diagnostics download with the full controller snapshot (location redacted)

**Services**

| Service | What it does |
|---|---|
| `jellyfish.run_custom_pattern` | Run an ad-hoc pattern on target lights; optional `save_as` |
| `jellyfish.adjust_pattern` | Change fields of the running pattern (speed, colors, ...) |
| `jellyfish.save_pattern` / `delete_pattern` | Manage saved patterns (built-ins are protected) |
| `jellyfish.get_pattern` | Return a pattern's settings (response data) |
| `jellyfish.get_schedule` / `set_schedule` | Read or replace daily/calendar schedules |
| `jellyfish.get_zone_config` / `set_zone_config` | Read or replace zone port mapping (`confirm: true` required) |
| `jellyfish.refresh` | Re-read everything |

Changes made from the JellyFish app show up in HA right away, because the controller
broadcasts every change to all connected clients.

## Install

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add this repo as an
*Integration* → install "JellyFish Lighting (Local)" → restart HA.

**Manual:** copy `custom_components/jellyfish` into your HA `config/custom_components/`
and restart.

Then go to **Settings → Devices & services → Add integration → JellyFish Lighting (Local)** and
enter the controller IP. Controllers are also auto-discovered by their DHCP hostname
(`JellyFish-XXXX`). Give the controller a static DHCP lease.

## Examples

```yaml
# Team colors chase, saved so it also appears in the app
action: jellyfish.run_custom_pattern
target:
  entity_id: light.zone
data:
  type: Chase
  colors: [[0, 32, 91], [255, 255, 255]]
  speed: 5
  direction: Left
  save_as: "Sports/Team"
```

```yaml
# Weekend evening schedule (replaces the daily schedule)
action: jellyfish.set_schedule
data:
  config_entry_id: <your entry id>
  kind: daily
  events:
    - days: [F, SA]
      actions:
        - { type: RUN, startFrom: sunset, hour: 0, minute: 0, patternFile: "Colors/Orange", zones: [Zone] }
        - { type: STOP, startFrom: time, hour: 23, minute: 0, zones: [Zone] }
```

```yaml
# Alert when the controller reboots
trigger:
  - trigger: state
    entity_id: sensor.home_restarts_detected
action:
  - action: notify.notify
    data:
      message: "JellyFish controller restarted"
```

## Protocol notes

The repo includes `jf.py`, a standalone stdlib client for poking at the API from a shell:

```bash
./jf.py '{"cmd":"toCtlrGet","get":[["zones"]]}' 192.168.0.224
```

- Read requests reply only to the client that asked. Changes are broadcast to all clients.
- Saving the zone config turns all lights off.
- `phyPort` matches the LED1-LED4 labels on the board. The JellyFish app showed some
  ports off by one.
- Pattern `data` is a JSON *string*. If any field is missing, the controller silently
  ignores the command, so the integration always sends complete patterns.

## Development

```bash
podman build -t jellyfish-test -f Containerfile.test .
podman run --rm -v "$PWD":/work:Z jellyfish-test python -m pytest -q
```

The tests run against an in-process fake controller (`tests/fake_controller.py`) that
mimics the firmware behavior described above.
