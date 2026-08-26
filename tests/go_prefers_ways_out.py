"""A bare map name goes to the part with the most ways on (2026-08-26).

`go MAP` took the NEAREST walked part, and the nearest part of a map is
routinely the worst one: ROUTE_7|18,12 is a pocket whose single recorded exit
is back east, and the run crossed into it four times; ROUTE_14|16,6 is a
four-cell nook. User: "can we route it to somewhere that isnt a pocket? ...
unless its stated that were aiming for the pocket we should go to the area
that has the most movement options".

Ways out first, distance second. Naming MAP|region still overrides it — that
is the "unless it is stated" half — and every alternative is still listed with
both numbers, so nothing is chosen in silence."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find('"NEAREST" IS THE WRONG DEFAULT FOR A BARE MAP NAME')
ck("the ranking exists", i > 0)
blk = src[i:i + 2600]

ck("ways out are counted from walked exits and untried ones",
   "def _ways(r):" in blk and "self.explored.get(r)" in blk
   and "self._frontier_left(r)" in blk)
ck("...ignoring an edge that loops back to itself",
   '(e or {}).get("to") != r' in blk)
ck("ranked by ways out first, legs second",
   "key=lambda rn: (-_ways(rn[0]), rn[1])" in blk)
ck("only for a BARE map name",
   '"|" not in str(want)' in blk)
ck("...and only when more than one part is reachable",
   "len(_reachable) > 1" in blk)
ck("a named region is still taken as given",
   "that choice is taken as given" in blk)
ck("the other parts are still listed, with both numbers",
   "way(s) out)" in blk and "leg(s)," in blk)
ck("it says WHY it did not take the nearest",
   "not the nearest" in blk and "often a corner" in blk)
ck("a failed re-route falls back rather than breaking",
   "if _p2:" in blk)

# behaviour on the live atlas shape
import json
d = json.loads(Path("run/explored.json").read_text())
ex = E.Executor.__new__(E.Executor)
ex.explored = d["explored"]
ex._frontier_left = lambda r: []
def ways(r):
    outs = {(e or {}).get("to") for e in (ex.explored.get(r) or {}).values()
            if (e or {}).get("to") and (e or {}).get("to") != r}
    return len(outs)
r7 = sorted((r for r in ex.explored if r.startswith("ROUTE_7|")),
            key=lambda r: -ways(r))
ck(f"ROUTE_7 ranks {r7[0]} above the pocket",
   r7[0] == "ROUTE_7|0,2" and ways("ROUTE_7|18,12") == 1)
r12 = sorted((r for r in ex.explored if r.startswith("ROUTE_12|")),
             key=lambda r: -ways(r))
ck("ROUTE_12 ranks the 3-way part first", r12[0] == "ROUTE_12|0,61")

# --- and the single-part dead end, which no ranking can help ---
j = src.find("AND WHEN THERE IS ONLY ONE PART, AND IT IS A DEAD END")
ck("a lone dead-end part is called out", j > 0)
dblk = src[j:j + 3000]
# the comment quotes the phrasing it forbids; test the code only
_dsaid = "\n".join(l for l in dblk.splitlines()
                   if not l.lstrip().startswith("#"))
ck("...only for a bare map name with nowhere else to go",
   '"|" not in str(want) and _ways(best[0]) <= 1' in dblk)
ck("it names what its recorded ways out lead back to", "_outs" in dblk)
ck("SEEN is not confused with WALKED",
   "SEEN but never " in _dsaid and "STOOD ON" in _dsaid
   and "never seen" not in _dsaid)
ck("...and the frontier count decides which half of that sentence",
   "map_seen" in dblk and "_fr_here == 0" in dblk)
ck("a closed box says explore cannot get out either",
   "explore finds no way on " in dblk)
ck("it still refuses to say where the rest IS",
   "is not recorded" in _dsaid
   and "may be another map entirely" in _dsaid)

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
