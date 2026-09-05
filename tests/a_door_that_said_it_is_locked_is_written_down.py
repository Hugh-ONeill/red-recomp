#!/usr/bin/env python3
"""A door that answered "The door is locked..." is written down as shut.

2026-09-05, live on Cinnabar. The party stood on the gym's mat and the shim
answered, in as many words:

  use_warp(x=18,y=3): FAILED — you reached the door and it refused to open
  — the game said: "The door is locked...". You stood on the mat; walking
  somewhere else and coming back will not change the answer.

Nothing recorded it. Cinnabar's blocker ledger was empty, the edge did not
exist, and (18,3) sat in the frontier as an exit never taken — so explore
chose it, the game said locked, the ledger was identical afterwards, and
the next round chose it again (user: "it somehow went to try the gyms door"
... "this also brought it back to the gym door"). The harness told the
model the answer would not change and then asked the question again itself.

The outcome recorder had a branch for a person standing on the doorstep, a
branch for a script that interrupted the walk, and a branch for a door that
spoke without opening. It had none for the plain refusal, which is the one
shape a LOCKED door uses.

The world mark is recorded with it, so the reopening rule is untouched: a
locked door is worth exactly one more press once the party carries
something it was not carrying then, which is what a key is. Nothing here
refuses the op — the model may press it whenever it likes. What changes is
that the frontier stops calling it a way never tried.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import executor as E                                  # noqa: E402
import candidates as C                                # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

HERE = "CINNABAR_ISLAND|10,0"
GYM = "18,3"
NOTE = ('use_warp(x=18,y=3): FAILED — you reached the door and it refused '
        'to open — the game said: "The door is locked...". You stood on the '
        'mat; walking somewhere else and coming back will not change the '
        'answer. — it said: "The door is locked..."')
OBS = {"map": {"id": "CINNABAR_ISLAND", "region": "10,0", "warps": []},
       "player": {"x": 18, "y": 4}, "party": [],
       "badges": ["B1"] * 6, "flags": ["f"] * 295, "bag": {"X": 1}}

def rig():
    ex = C.make()
    ex.explored = {HERE: {}}
    ex.blockers = {}
    ex._outcomes = {}
    ex._cur_target = "badge:VOLCANOBADGE"
    ex.hints = {}
    ex.touched = {}
    ex.frontier = {HERE: [GYM, "6,3", "east"]}
    ex._no_cross = {}
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda *a, **k: None
    return ex

ex = rig()
ex._record_outcome(OBS, "use_warp", {"x": 18, "y": 3}, NOTE)

edge = (ex.explored.get(HERE) or {}).get(GYM) or {}
ck("the door is marked shut", edge.get("shut") is True)
ck("...with the world it was shut in", edge.get("shut_at") == [6, 295, 1])
ck("...and is not claimed as a door that was taken", edge.get("n") == 0)
ck("...nor claimed to lead anywhere", edge.get("to") is None)

blk = ex.blockers.get(f"{HERE}|{GYM}") or {}
ck("a blocker is written where the run can read it", bool(blk))
ck("...in the game's own words", "The door is locked" in str(blk))
ck("...and it is the game's line and nothing else",
   blk.get("what") == '"The door is locked..."')
ck("...with nothing invented about what would lift it",
   blk.get("lifts") is None and not blk.get("lifts_note"))
ck("...and it counts as a door, not a person or a seam",
   blk.get("kind") == "door")

# what the frontier does with it, which is the whole point
ex._mark_now = [6, 295, 1]
left = ex._frontier_left(HERE)
ck("the frontier stops calling it a way never tried", GYM not in left)
ck("...while the other untried ways are untouched",
   "6,3" in left and "east" in left)

# the reopening rule is untouched: carry something new and it is worth a
# press again, which is exactly what a key is
ex._mark_now = [6, 295, 2]
ck("it is offered again once the party is carrying something new",
   GYM in ex._frontier_left(HERE))

# a door that could not be REACHED is a different fact and must not be shut
ex2 = rig()
ex2._record_outcome(OBS, "use_warp", {"x": 18, "y": 3},
                    "use_warp(x=18,y=3): FAILED — couldn't reach the warp "
                    "tile (no path)")
ck("couldn't-reach is still not the same as refused",
   not ((ex2.explored.get(HERE) or {}).get(GYM) or {}).get("shut"))

# and a door that opened is not shut by this branch
ex3 = rig()
ex3._record_outcome(OBS, "use_warp", {"x": 6, "y": 3},
                    "use_warp(x=6,y=3): ok (map->POKEMON_MANSION_1F, moved, "
                    "warped)")
ck("a door that opened is left alone",
   not ((ex3.explored.get(HERE) or {}).get("6,3") or {}).get("shut"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
