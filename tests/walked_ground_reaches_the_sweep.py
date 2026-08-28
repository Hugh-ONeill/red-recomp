#!/usr/bin/env python3
"""The sweep and the already-done judge are shown where the run has been,
for the places each objective names.

They were told to point only at "the item is in the bag, the badge is
earned, the event has fired", and shown the state and the events, never
the walked record — so "Navigate the Safari Zone", every Safari map stood
in and lit end to end, could never be shown done and was authored four
times (user, 2026-08-28: "didn't skip the safari zone leg despite that
whole area being explored").
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

ids = ["SAFARI_ZONE_CENTER", "SAFARI_ZONE_EAST", "SAFARI_ZONE_GATE", "SAFARI_ZONE_SECRET_HOUSE",
       "CINNABAR_ISLAND", "CINNABAR_GYM", "ROUTE_20", "VICTORY_ROAD_1F", "FUCHSIA_CITY"]
ck("'Navigate the Safari Zone' names the whole Safari family",
   A.maps_named("Navigate the Safari Zone", ids) == ["SAFARI_ZONE_CENTER", "SAFARI_ZONE_EAST", "SAFARI_ZONE_GATE", "SAFARI_ZONE_SECRET_HOUSE"])
ck("'Reach Cinnabar Island' names the island and not its gym",
   A.maps_named("Reach Cinnabar Island", ids) == ["CINNABAR_ISLAND"])
ck("'Reach Route 20' names the route", A.maps_named("Reach Route 20", ids) == ["ROUTE_20"])
ck("'Defeat Koga for the Soul Badge' names no map", A.maps_named("Defeat Koga for the Soul Badge", ids) == [])

tmp = Path(tempfile.mkdtemp(prefix="ground_")); (tmp / "run").mkdir(); os.chdir(tmp)
(tmp / "run/explored.json").write_text(json.dumps({"visits": {
    "SAFARI_ZONE_CENTER|2,1": 20, "SAFARI_ZONE_CENTER|14,0": 7, "SAFARI_ZONE_EAST|1,1": 12,
    "SAFARI_ZONE_GATE|3,0": 30, "SAFARI_ZONE_SECRET_HOUSE|2,2": 3, "ROUTE_20|44,2": 14}}))
(tmp / "run/seen.json").write_text('return {\n  ["SAFARI_ZONE_CENTER"] = { ' + ",".join(f'"{i},0"' for i in range(1440)) + " },\n"
                                   '  ["SAFARI_ZONE_EAST"] = { ' + ",".join(f'"{i},0"' for i in range(900)) + " },\n}\n")
A._MAP_DIMS = {"SAFARI_ZONE_CENTER": (40, 36), "SAFARI_ZONE_EAST": (40, 36), "CINNABAR_ISLAND": (20, 18)}
text = A.walked_ground_text([(38, "Navigate the Safari Zone"), (39, "Obtain the Secret Key"),
                             (40, "Reach Cinnabar Island")], observed="run/explored.json")
ck("the Safari leg is shown its maps, stood-in counts and tiles seen",
   "38. Navigate the Safari Zone: SAFARI_ZONE_CENTER stood in 27x, 1440/1440 tiles seen" in text
   and "SAFARI_ZONE_EAST stood in 12x, 900/1440 tiles seen" in text)
ck("...a map never stood in is said so", "CINNABAR_ISLAND never stood in, 0/360 tiles seen" in text)
ck("...an objective naming no place gets no line", "39. Obtain the Secret Key" not in text)
ck("...and the header says where the facts come from", "from the walked record" in text)
ck("no places named, no paragraph", A.walked_ground_text([(1, "Defeat Koga")], observed="run/explored.json") == "")

captured = []
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"]); return '{"why": "x", "done": []}'
A.brock_probe.chat = fake_chat
A.recent_events = lambda: ""
A.done_ledger_text = lambda *a, **k: ""
A.sweep_already_done([(38, "Navigate the Safari Zone")], "start", "m", observed="run/explored.json")
ck("the sweep sees it", "WHERE THE RUN HAS BEEN" in captured[-1] and "SAFARI_ZONE_CENTER stood in 27x" in captured[-1])
A.brock_probe.chat = lambda msgs, model: (captured.append(msgs[-1]["content"]) or '{"why": "x", "done": false}')
A.check_already_done("Navigate the Safari Zone", "start", "m", observed="run/explored.json")
ck("so does the already-done judge", "WHERE THE RUN HAS BEEN" in captured[-1])
ck("and both prompts let walked ground be pointed at",
   "the ground has been walked" in A.SWEEP_SYS and "has been walked" in A.ALREADY_SYS)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
