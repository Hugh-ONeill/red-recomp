"""Where the boulders stood when you walked in.

A shove cannot be undone, and a boulder can be shoved into a cell that kills
the puzzle: VICTORY_ROAD_1F's row-16 corridor is the only way between the
floor's two halves, so a boulder parked in it with the player on the wrong
side can never be pushed again — measured, the solver correctly reports "no
run of shoves ends there".

The floor RELOADING puts them all back, which the run has now watched happen
twice, and nothing recorded it — so the one lever out of a dead position was
invisible (user, 2026-08-24: "not anymore for some reason, its gotta solve
it agian"). The arrival snapshot is the run's own observation; what it means
is the model's to read.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class Ex:
    def __init__(self, start):
        self.boulder_start = {"VICTORY_ROAD_1F": start} if start else {}

    def _where(self, o):
        return f"{o['map']['id']}|{o['player']['x']},{o['player']['y']}"

    def __getattr__(self, k):
        return {}


def page(now, start):
    obs = {"map": {"id": "VICTORY_ROAD_1F", "warps": [],
                   "objects": [{"kind": "boulder", "x": int(c.split(",")[0]),
                                "y": int(c.split(",")[1])} for c in now]},
           "player": {"x": 5, "y": 14}, "party": [], "bag": {}}
    return str(ledger.render([], Ex(start), obs))


MOVED = page(["5,15", "14,2", "2,10"], ["14,2", "2,10", "5,16"])
ck("it says they have moved", "THE BOULDERS HERE HAVE MOVED" in MOVED)
ck("...naming where they were", "(5,16)" in MOVED)
ck("...and where they are", "(5,15)" in MOVED)
ck("...and that a shove cannot be taken back",
   "cannot be taken back" in MOVED)
ck("...and that arriving put them back last time",
   "put them back where they started" in MOVED)

SAME = page(["5,16", "14,2", "2,10"], ["14,2", "2,10", "5,16"])
ck("unmoved boulders say nothing", "THE BOULDERS HERE HAVE MOVED" not in SAME)

ck("no arrival snapshot, no claim",
   "THE BOULDERS HERE HAVE MOVED" not in page(["5,15"], []))
ck("no boulders at all, no claim",
   "THE BOULDERS HERE HAVE MOVED" not in page([], ["5,16"]))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
