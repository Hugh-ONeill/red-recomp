"""A door you cannot walk to on a floor that still has ground never on
screen is not behind a wall, and nothing is said to be in its way.

Mt Moon B2F, run 16 (2026-09-07): the exit ladder (5,7) lay past ground
never on screen.  The door's own line said so -- "its way in is ground you
have not stood on: unseen ground on this floor" -- and two other lines on
the same page said otherwise: "THIS MAP HOLDS MORE THAN ONE ROOM: the
door(s) ... (5,7) are on it but not reachable from where you stand -- walls,
not obstacles" and "A doorway does not move, so something between you and it
does not want you through yet".  The model believed the two, gave up on the
floor and climbed back out to Route 4 (user: "the untried ladder should be
on its frontier list ... where else can it even go?").

The shim counts the cells where the whole floor's seen ground ends
(seen.frontier_map_n).  While that is above zero, both notes say the doors
may lie past that ground and that standing where the seen ground ends is
how it comes into view.  Only a floor searched to its edge is walls.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lsrc = Path("planner/ledger.py").read_text()
esrc = Path("planner/executor.py").read_text()
ck("the ledger reads the whole floor's frontier before calling anything a wall",
   '_fmap = int(((m.get("seen") or {}).get("frontier_map_n")) or 0)' in lsrc
   and "if _fmap > 0:" in lsrc)
ck("...and with unseen ground left it says the doors may lie past it",
   'DOORS ON THIS FLOOR YOU CANNOT WALK TO FROM "' in lsrc
   and 'the seen ground ends), and the way to them may "' in lsrc)
ck("...and calls them walls only when every seen cell is searched to its edge",
   'walls, not obstacles: every "' in lsrc)
ck("the executor's doorway line reads the same count",
   '.get("frontier_map_n") or 0)' in esrc and "if _fmap > 0:\n                shut_line = (" in esrc)
ck("...and infers something in the way only on a floor searched to its edge",
   '"so something between you and it does not want you "' in esrc
   and '"floor that has been on screen is searched to its edge, "' in esrc)
ck("...and otherwise says the way may run through the unseen ground",
   '"these may run through that ground. Standing where the "' in esrc)
ck("the shim reports the whole-floor count",
   "frontier_map_n = fmap" in Path("harness/shim.lua").read_text())

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
