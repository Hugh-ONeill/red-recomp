#!/usr/bin/env python3
"""Naming ground the run has stood on is not naming a way back to it.

An unreachable door's row names a part of the floor the run HAS stood in
that reaches the thing, which is real recall and the reason the row exists.
It said nothing about how to return there.

On POKEMON_MANSION_1F the row read "the ground you stood on in
POKEMON_MANSION_1F|12,14 DOES reach it" about the basement stairs, the
model asked to go to that region, and go answered "no walked way from
POKEMON_MANSION_1F|1,1 to POKEMON_MANSION_1F|12,14 is known".  Three
rounds, the same proposal (2026-09-10).  The only way into that part of
the floor is a DROP from the floor above, and a drop taught the atlas
nothing until the settle fix landed that morning.

The run's own graph settles it: if no exit it has ever taken lands in that
region, go cannot replay a route to it, whatever the visit counter says.
HOW to get in is still the model's.  Synthetic: no game, no model.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger                                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "POKEMON_MANSION_1F|1,1"
FAR = "POKEMON_MANSION_1F|12,14"


class _Ex:
    frontier = {}
    _inert_objs = {}
    hints = {}
    def __init__(self, explored):
        self.explored = explored
        self.visits = {HERE: 70, FAR: 2}
    def _where(self, _o): return HERE
    def _taken_here(self, h): return {}
    def _spent_exits(self, h): return {}
    def _sealed(self, h): return set()
    def _untaken(self, m, t): return set()
    def _worth_another_word(self, h, o, backfill=True): return []
    def _door_groups(self, w): return {}
    def _frontage(self, d): return ""
    def _seen_cells_words(self, h): return ""
    def _walked_dest(self, mid, key): return None
    def _snapshot_anywhere(self, o): return None
    def dead_for(self, t, r): return 0
    def __getattr__(self, _n): return {}


OBS = {"party": [], "mode": "overworld", "player": {"x": 5, "y": 10},
       "map": {"id": "POKEMON_MANSION_1F", "region": "1,1", "objects": [],
               "connections": {},
               "warps": [{"x": 21, "y": 23, "look": "stairs_down",
                          "reachable": False, "from": [FAR]}]}}

# nothing the run has walked lands in the far part
STRANDED = {HERE: {"5,27": {"n": 21, "to": "CINNABAR_ISLAND|10,0"}},
            FAR: {"21,23": {"n": 1, "to": "POKEMON_MANSION_B1F|10,9"}}}
# ...and the same floor once a way in has been recorded
REACHED = {HERE: {"5,27": {"n": 21, "to": "CINNABAR_ISLAND|10,0"}},
           "POKEMON_MANSION_3F|1,1": {"17,14": {"n": 1, "to": FAR}},
           FAR: {"21,23": {"n": 1, "to": "POKEMON_MANSION_B1F|10,9"}}}


def row(explored):
    ex = _Ex(explored)
    txt = ledger.render(ledger.build(ex, OBS), ex, OBS)
    return next(ln for ln in txt.splitlines() if "21,23" in ln and "->" in ln)


stranded, reached = row(STRANDED), row(REACHED)

ck("the recall still names the ground that reaches it",
   f"the ground you stood on in {FAR} DOES reach it" in stranded)
ck("...and says no exit ever taken lands there",
   "NO exit you have taken LANDS there" in stranded)
ck("...naming go as the thing that cannot get back there",
   "go cannot get you back to it" in stranded)
ck("...and the whole caveat survives the note bound",
   "…" not in stranded and stranded.rstrip().endswith("back to it"),
   stranded[-60:])
ck("...and without pointing at a way in",
   "hole" not in stranded.lower() and "drop" not in stranded.lower()
   and "3F" not in stranded)

ck("once a way in is recorded, the caveat goes",
   "NO exit you have taken" not in reached)
ck("...and the recall itself is untouched",
   f"the ground you stood on in {FAR} DOES reach it" in reached)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("\nSTRANDED:", stranded[:500])
    print("\nREACHED:", reached[:500])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
