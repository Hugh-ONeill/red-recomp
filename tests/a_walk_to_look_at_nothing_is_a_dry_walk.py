#!/usr/bin/env python3
"""A walk to look at nothing is a dry walk, wherever the walk happened.

explore ranks an area by the unseen ground counted for it and walks the
party there; enough walks that show nothing new send the area to the
bottom band of the list.  There are three ways for a walk to show
nothing, and for a long time only one of them counted.

  * a REMOTE sweep that swept and turned up no new cell -- counted since
    2026-08-29;
  * an arrival whose counted spot turned out to lie in a chamber no walk
    from the landing reaches, so there was no sweep to read at all --
    Rock Tunnel's entrance chamber, six arrivals in one attempt, each
    round ending as it arrived (2026-09-03, leg 24);
  * a LOCAL sweep, of the ground the party is already standing in, which
    never counted at all.  Viridian's sleeping old man is the case: he
    walls the north exit, seven of eighteen sweeps ended at him, five saw
    nothing, and the dry_walks ledger stayed empty the whole time
    (2026-09-13, user: "otherwise itll go to the blocker and not explore
    anywhere else").

All three now count through one helper, at one threshold.  The count is
CUMULATIVE: a productive sweep no longer wipes what the wasted ones
earned, because a region that gives up one cell every other visit would
otherwise sit near the top of the ranking for ever.  Viridian ran 80, 80,
20, 0, 0, 90, 0, 16, 0, 0 -- four useful walks bought six wasted ones a
clean slate twice over.  The threshold is four rather than two BECAUSE it
no longer resets (2026-09-13, user: "go with cumulative, threshold 4 to
start").

What it buys is a demotion, not a ban: the region drops to the bottom
BAND of explore's ranking and is still walked when nothing ranks above it.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


# ---- the counter itself -------------------------------------------------
def _fake():
    """An object with just enough of the executor to count a dry walk."""
    o = types.SimpleNamespace(_dry_walks={}, _saves=0)
    o.log = lambda *a, **k: None
    o._save_memory = lambda: setattr(o, "_saves", o._saves + 1)
    o.DRY_WALKS_RETIRE = E.Executor.DRY_WALKS_RETIRE
    o._count_dry_walk = types.MethodType(E.Executor._count_dry_walk, o)
    return o

N = E.Executor.DRY_WALKS_RETIRE
ck("the threshold is four to start", N == 4, N)

o = _fake()
DRY = ["swept 12 tile(s)", "0 cell(s) newly on screen"]
WET = ["swept 12 tile(s)", "20 cell(s) newly on screen"]

ck("a sweep that showed nothing counts",
   o._count_dry_walk("VIRIDIAN_CITY|1,1", DRY) == []
   and o._dry_walks == {"VIRIDIAN_CITY|1,1": 1})
ck("...and is persisted", o._saves == 1)
ck("a sweep that showed something does not count",
   o._count_dry_walk("VIRIDIAN_CITY|1,1", WET) == []
   and o._dry_walks == {"VIRIDIAN_CITY|1,1": 1})
ck("...AND DOES NOT RESET WHAT THE DRY ONES EARNED -- this is the whole "
   "of the cumulative change",
   o._dry_walks.get("VIRIDIAN_CITY|1,1") == 1)

for _ in range(N - 2):
    ck("...nothing is said before the threshold",
       o._count_dry_walk("VIRIDIAN_CITY|1,1", DRY) == [])
said = o._count_dry_walk("VIRIDIAN_CITY|1,1", DRY)
ck("the Nth dry walk says so, naming the count and the region",
   len(said) == 1 and f"{N} walk(s)" in said[0]
   and "VIRIDIAN_CITY|1,1" in said[0]
   and "ranks LAST for explore" in said[0], said)
ck("...and it keeps saying so after",
   len(o._count_dry_walk("VIRIDIAN_CITY|1,1", DRY)) == 1)
ck("...and a productive sweep still does not undo it",
   o._count_dry_walk("VIRIDIAN_CITY|1,1", WET) == []
   and o._dry_walks["VIRIDIAN_CITY|1,1"] > N)

ck("a region walked productively from the start never retires",
   _fake()._count_dry_walk("R|1,1", WET) == [])

o2 = _fake()
ck("no trace to read means the walk counts anyway -- the arrival whose "
   "spot was in an unreachable chamber",
   o2._count_dry_walk("ROCK_TUNNEL_1F|3,3") == []
   and o2._dry_walks == {"ROCK_TUNNEL_1F|3,3": 1})

o3 = _fake()
ck("a region with no name is not counted",
   o3._count_dry_walk("", DRY) == [] and o3._dry_walks == {})
ck("...and neither is the shape a missing map leaves behind",
   o3._count_dry_walk("None|None", DRY) == [] and o3._dry_walks == {})

ck("one region's dry walks are not another's",
   (lambda x: (x._count_dry_walk("A|1,1", DRY),
               x._count_dry_walk("B|1,1", DRY),
               x._dry_walks == {"A|1,1": 1, "B|1,1": 1})[-1])(_fake()))


# ---- and all three sites go through it ----------------------------------
ck("the LOCAL sweep counts its dry walks",
   "self._count_dry_walk(self._where(obs), tr)" in src)
ck("the REMOTE sweep counts its dry walks",
   "t2 += self._count_dry_walk(region, t2)" in src)
i_dry = src.index("nothing here is left to look at from where you")
i_exits = src.index("if _map_goal and exits2:            # same rule as at home")
seg = src[i_dry - 1200:i_exits]
ck("the arrival with nothing to look at counts its dry walk",
   "_retired = self._count_dry_walk(region)" in seg)
ck("...only when the area was chosen for its unseen ground",
   "        if unseen:\n" in seg)
ck("...and says it in the round, naming the count and the region",
   "spot(s) counted for {region} are in" in seg
   and "ranks LAST for explore from now on" in seg)
ck("nothing bumps the ledger behind the helper's back -- the one write "
   "in the file is the helper's own",
   src.count("self._dry_walks[") == 1, src.count("self._dry_walks["))

# ---- the picker reads the same threshold --------------------------------
ck("the picker demotes at the same number the counter retires at",
   "if _dry >= self.DRY_WALKS_RETIRE:\n                _pri = 3" in src)
ck("...to the bottom BAND, which is a demotion and not a ban",
   "_pri = 3" in src and "_pri = 4" not in src)

# ---- and it survives a restart ------------------------------------------
ck("the ledger is saved with the rest of memory",
   '"dry_walks": getattr(self, "_dry_walks", {})' in src)
ck("...and read back", 'self._dry_walks = data.get("dry_walks", {}) or {}' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
