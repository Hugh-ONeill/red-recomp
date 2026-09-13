#!/usr/bin/env python3
"""The run's own history said WHAT it had done and never WHERE.

Run 17, leg 7 (2026-09-13). The author was shown, second and third in this
very line, EVENT_MET_BILL and EVENT_USED_CELL_SEPARATOR_ON_BILL — and
wrote a plan that travelled to FUCHSIA_CITY and into
FUCHSIA_BILLS_GRANDPAS_HOUSE to find "Bill's mother", four legs south of
the house where the run had just done both of those things. Every piece
validated, because Bill's grandpa's house is a real map in this game.

The place is not a hint about what to do. It is the same history the event
name already is, the run keeps it in flag_sites keyed by region, and it
was simply never handed over. Joining them is the difference between "you
have met Bill" and "you met Bill in Bill's house".

Only events that fired ONCE get a place, and only the map: a family of
twenty beaten trainers has no single where, and a region suffix is noise
at this altitude.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                         # noqa: E402
from pinned_world import pin_world                         # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

JOURNAL = [{"kind": "flag_fired", "flag": f} for f in
           ("EVENT_BEAT_BROCK", "EVENT_MET_BILL",
            "EVENT_USED_CELL_SEPARATOR_ON_BILL",
            "EVENT_BEAT_ROUTE_3_TRAINER_0", "EVENT_BEAT_ROUTE_3_TRAINER_1")]
pin_world(
    explored={"BILLS_HOUSE|0,2": {}, "PEWTER_GYM|4,4": {}},
    journal=JOURNAL,
    flag_sites={"EVENT_MET_BILL": "BILLS_HOUSE|0,2",
                "EVENT_USED_CELL_SEPARATOR_ON_BILL": "BILLS_HOUSE|0,2",
                "EVENT_BEAT_BROCK": "PEWTER_GYM|4,4",
                "EVENT_BEAT_ROUTE_3_TRAINER_0": "ROUTE_3|1,1",
                "EVENT_BEAT_ROUTE_3_TRAINER_1": "ROUTE_3|9,9"})
# pinned_world writes extras as run/<name>.json; flag_sites lives INSIDE
# explored.json, so put it there the way the run does
_ex = json.loads(Path("run/explored.json").read_text())
_ex["flag_sites"] = json.loads(Path("run/flag_sites.json").read_text())
Path("run/explored.json").write_text(json.dumps(_ex))

line = A.recent_events()
ck("the line exists at all", "ALREADY DONE" in line)
ck("...and now says WHERE as well as what", "and WHERE" in line)
ck("a one-off event carries the map it fired on",
   "EVENT_MET_BILL (at BILLS_HOUSE)" in line)
ck("...the one that mattered included",
   "EVENT_USED_CELL_SEPARATOR_ON_BILL (at BILLS_HOUSE)" in line)
ck("...and another, somewhere else",
   "EVENT_BEAT_BROCK (at PEWTER_GYM)" in line)
ck("the MAP only, never the region inside it",
   "|0,2" not in line and "|4,4" not in line)
# the family collapse rewrites EVERY number, so ROUTE_3_TRAINER_0/1 become
# one ROUTE_N_TRAINER_N — and a family has no single place to name
ck("a collapsed family of many gets no single place",
   "EVENT_BEAT_ROUTE_N_TRAINER_N x2" in line
   and "EVENT_BEAT_ROUTE_N_TRAINER_N x2 (at" not in line)

# an event with no recorded site is still listed, bare
_ex["flag_sites"].pop("EVENT_MET_BILL")
Path("run/explored.json").write_text(json.dumps(_ex))
line2 = A.recent_events()
ck("an event the run never sited is named without a place",
   "EVENT_MET_BILL," in line2 or line2.rstrip(".").endswith("EVENT_MET_BILL"))
ck("...while the others keep theirs",
   "EVENT_USED_CELL_SEPARATOR_ON_BILL (at BILLS_HOUSE)" in line2)

# a missing or broken ledger must never cost the prompt
Path("run/explored.json").write_text("not json at all")
ck("an unreadable record still produces the line",
   "ALREADY DONE" in A.recent_events())

SRC = (ROOT / "planner" / "author.py").read_text()
ck("the places come from the run's own flag_sites, not a table",
   '_d.get("flag_sites")' in SRC)
ck("...and are read defensively", "except (OSError, ValueError):" in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
