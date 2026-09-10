#!/usr/bin/env python3
"""A drop is a way out, so it is a row like every other way out.

A hole is in no warp table.  That is a true fact about the engine and the
shim says so on purpose -- and it meant a drop was in no doorway row,
which meant nothing that RANKS ways out could ever pick one: not
unreached_ways, not "is this area finished", not explore.

Standing on POKEMON_MANSION_3F with two never-taken drops beside it,
explore's first line sent run 16 to another floor to press a diary.  Those
drops are the only way into the sealed room 1F's basement stairs stand
in.  Leg 40 failed on the basement through four subgoals and two replans
before the user said "yeah build it, make the drops real candidates"
(2026-09-10).

Two things had to come with it.  The row carries its own op, because a
drop is the one exit on the page that takes no use_warp; and explore
mints that op rather than the use_warp it mints for every other door, or
the new row would be one it could only fail at.

Where a drop LANDS is still not said until one has been taken.  Synthetic:
no game, no model.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger                                          # noqa: E402
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "POKEMON_MANSION_3F|5,8"


class _Ex:
    frontier = {}
    _inert_objs = {}
    hints = {}
    def __init__(self, walked=None):
        self.explored = {HERE: {}}
        self.visits = {HERE: 13}
        self._walked = walked or {}
    def _where(self, _o): return HERE
    def _taken_here(self, h): return {}
    def _spent_exits(self, h): return {}
    def _sealed(self, h): return set()
    def _untaken(self, m, t): return set()
    def _worth_another_word(self, h, o, backfill=True): return []
    def _door_groups(self, w): return {}
    def _frontage(self, d): return ""
    def _seen_cells_words(self, h): return ""
    def _walked_dest(self, mid, key): return self._walked.get(key)
    def _snapshot_anywhere(self, o): return None
    def dead_for(self, t, r): return 0
    def __getattr__(self, _n): return {}


def hole(x, y, grp, reach):
    return {"x": x, "y": y, "drop": grp, "reachable": reach}


def world(holes, warps=None):
    m = {"id": "POKEMON_MANSION_3F", "region": "5,8", "objects": [],
         "connections": {}, "holes": holes,
         "warps": warps if warps is not None
         else [{"x": 7, "y": 10, "look": "stairs_down", "reachable": True}]}
    return {"party": [], "map": m, "mode": "overworld",
            "player": {"x": 5, "y": 8}}


HOLES = [hole(16, 14, 1, True), hole(17, 14, 1, True),
         hole(19, 14, 2, False)]
ex = _Ex()
obs = world(HOLES)
cands = ledger.build(ex, obs)
doors = {c.key: c for c in cands if c.kind == "door"}

# ---- the drop is a candidate -------------------------------------------
ck("a drop is a way out on the list", "16,14" in doors)
ck("...drawn as a hole, not a door", doors["16,14"].look == "hole")
ck("...with the other tile of it as one drop, not a second exit",
   doors["16,14"].twins == ["17,14"] and "17,14" not in doors)
ck("...never taken, so untried", doors["16,14"].status == "untried")
ck("a drop no walk reaches is unreachable, not untried",
   doors["19,14"].status == "unreachable")
ck("the ordinary doorway is untouched by any of this",
   doors["7,10"].look == "stairs_down" and doors["7,10"].status == "untried")

# ---- and it counts where ways out are counted --------------------------
uw = ledger.unreached_ways(cands)
ck("an unreachable never-taken drop is a way out never taken",
   [c.key for c in uw] == ["19,14"], [c.key for c in uw])
ck("this floor is not fully worked with a drop untaken on it",
   not ledger.fully_worked(cands))

txt = ledger.render(cands, ex, obs)
first = next(ln for ln in txt.splitlines() if ln.strip().startswith("1. explore"))
ck("explore now reaches for the drop", "hole (16,14)" in first, first[:160])

# ---- the row carries the op that takes it ------------------------------
row = next(ln for ln in txt.splitlines()
           if "hole (16,14)" in ln and not ln.strip().startswith("1."))
ck("the row leads with what a drop IS, not with what it costs",
   row.index("an untried way OFF this floor")
   < row.index("cannot come back up"), row[:200])
ck("...names walk_to, the one op a drop answers",
   '{"op":"walk_to","x":N,"y":N}' in row and "rather than by use_warp" in row)
ck("...and does not claim which floor it lands on",
   "floor below" not in row and "POKEMON_MANSION_1F" not in row)
# A COST SAID FIVE TIMES IS AN ARGUMENT. Beside "stairs down (25,14) ->
# UNKNOWN - never taken from here", the old row said not-a-doorway, no
# climbing back up, and a way down and never a way back, over a header
# that said it twice more; run 16 took those stairs twice and left both
# drops untaken (2026-09-10).
import re as _re                                        # noqa: E402
_ONEWAY = _re.compile(r"come back|climbing back|never a way back|"
                      r"NOT a doorway")
ck("the one-way fact is stated once in the row",
   len(_ONEWAY.findall(row)) == 1, _ONEWAY.findall(row))
_hdr = txt.splitlines()[0]
ck("...and once in the header",
   len(_ONEWAY.findall(_hdr)) == 1, _ONEWAY.findall(_hdr))

# ---- a drop that HAS been taken is not unfinished ground ---------------
ex2 = _Ex(walked={"16,14": "POKEMON_MANSION_1F|1,1"})
c2 = ledger.build(ex2, world(HOLES))
d2 = {c.key: c for c in c2 if c.kind == "door"}
ck("a drop you have fallen down is taken", d2["16,14"].status == "taken")
ck("...and carries where it put you, from the walked atlas",
   d2["16,14"].dest == "POKEMON_MANSION_1F|1,1")
ck("...and is no longer a way out never taken",
   "16,14" not in [c.key for c in ledger.unreached_ways(c2)])

# ---- a hole the warp table already knows is not doubled ---------------
c3 = ledger.build(_Ex(), world([hole(16, 14, 1, True)],
                               warps=[{"x": 16, "y": 14, "look": "hole",
                                       "reachable": True}]))
ck("a drop already in the warp table gets one row, not two",
   len([c for c in c3 if c.kind == "door" and c.key == "16,14"]) == 1)

# ---- explore mints the op the row names --------------------------------
h = ledger.Candidate(key="16,14", kind="door")
h.look = "hole"
d = ledger.Candidate(key="7,10", kind="door")
d.look = "stairs_down"
ck("explore takes a drop by walking onto it",
   E.Executor._take_exit(h) == {"op": "walk_to", "x": 16, "y": 14})
ck("...and every other door with use_warp",
   E.Executor._take_exit(d) == {"op": "use_warp", "x": 7, "y": 10})

# ---- and the shim answers both ops sensibly ---------------------------
SHIM = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim can tell a drop cell from the map's own hole list",
   "local function drop_cell(mapid, x, y)" in SHIM)
ck("use_warp at a drop refuses and names walk_to",
   "is a one-way DROP, not a doorway" in SHIM
   and "You take it by WALKING ONTO IT" in SHIM)
ck("walk_to onto a drop reports falling through as the op working",
   "stepped onto the DROP at (%d,%d) and fell through" in SHIM)
ck("...and that branch is reached before the carried-through-a-door one",
   SHIM.index("stepped onto the DROP")
   < SHIM.index("carried through a DIFFERENT door"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
