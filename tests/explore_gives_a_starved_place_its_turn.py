#!/usr/bin/env python3
"""Explore round-robins over the places it has walked to, and the page
says when the party has never looked around where it stands.

Two halves of one failure. Explore ranked by band, then locality, then
goalward, then DISTANCE, and in a run holding a hundred walked areas
there is always a loose end one leg away, so the far frontier was
unreachable by explore in practice, for ever. ROUTE_10|14,52 was the
case: six spots of unseen ground and a west edge never crossed, six legs
off through Rock Tunnel, the only region on the board that could open new
map, and explore never once chose it while Cerulean and Vermilion had
ends to tidy. The file already solves this shape elsewhere, in the
remote-hints round robin ("every room reachable gets its first sentence
before any room gets its second"), so the picker now prefers, inside a
band, the region it has walked to least.

And a leg can finish on the step that ARRIVES somewhere: leg 16 completed
the instant the run stood on that far mouth, and leg 17 opened by healing
back through the tunnel. It had stood on the far side and never looked
south from it. The header now says so where the party stands, and says
nothing about what is out there (2026-09-14).
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402
import ledger as L                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ex_src = (ROOT / "planner" / "executor.py").read_text()
lg_src = (ROOT / "planner" / "ledger.py").read_text()

# ---- the ranking ------------------------------------------------------------
i = ex_src.index("_goal = ledger.goalward_tier(self, region, here, target)")
blk = ex_src[i:i + 2200]
ck("the picker counts how often explore has walked to a region",
   '_picks = min(int((getattr(self, "_explore_picks", None) or {})' in blk)
ck("...capped, so a place worked a few times rejoins the field",
   ".get(region, 0) or 0), 3)" in blk)
ck("...and weighs it BEFORE distance",
   "r = (_pri, _stale, _local, _goal, _picks, len(path), _way_here," in blk)
ck("...but after band, staleness, locality and goalward, which still lead",
   blk.index("_pri, _stale, _local, _goal, _picks") > 0)
ck("the count is kept where explore records a walk",
   'self._explore_picks[region] = int(' in ex_src)
ck("...and outlives the attempt",
   '"explore_picks": getattr(self, "_explore_picks", {})' in ex_src
   and 'self._explore_picks = data.get("explore_picks") or {}' in ex_src)

# the tuple orders the way the comment says
def rank(picks, legs):
    return (0, 0, 0, 0, min(picks, 3), legs)
ck("a place never walked to beats one walked twice, though it is farther",
   rank(0, 6) < rank(2, 1))
ck("...and among places walked equally often, nearest still wins",
   rank(1, 2) < rank(1, 6))
ck("...and the cap stops a place being banished for ever",
   rank(9, 2) == rank(3, 2))

# ---- swept ground is one persisted fact --------------------------------------
o = types.SimpleNamespace(_swept=set())
for m in ("_has_swept", "_note_swept"):
    setattr(o, m, types.MethodType(getattr(E.Executor, m), o))
ck("ground not yet swept says so", not o._has_swept("ROUTE_10|14,52"))
o._note_swept("ROUTE_10|14,52")
ck("...and once swept, says so", o._has_swept("ROUTE_10|14,52"))
o._note_swept("ROUTE_10|14,52")
ck("...and noting it again changes nothing", o._swept == {"ROUTE_10|14,52"})
ck("...and it writes no memory of its own: it rides with the rest",
   "_save_memory" not in (ROOT / "planner" / "executor.py").read_text()
   .split("def _note_swept")[1].split("def ")[0])
o._note_swept("None|None"); o._note_swept("")
ck("a region with no name is never recorded", o._swept == {"ROUTE_10|14,52"})
ck("it is saved with the rest of memory",
   '"swept": sorted(getattr(self, "_swept", set()))' in ex_src
   and 'self._swept = set(data.get("swept") or ())' in ex_src)
ck("the first-sweep-sees-it-out rule reads the same fact",
   "and not self._has_swept(_reg_now)" in ex_src)
ck("...and a remote sweep records it too",
   ex_src.count("self._note_swept(") == 2)

# ---- the header -------------------------------------------------------------
ck("the header asks the executor whether this ground was ever swept",
   "if _fh and not ex._has_swept(here):" in lg_src)
ck("...and says it plainly, with the count", "YOU HAVE NEVER LOOKED AROUND HERE:" in lg_src
   and "spot(s) \"\n                     f\"where the ground you have seen ends" in lg_src)
ck("...and says nothing about what is out there",
   "what is past them is not \"\n                     f\"known" in lg_src)
i2 = lg_src.index("YOU HAVE NEVER LOOKED AROUND HERE")
ck("...only when there is reachable ground left to look at",
   '_fh = int(_sn.get("frontier_n") or 0)' in lg_src[i2 - 900:i2])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
