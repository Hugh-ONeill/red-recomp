#!/usr/bin/env python3
"""A walk made on the water is replayed on the water (2026-09-05).

The run had walked the whole way out of Seafoam bar one door: B3F's 1,0
part, a swim across to its 21,6 part, up the east ladders to 1F|21,12,
where door (26,17) had never been taken.  The swim was stored as a plain
intra-map walk.  `go` replayed it on foot, the walk failed on the water,
the hop took a blocked_at stamp, and three things happened at once:

  - `go` to the far part answered "no walked way is known";
  - explore's picker, which skips any region it cannot route to, lost
    1F|21,12 and B3F|21,6 and walked the party to Route 18 instead
    (user: "when it explores its dragged away from seafoam");
  - the page kept saying "THIS FLOOR HAS ANOTHER PART YOU HAVE WALKED ...
    go replays a route you have walked" — a lie while the leg was dark.

The same stamp on Route 20's 52,2 -> 44,2 swim was why `go FUCHSIA_CITY`
refused from the Seafoam door (user: "why did go fail there anyway").

Door and seam hops have ridden a swim they failed to reach on foot since
2026-08-28 (route_ride_replay.py).  This is the same rule for the walk
hop: an edge remembered as ridden is ridden first; one that is not is
walked, then ridden once if the walk fell short on a floor with water and
someone knows SURF.  A landing clears the block and remembers the ride.
And _note_intra now records `surf` when the party was on the water at
either end of the walk, so the replay can know without a failed walk.
"""
import sys
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

MAP = "SEAFOAM_ISLANDS_B3F"
HOME, FAR = f"{MAP}|1,0", f"{MAP}|21,6"
KEY = f"walk:{FAR}"

def obs_at(region, water=True, surf_known=True, surfing=False):
    return {"mode": "overworld",
            "map": {"id": MAP, "region": region.split("|")[1],
                    "water": {"cells": 120} if water else None},
            "player": {"x": 1, "y": 0, "surfing": surfing},
            "party": [{"moves": [{"id": "SURF"} if surf_known
                                 else {"id": "BITE"}]}],
            "badges": [], "flags": [], "bag": {}}

class Bridge:
    def __init__(self, world): self.w = world
    def obs(self): return self.w.obs()

class World:
    """The map as the shim would answer it: the two parts are joined by
    water, so a walk_to lands only when it rides."""
    def __init__(self, water=True, surf_known=True):
        self.at, self.water, self.surf_known = HOME, water, surf_known
        self.calls, self.logs = [], []
    def obs(self): return obs_at(self.at, self.water, self.surf_known)
    def send(self, op, **kw):
        self.calls.append((op, dict(kw)))
        if op == "walk_to":
            if kw.get("surf") and self.water:
                self.at = FAR
                return {"result": {"ok": True, "detail": "rode there"}}
            return {"result": {"ok": False, "detail":
                    "no path — WATER at (12,6); a walk will not cross water"}}
        return {"result": {"ok": True}}

def rig(world, edge):
    ex = E.Executor.__new__(E.Executor)
    ex.b = Bridge(world)
    ex.explored = {HOME: {KEY: dict(edge)}}
    ex._send_safe = lambda op, **kw: world.send(op, **kw)
    ex.settle = lambda: world.obs()
    ex.log = lambda kind, **kw: world.logs.append((kind, kw))
    ex._save_memory = lambda: None
    ex.handle_battle = lambda sg, o: o
    return ex

SG = {"id": "t"}
PATH = [(KEY, FAR)]

# 1. an edge the ledger does not remember as ridden: walk, then ride once
w = World(); ex = rig(w, {"n": 1, "to": FAR, "intra": True})
ex._walk_route(SG, PATH)
walks = [kw for op, kw in w.calls if op == "walk_to"]
ck("the foot walk is tried first", walks and not walks[0].get("surf"))
ck("...and when it falls short on a water floor, the ride follows",
   len(walks) == 2 and walks[1].get("surf") is True)
ck("the party arrives", w.at == FAR)
ck("the ride is logged as the seam hop's is",
   any(k == "route_hop_surfed" and kw.get("key") == KEY for k, kw in w.logs))
ck("a landing takes no blocked_at stamp",
   "blocked_at" not in ex.explored[HOME][KEY])
ck("the edge now remembers it was ridden",
   ex.explored[HOME][KEY].get("surf") is True)

# 2. an edge remembered as ridden is ridden straight away, and a stale
#    block from the foot-walk days is lifted by the landing
w = World(); ex = rig(w, {"n": 3, "to": FAR, "intra": True, "surf": True,
                          "blocked_at": [6, 286, 19]})
ex._walk_route(SG, PATH)
walks = [kw for op, kw in w.calls if op == "walk_to"]
ck("a remembered swim is ridden first, no failed foot walk",
   len(walks) == 1 and walks[0].get("surf") is True)
ck("the old block is gone once it lands",
   "blocked_at" not in ex.explored[HOME][KEY])

# 3. nobody knows SURF: the old behaviour, exactly
w = World(surf_known=False); ex = rig(w, {"n": 1, "to": FAR, "intra": True})
ex._walk_route(SG, PATH)
walks = [kw for op, kw in w.calls if op == "walk_to"]
ck("no SURF, no ride", len(walks) == 1 and not walks[0].get("surf"))
ck("...and the hop is blocked for this world state",
   ex.explored[HOME][KEY].get("blocked_at") == [0, 0, 0])
ck("...and the walk's own words are kept",
   "WATER" in (ex._route_why or ""))

# 4. a dry floor is never ridden
w = World(water=False); ex = rig(w, {"n": 1, "to": FAR, "intra": True})
ex._walk_route(SG, PATH)
walks = [kw for op, kw in w.calls if op == "walk_to"]
ck("a floor with no water gets no ride", len(walks) == 1)

# 5. the recorder: riding at either end of the walk marks the edge
def recorder():
    ex = E.Executor.__new__(E.Executor)
    ex.explored, ex._faint_at, ex._intra_prev = {}, None, None
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda: None
    return ex
ex = recorder()
ex._note_intra(obs_at(HOME, surfing=False))
ex._note_intra(obs_at(FAR, surfing=True))
ck("arriving on the water marks the walk as ridden",
   ex.explored[HOME][KEY].get("surf") is True)
ex = recorder()
ex._note_intra(obs_at(HOME, surfing=True))
ex._note_intra(obs_at(FAR, surfing=False))
ck("leaving from the water marks it too",
   ex.explored[HOME][KEY].get("surf") is True)
ex = recorder()
ex._note_intra(obs_at(HOME, surfing=False))
ex._note_intra(obs_at(FAR, surfing=False))
ck("a walk on land stays a walk", "surf" not in ex.explored[HOME][KEY])
ex = recorder()
ex.explored = {HOME: {KEY: {"n": 1, "to": FAR, "intra": True,
                            "blocked_at": [6, 286, 19]}}}
ex._note_intra(obs_at(HOME, surfing=False))
ex._note_intra(obs_at(FAR, surfing=True))
ck("a walk made again by hand lifts the block, as a door that opened does",
   "blocked_at" not in ex.explored[HOME][KEY])

# 6. stamps earned under the foot-only rule are lifted once, at load
from pathlib import Path
src = Path("planner/executor.py").read_text()
ck("the ledger lifts old walk stamps once, on load",
   'if not data.get("walks_reopened"):' in src
   and 'str(_k).startswith("walk:")' in src)
ck("...and remembers having done so",
   '"walks_reopened": bool(getattr(' in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
