#!/usr/bin/env python3
"""The ground a leg's runs walked for the first time, by map, is put in
front of the rungs that can add a step.

"Reach Cinnabar Island" walked ten new parts of the Seafoam Islands and
the missing rung, asked whether a step was missing, was shown none of
it; it answered nothing and the chain stopped. User, 2026-08-27: "if
something has a ton of new ground walked it probably deserves its own
leg." leg_delta now counts new ground by map, the yield ledger keeps it,
and the missing and later rungs read the sum over the leg's runs.
"""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A            # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

tmp = Path(tempfile.mkdtemp(prefix="ground_")); (tmp / "run").mkdir(); os.chdir(tmp)
# leg_delta groups by map
def state(areas):
    (tmp / "run/obs.json").write_text(json.dumps({"flags": [], "bag": {}, "badges": [], "party": [], "map": {"id": "X"}}))
    (tmp / "run/explored.json").write_text(json.dumps({"visits": {a: 1 for a in areas}}))
def delta(mode):
    return subprocess.run([sys.executable, str(ROOT / "planner/leg_delta.py"), mode, "run/snap.json"],
                          capture_output=True, text=True, cwd=tmp).stdout.strip()
def seen(**maps):
    (tmp / "run/seen.json").write_text("return {\n" + "".join(
        f'  ["{m}"] = {{ ' + ",".join(f'"{i},0"' for i in range(n)) + " }},\n" for m, n in maps.items()) + "}\n")
seen(ROUTE_20=40); state(["ROUTE_20|44,2"]); delta("snap")
seen(ROUTE_20=350, SEAFOAM_ISLANDS_B2F=142, SEAFOAM_ISLANDS_1F=60)
state(["ROUTE_20|44,2", "SEAFOAM_ISLANDS_1F|3,2", "SEAFOAM_ISLANDS_B1F|11,0", "SEAFOAM_ISLANDS_B1F|20,2",
       "SEAFOAM_ISLANDS_B2F|11,4", "ROUTE_20|52,2"])
t = delta("diff")
ck("new ground is counted by map", "by map: SEAFOAM_ISLANDS_B1F x2" in t and "ROUTE_20 x1" in t and "5 place(s)" in t)
ck("new tiles seen are counted by map, from the footprint's own mask",
   "512 tile(s) seen for the first time — by map: ROUTE_20 +310, SEAFOAM_ISLANDS_B2F +142, SEAFOAM_ISLANDS_1F +60" in t)
seen(ROUTE_20=350); state(["ROUTE_20|44,2"]); delta("snap")
seen(ROUTE_20=420); state(["ROUTE_20|44,2"])
t = delta("diff")
ck("new tiles alone, with no new region, are a yield", t.startswith("WHAT CHANGED") and "70 tile(s)" in t)
seen(ROUTE_20=420); delta("snap"); t = delta("diff")
ck("the same mask twice is not", t.startswith("NOTHING"))

# the sum over a leg's runs, old and new row formats alike
G = "Reach Cinnabar Island"
(tmp / "run/attempt_yield").write_text(
    f"{G}\t37\t1\tWHAT CHANGED WHILE THIS LEG RAN — 3 place(s) entered for the first time: ROUTE_19|13,0, ROUTE_20|44,2, SEAFOAM_ISLANDS_1F|3,2.\n"
    f"{G}\t37\t3\tWHAT CHANGED WHILE THIS LEG RAN — events that fired: EVENT_X; 6 place(s) entered for the first time — by map: SEAFOAM_ISLANDS_B1F x2, SEAFOAM_ISLANDS_B2F x2, SEAFOAM_ISLANDS_B3F x1, SEAFOAM_ISLANDS_B4F x1.\n")
(tmp / "run/attempt_yield").write_text((tmp / "run/attempt_yield").read_text()
    + f"{G}\t37\t3\tWHAT CHANGED WHILE THIS LEG RAN — 300 tile(s) seen for the first time — by map: SEAFOAM_ISLANDS_B4F +204, ROUTE_20 +96; 1 place(s) entered for the first time — by map: SEAFOAM_ISLANDS_B4F x1.\n")
tl = A.new_tiles_by_map(G)
ck("tiles are summed over the runs", tl == {"SEAFOAM_ISLANDS_B4F": 204, "ROUTE_20": 96})
g = A.new_ground_by_map(G)
ck("both row formats are summed", g.get("SEAFOAM_ISLANDS_1F") == 1 and g.get("SEAFOAM_ISLANDS_B1F") == 2 and g.get("ROUTE_19") == 1)
text = A.new_ground_text(G)
ck("the text leads with the tiles, then the parts",
   "300 tile(s) seen for the first time, by map: SEAFOAM_ISLANDS_B4F +204" in text
   and "10 part(s) entered for the first time" in text and "SEAFOAM_ISLANDS_B1F x2" in text
   and text.index("tile(s)") < text.index("part(s)"))
ck("...and leaves the judgement to the model", "yours to say" in text)
ck("no record, no words", A.new_ground_text("Defeat Blaine") == "")

captured = []
def fake_chat(msgs, model):
    captured.append(msgs[-1]["content"]); return '{"why": "x", "insert": null}'
A.brock_probe.chat = fake_chat
A.done_ledger_text = lambda *a, **k: ""
A.check_already_done = lambda *a, **k: False
A.check_missing(G, [(37, G), (38, "Defeat Blaine")], "start", "m")
ck("the missing rung sees the yield record and the new ground",
   "WHAT EACH RUN AT THIS OBJECTIVE YIELDED" in captured[-1] and "GROUND THIS OBJECTIVE'S RUNS WALKED" in captured[-1])
fake2 = lambda msgs, model: (captured.append(msgs[-1]["content"]) or '{"why": "x", "after": null}')
A.brock_probe.chat = fake2
A.check_later(G, 37, [(37, G), (38, "Defeat Blaine")], "start", "", "m")
ck("so does the later rung", "GROUND THIS OBJECTIVE'S RUNS WALKED" in captured[-1])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
