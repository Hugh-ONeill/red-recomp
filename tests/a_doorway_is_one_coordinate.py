#!/usr/bin/env python3
"""A doorway is one coordinate on the page, wherever doors are listed.

Four wordings of a two-tile doorway have now been read as two doors:
"(4,7)+(5,7)", "(4,7)+(5,7) — ONE doorway, two tiles wide", "[ONE door, 2
tiles wide: (5,7) is the SAME door]" and "(4+5,7)". Run 16, leg 14 (the
S.S. Anne, 2026-09-07): three pages read "door (12+13,5) -> SS_ANNE_B1F|7,3
— the door you came in by; taken", and three rounds the model wrote "exit
through the untried door at (13,5)", took the twin tile and walked back out
where it came from — at (13,15), at (13,5), and at the bow's (13,7). The
lesson the ledger's own comment already drew: any number on the page that
can be read as a coordinate will be. So every list of doors names ONE tile
per doorway, and the width is said in words. The same fold reaches the
far-floor summary, which also counted the door the run came in by (the
cell it landed on) as a plain untried door.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
ex = (ROOT / "planner" / "executor.py").read_text()
lg = (ROOT / "planner" / "ledger.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

d = L.Candidate(key="12,5", kind="door", twins=["13,5"])
lab = d.label()
ck("the row names one tile and says the width in words",
   lab == "door (12,5), two tiles wide")
ck("the twin tile's coordinate is nowhere in the row", "13" not in lab)
d3 = L.Candidate(key="4,0", kind="door", twins=["5,0", "6,0", "7,0"])
ck("a four-tile doorway is 'four tiles wide'", d3.label() == "door (4,0), four tiles wide")
ck("a one-tile door has no width clause",
   L.Candidate(key="3,9", kind="door").label() == "door (3,9)")

ck("the unopened-doors list names the first tile, not 'a+b'",
   "folded.append((g[0], d, who))" in ex and 'folded.append(("+".join(g), d, who))' not in ex)
ck("the local floor note counts doorways and names one tile each",
   "_n_doors = len({_grp.get(k, (k,)) for k in allw})" in ex
   and "open_here = {_grp.get(k, (k,))[0] for k in open_here}" in ex
   and 'has {_n_doors} ' in ex)
ck("the far-floor summary welds twin tiles from door_dests",
   "_grp2 = self._door_groups([" in ex and "_units = {_grp2.get(k, (k,))[0] for k in _doors}" in ex
   and "_mid, len(_units), _open, _far, _barred))" in ex)
ck("...and counts the cell the run landed on as a door it came in by",
   '_stood.add(_r2.split("|", 1)[1])' in ex)
ck("the ledger's unreachable-doors line names one tile per doorway",
   "_firsts.append(_g0[0])" in lg and '_others = ", ".join(f"({t})" for t in _firsts[:6])' in lg)

sh = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim's doorway labels are one coordinate each",
   'table.concat(parts, "+")' not in sh and 'out[#out + 1] = ("(%d,%d)"):format(g[1].x, g[1].y)' in sh)
ck("...and the 'no door at' message lists doorways through them",
   "local here = doorway_labels(here_ws)" in sh)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
