"""In-process fake JellyFish controller speaking the real websocket protocol.

Behavior mirrors what firmware 4.6.1 was observed to do: gets reply only to the
asker, sets are broadcast to every client, saving zones resets run state.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from aiohttp import WSMsgType, web

BOOT_DATA = json.dumps(
    {"colors": [100, 100, 100], "spaceBetweenPixels": 2,
     "effectBetweenPixels": "No Color Transform", "type": "Color", "skip": 1,
     "numOfLeds": 1, "runData": {"speed": 10, "brightness": 100, "effect": "No Effect",
     "effectValue": 0, "rgbAdj": [100, 100, 100]}, "direction": "Left"},
    separators=(",", ":"),
)

SPOOKY = {
    "colors": [0, 166, 0, 105, 0, 201, 255, 46, 0, 0, 0, 0], "spaceBetweenPixels": 2,
    "effectBetweenPixels": "No Color Transform", "colorPos": [-1], "cursor": -1,
    "type": "Chase", "skip": 1, "numOfLeds": 1,
    "runData": {"speed": 0, "brightness": 100, "effect": "No Effect", "effectValue": 0,
                "rgbAdj": [100, 100, 100]},
    "direction": "Left",
}


def initial_state() -> dict[str, Any]:
    return {
        "ctlrName": "Home",
        "hostName": "JellyFish-2AB3.local",
        "version": {"details": "4.1.7-154-ge9b2887", "isUpdate": False, "ver": "4.6.1"},
        "timeConfig": {"lat": 39.0, "locName": "Example - Springfield", "lon": 105.0,
                       "timezone": "MST7MDT,M3.2.0,M11.1.0", "timezoneName": "MST"},
        "zones": {
            "Zone": {"numPixels": 137, "portMap": [
                {"ctlrName": "JellyFish-2AB3.local", "phyEndIdx": 79, "phyPort": 3,
                 "phyStartIdx": 0, "zoneRGBStartIdx": 0},
                {"ctlrName": "JellyFish-2AB3.local", "phyEndIdx": 56, "phyPort": 1,
                 "phyStartIdx": 0, "zoneRGBStartIdx": 80}]},
            "Garage": {"numPixels": 20, "portMap": [
                {"ctlrName": "JellyFish-2AB3.local", "phyEndIdx": 19, "phyPort": 2,
                 "phyStartIdx": 0, "zoneRGBStartIdx": 0}]},
        },
        "patterns": {
            "Halloween/Spookier01": (True, SPOOKY),
            "Colors/Orange": (True, {**SPOOKY, "type": "Color", "colors": [255, 80, 0]}),
            "Mine/Custom": (False, {**SPOOKY, "type": "Color", "colors": [1, 2, 3]}),
        },
        "states": {
            "Zone": {"activatedBy": "network_command", "data": json.dumps(SPOOKY),
                     "file": "Halloween/Spookier01", "id": "Zone", "state": 1,
                     "zoneName": ["Zone"]},
            "Garage": {"data": BOOT_DATA, "file": "", "id": "Garage", "state": 0,
                       "zoneName": ["Garage"]},
        },
        "daily": [{"actions": [
            {"hour": 0, "minute": 0, "patternFile": "Halloween/Spookier01",
             "startFrom": "sunset", "type": "RUN", "zones": ["Zone"]},
            {"hour": 0, "minute": 0, "patternFile": "", "startFrom": "sunrise",
             "type": "STOP", "zones": ["Zone"]}], "days": ["S", "M"], "label": ""}],
        "calendar": [],
    }


class FakeController:
    def __init__(self) -> None:
        self.state = initial_state()
        self.received: list[dict[str, Any]] = []
        self.clients: set[web.WebSocketResponse] = set()
        self.runner: web.AppRunner | None = None
        self.port: int = 0
        self.ignore_gets = False  # simulate a hung controller

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/ws", self._ws)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001

    async def stop(self) -> None:
        for ws in list(self.clients):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()

    async def drop_all(self) -> None:
        for ws in list(self.clients):
            await ws.close()

    def reboot(self) -> None:
        for name, st in self.state["states"].items():
            self.state["states"][name] = {"data": BOOT_DATA, "file": "", "id": name,
                                          "state": 0, "zoneName": [name]}

    def sets(self, key: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m.get("cmd") == "toCtlrSet" and key in m]

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                req = json.loads(msg.data)
                self.received.append(req)
                if req["cmd"] == "toCtlrGet":
                    if not self.ignore_gets:
                        for reply in self._get(req["get"][0]):
                            await ws.send_str(json.dumps(reply))
                else:
                    for reply in self._set(req):
                        for client in list(self.clients):
                            await client.send_str(json.dumps(reply))
        finally:
            self.clients.discard(ws)
        return ws

    def _get(self, args: list[str]) -> list[dict[str, Any]]:
        s = self.state
        res, *rest = args
        base = {"cmd": "fromCtlr"}
        if res in ("ctlrName", "hostName", "version", "timeConfig"):
            return [{**base, res: s[res]}]
        if res == "zones":
            return [{**base, "save": True, "zones": s["zones"]}]
        if res == "patternFileList":
            items = []
            for folder in sorted({p.split("/")[0] for p in s["patterns"]}):
                items.append({"folders": folder, "name": "", "readOnly": False})
                for path, (ro, _) in s["patterns"].items():
                    if path.startswith(folder + "/"):
                        items.append({"folders": folder, "name": path.split("/", 1)[1],
                                      "readOnly": ro})
            return [{**base, "patternFileList": items}]
        if res == "patternFileData":
            folder, name = rest
            _, data = s["patterns"][f"{folder}/{name}"]
            return [{**base, "patternFileData": {"folders": folder, "name": name,
                                                 "jsonData": json.dumps(data)}}]
        if res == "runPattern":
            return [{**base, "runPattern": s["states"][z]} for z in rest]
        if res == "scheduleDaily":
            return [{**base, "events": s["daily"], "schedule": "daily"}]
        if res == "scheduleCalendar":
            return [{**base, "events": s["calendar"], "schedule": "calendar"}]
        return []

    def _set(self, req: dict[str, Any]) -> list[dict[str, Any]]:
        s = self.state
        base = {"cmd": "fromCtlr"}
        if "runPattern" in req:
            rp = copy.deepcopy(req["runPattern"])
            if rp.get("file") and not rp.get("data"):
                rp["data"] = json.dumps(s["patterns"][rp["file"]][1])
            out = {"activatedBy": "network_command", "data": rp["data"], "file": rp["file"],
                   "id": rp["zoneName"][0], "state": rp["state"], "zoneName": rp["zoneName"]}
            for zone in rp["zoneName"]:
                s["states"][zone] = {**out, "id": zone}
            return [{**base, "runPattern": out}]
        if "zones" in req:
            s["zones"] = req["zones"]
            self.reboot()
            return [{**base, "save": True, "zones": s["zones"]}]
        if "patternFileData" in req:
            pf = req["patternFileData"]
            s["patterns"][f"{pf['folders']}/{pf['name']}"] = (False, json.loads(pf["jsonData"]))
            return [{**base, "patternFileData": pf}]
        if "patternFileDelete" in req:
            pf = req["patternFileDelete"]
            s["patterns"].pop(f"{pf['folders']}/{pf['name']}", None)
            return [{**base, "patternFileDelete": pf}]
        if "schedule" in req:
            s[req["schedule"]] = req["events"]
            return [{**base, "schedule": req["schedule"], "events": req["events"]}]
        if "ctlrName" in req:
            s["ctlrName"] = req["ctlrName"]
            return [{**base, "ctlrName": req["ctlrName"]}]
        return []
