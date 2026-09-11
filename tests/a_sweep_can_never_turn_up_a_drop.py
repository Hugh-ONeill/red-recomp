#!/usr/bin/env python3
"""Coverage comes first for every exit, and a drop needs saying anyway.

Explore sweeps unseen ground before it takes an untried exit, because the
ledger only holds what has been on screen and "everything here is done"
can only be true of a floor with no frontier.  A drop gets the same
treatment as a door: it waits its turn.

But a drop sits on ground ALREADY seen, so no amount of sweeping will ever
turn it up as new.  The floor can be swept dry with one standing in the
middle of it, which is how POKEMON_MANSION_3F read for a whole leg: nine
frontier spots, two untaken drops, and every round a sweep that named
neither (user, 2026-09-11: "now the coverage-first rule so drops get
offered").

So the sweep is AIMED at it and the line says it is there, which is the
courtesy an unreachable way out has had since 2026-08-29.  Taking it stays
the model's, because a drop is one-way and its row says so.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


class _Ex:
    frontier = {}
    _inert_objs = {}
    hints = {}
    explored = {"POKEMON_MANSION_3F|1,1": {}}
    visits = {"POKEMON_MANSION_3F|1,1": 17}
    def _where(self, _o): return "POKEMON_MANSION_3F|1,1"
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
    def _frontier_left(self, r): return set()
    def dead_for(self, t, r): return 0
    def __getattr__(self, _n): return {}


def page(holes, frontier):
    m = {"id": "POKEMON_MANSION_3F", "region": "1,1", "objects": [],
         "connections": {}, "holes": holes, "frontier": frontier,
         "seen": {"frontier_n": len(frontier)},
         "warps": [{"x": 6, "y": 1, "look": "stairs_down", "reachable": True}]}
    obs = {"party": [], "mode": "overworld", "player": {"x": 1, "y": 1},
           "map": m}
    ex = _Ex()
    return L.plan_explore(ex, obs, L.build(ex, obs, want_explore=False))


FRONT = [{"x": 12, "y": 16}, {"x": 12, "y": 17}]
HOLE = [{"x": 16, "y": 14, "drop": 1, "reachable": True}]
FAR = [{"x": 16, "y": 14, "drop": 1, "reachable": False}]

with_drop = page(HOLE, FRONT)
no_drop = page([], FRONT)
unreachable = page(FAR, FRONT)

# ---- coverage still leads -----------------------------------------------
ck("the deed is still the sweep, not the drop",
   "walk to the unseen ground" in with_drop, with_drop[:120])
ck("...and still counts the spots", "spot(s) on this floor" in with_drop)

# ---- but the drop is named ----------------------------------------------
ck("the untaken drop is named in the line", "hole (16,14)" in with_drop)
ck("...as a way off this floor never taken",
   "way OFF this floor never taken" in with_drop)
ck("...and why sweeping will not find it",
   "already on screen" in with_drop)

# ---- and nothing is invented when there is none -------------------------
ck("a floor with no drop says nothing about one",
   "hole (" not in no_drop and "walk to the nearest edge" in no_drop)
ck("a drop no walk reaches is not offered as a target",
   "way OFF this floor never taken" not in unreachable)

# ---- the deed says the same thing ---------------------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
blk = SRC.split("AND FAILING THAT, A DROP NOBODY HAS TAKEN", 1)[1][:2200]
ck("the deed aims its sweep at the drop",
   '_st["toward_x"], _st["toward_y"]' in blk)
ck("...only at a reachable, never-taken one",
   'c.status == "untried"' in blk and 'getattr(c, "reachable", False)' in blk)
ck("...and only when no unreachable way out already claimed the aim",
   "if _d0 is None:" in blk)
ck("...saying it once, not twice", "do not say it twice" in blk)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:110] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
