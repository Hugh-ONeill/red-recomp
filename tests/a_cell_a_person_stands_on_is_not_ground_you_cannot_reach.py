#!/usr/bin/env python3
"""A cell somebody is standing on is not ground you cannot get to (2026-09-05).

In the Safari Zone's Secret House the only seen-but-unwalkable cell was (3,3) —
the FISHING GURU's own tile, the man the leg was for — and the head line
reported it exactly as it reports a walled-off corner: "1 cell(s), nearest
(3,3); no part of this map you have stood in reaches it". The plan read "a
Fishing Guru who is currently unreachable" and went looking for another door,
while option 1 on the same page was "press the Fishing Guru here". You never
walk onto a person; standing beside them is the whole of reaching them.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
HERE = "SAFARI_ZONE_SECRET_HOUSE|2,2"
ex = E.Executor.__new__(E.Executor)
for _n, _v in dict(
        visits={HERE: 2}, explored={}, frontier={}, _no_cross={}, _no_cross_at={},
        _exit_tries={}, sightings={}, searched={}, dead_ends={}, _gone={}, seen_far={},
        blockers={}, _cut_bushes={}, map_forced={}, map_holes={}, door_dests={},
        _shelves={}, _shelf_machine=set(), _shelf_reads={}, _offered={}, _wild_lv={},
        _wild_seen={}, region_seen={}, frontier_here={}, touched={}, hints={}, hints_at={},
        _inert_objs={}, _outcomes={}, _touch_mark={}, _dead_ops={}, _dead_at={}, _dead_why={},
        _unreached_at={}, _region_mark={}, _plan_hist={}, _world_visits={}, _stuck_in={},
        _parts_by_map={}, region_anchors={}, _bad_seam=set(), _shut_settings={},
        _reach_settings={}, flag_sites={}, contested={}, _dry_walks={}, _ghost_said="",
        shut_doors={}, map_seen={}, _grind_exp={}, _retalked=set(), _cur_target="item:HM_SURF",
        _mark_now=[5, 200, 20]).items():
    setattr(ex, _n, _v)
ex._where = lambda o: HERE
ex._route = lambda a, b: None
ex.log = lambda *a, **k: None

def page(objects, near):
    obs = {"mode": "overworld", "player": {"x": 2, "y": 5}, "bag": {},
           "map": {"id": "SAFARI_ZONE_SECRET_HOUSE", "region": "2,2", "warps": [],
                   "connections": {}, "objects": objects, "frontier": [],
                   "seen_unreached": {"n": len(near), "near": near, "from": []}}}
    return L.render(L.build(ex, obs, "item:HM_SURF"), ex, obs, "item:HM_SURF")

GURU = {"name": "SAFARIZONESECRETHOUSE_FISHING_GURU", "kind": "npc", "x": 3, "y": 3, "reachable": True}
t = page([GURU], [{"x": 3, "y": 3}])
ck("the cell a reachable person stands on is named as such",
   "(3,3) is where SAFARIZONESECRETHOUSE_FISHING_GURU STANDS" in t, t[:600])
ck("...and says you never walk onto a person", "you never walk onto a person" in t, t[:600])
ck("...and that beside them is the whole of reaching them",
   "standing beside them is the whole of reaching them" in t, t[:600])
ck("...and that it says nothing about pressing them",
   "says nothing about whether you can press them" in t, t[:600])
t2 = page([], [{"x": 0, "y": 0}])
ck("ordinary walled-off ground is unchanged",
   "GROUND YOU HAVE SEEN BUT CANNOT WALK TO FROM HERE" in t2 and "STANDS" not in t2, t2[:400])
FAR = dict(GURU, reachable=False)
t3 = page([FAR], [{"x": 3, "y": 3}])
ck("a person the page itself calls unreachable is not claimed to be pressable", "STANDS" not in t3, t3[:400])
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:500]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
