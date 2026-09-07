"""A doorway is one door in every count, including the ones that say a
floor has parts you have never stood on.

Viridian Forest's south gate (run 16, 2026-09-07): the north door is two
tiles, (4,0) and (5,0).  The reach search got to (5,0) and not (4,0), and
the same page that folded them -- "door (5,0) [ONE door, 2 tiles wide:
(4,0) is the SAME door, not another]" -- went on to say "THIS MAP HOLDS
MORE THAN ONE ROOM: the door(s) (4,0) are on it but not reachable from
where you stand -- walls, not obstacles" and "THIS FLOOR IS NOT FINISHED
... 1 of them (4,0) are on part of it you have never stood on".  Two
readers of the warp list counted tiles; one relation (_door_groups) says
what is one door, and now both readers use it.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

warps = [{"x": 4, "y": 0, "dest": "VIRIDIAN_FOREST", "reachable": False},
         {"x": 5, "y": 0, "dest": "VIRIDIAN_FOREST", "reachable": True},
         {"x": 4, "y": 7, "dest": "LAST_MAP", "reachable": True},
         {"x": 5, "y": 7, "dest": "LAST_MAP", "reachable": True}]
g = E.Executor._door_groups(warps)
ck("the two north tiles are one door", set(g.get("4,0", ())) == {"4,0", "5,0"})
ck("...and not the south door's", "4,7" not in g.get("4,0", ()))

# the ledger's other-room note folds by the same relation
lsrc = Path("planner/ledger.py").read_text()
ck("the other-room note skips a tile whose doorway has a reachable tile",
   "_unreach = [w0 for w0 in (m.get(\"warps\") or [])" in lsrc
   and "and not any(t in _reach for t in _groups.get(" in lsrc)
# the executor's unfinished-floor count too
esrc = Path("planner/executor.py").read_text()
ck("the unfinished-floor count folds doorway tiles",
   "_known_wide = {t for k in _known for t in _grp.get(k, (k,))}" in esrc
   and "unseen = allw - _known_wide" in esrc)
# the arithmetic the count now does, on this gate
here_keys, ever, stood = {"5,0"}, {"4,7"}, set()
allw = {f"{w['x']},{w['y']}" for w in warps}
known = here_keys | ever | stood
known_wide = {t for k in known for t in g.get(k, (k,))}
ck("with (5,0) at hand and (4,7) taken, no tile of this gate is unseen floor",
   not (allw - known_wide))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
