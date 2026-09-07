#!/usr/bin/env python3
"""A ball pressed where it no longer lies is gone, not elsewhere.

Rocket Hideout B4F, run 16 (2026-09-07): the Rocket dropped the Lift Key,
the run took it, and the ball's sighting ITEM_ROCKET_HIDEOUT_B4F_10_2
stayed in the never-pressed count. The model pressed it four times; the
shim's reply, written for a ball named from another map, said "go to that
map first" while the run stood on that map, and the far-floor line kept
saying B4F "still has 1 thing never pressed" — the phantom item the user
watched it go back for. Now: the shim reads the map out of the ball's own
name and, when it is this map, says the ball has been taken; the executor
marks it gone; the ledger's never-pressed count leaves gone things out.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
sh = (ROOT / "harness" / "shim.lua").read_text()
ex_src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the shim reads the ball's map out of its name",
   'match("^ITEM_(.-)_%d+_%d+$")' in sh)
ck("...and says taken, not elsewhere, when that map is this one",
   "you saw there has been taken, and a ball taken is gone for" in sh
   and sh.find("has been taken, and a ball taken is gone") < sh.find("Go to that map", sh.find("has been taken, and a ball taken is gone")))
ck("the executor marks such a ball gone", 'if op == "interact" and "has been taken, and a ball taken is gone" in note:' in ex_src
   and "self._gone.setdefault(here, set()).add(key)" in ex_src)
fake = types.SimpleNamespace(sightings={"B4F|17,1": ["ITEM_B4F_10_2", "ITEM_B4F_9_4", "ROCKET3"]},
                             _tried_objs={"B4F|17,1": {"ITEM_B4F_9_4", "ROCKET3"}},
                             _gone={"B4F|17,1": {"ITEM_B4F_10_2"}})
ck("the never-pressed count leaves gone things out", L.untouched_in(fake, "B4F|17,1") == [], L.untouched_in(fake, "B4F|17,1"))
fake._gone = {}
ck("...and still counts a thing that is there", L.untouched_in(fake, "B4F|17,1") == ["ITEM_B4F_10_2"])
# ...AND A THING PRESSED FROM THE NEXT PART OVER IS PRESSED (B3F's Rockets, 2026-09-07)
fake2 = types.SimpleNamespace(sightings={"B3F|9,5": ["ROCKET1", "ROCKET2", "ITEM_26_17"]},
                              _tried_objs={"B3F|9,5": {"ITEM_26_17"}, "B3F|18,16": {"ROCKET1", "ROCKET2"}}, _gone={})
ck("a thing pressed from another part of the same floor is not 'never pressed' here",
   L.untouched_in(fake2, "B3F|9,5") == [], L.untouched_in(fake2, "B3F|9,5"))
fake2._tried_objs = {"B3F|9,5": {"ITEM_26_17"}, "B2F|1,1": {"ROCKET1"}}
ck("...but a same-named thing on another floor does not count",
   L.untouched_in(fake2, "B3F|9,5") == ["ROCKET1", "ROCKET2"])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
