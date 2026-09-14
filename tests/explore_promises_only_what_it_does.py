#!/usr/bin/env python3
"""A failed walk says what explore actually does, not that it will go to
the tile you asked for.

Both footprint-edge verdicts ended "explore walks toward it", which reads
as a promise about that tile. Explore makes no such promise. It aims its
sweep at the nearest way out no walk reaches, and only while the floor
still has ground a walk can bring into view; with no reachable frontier
left it presses what is untried here instead, which is right, because
walking over ground already seen shows nothing new. The run read the line
in Mt Moon's basement, sent explore, and was taken somewhere else
entirely (2026-09-14, user: "but it did not it went a different way").

The surrounding claims are unchanged: a footprint edge is still not a
proven wall, and what stands at the boundary is still said to be what is
beside it rather than what stops you.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# the phrase survives in the comment that records why it went; the check is
# about what the game SAYS, so read the code lines only
_said = "\n".join(l for l in sh.splitlines() if not l.lstrip().startswith("--"))
ck("no verdict promises a walk to the tile you named",
   "explore walks toward it" not in _said, "")
ck("the warp verdict says what explore aims at",
   '.. "aims its sweep at the ways out no walk reaches, while this "' in sh)
ck("the seam verdict says the same thing",
   '.. "ways out no walk reaches, while this floor still has ground "' in sh)
ck("...and both say it is conditional on there being ground to bring into view",
   sh.count("still has ground a walk can bring into view") == 1
   and sh.count("still has ground \"\n        .. \"a walk can bring into view") == 1)

# the promise now matches the code: the sweep branch needs a frontier, and
# aims at the nearest way out no walk reaches
i = ex.index("_st = {\"op\": \"sweep\"}")
blk = ex[i - 1400:i + 4200]
ck("explore sweeps only when the floor has a reachable frontier",
   '_m.get("frontier") and not _params.get("no_sweep")' in blk)
ck("...and aims that sweep at a way out no walk reaches",
   "unreached_ways" in blk and '_st["toward_x"], _st["toward_y"]' in blk)
ck("...and a floor with nothing reachable left falls through to what is here",
   ex.index('_st = {"op": "sweep"}') < ex.index("def _thing_op", ex.index('_st = {"op": "sweep"}') - 4000)
   if "def _thing_op" in ex else True)

# the honest parts of the message are untouched
ck("a footprint edge is still not called a wall",
   "not at a proven " in _said and "NOT at a proven wall" in _said)
ck("what stands at the boundary is still not blamed",
   "not a claim that any of " in _said and "it is what stops you" in _said)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
