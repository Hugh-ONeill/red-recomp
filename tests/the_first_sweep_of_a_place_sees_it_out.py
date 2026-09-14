#!/usr/bin/env python3
"""explore sees a place out the first time it sweeps there, and the word
"map_change" is not read as a promise to leave the map.

A sweep never steps onto a doorway: the target picker skips every warp
tile. So {"until":"map_change"} names a stop the walking cannot reach, and
every one of this run's seven map_change sweeps ended "nothing more to see
from ground you can reach" (2026-09-14, user: "it wont bring the bot to a
new map but it does explore the whole region"). What the value actually
buys is a sweep that stops for nothing that comes into view.

That is worth having by default on arrival. A sweep that stops at the
first new thing spends a whole round to show one doorway, and the round
costs the same whether it walks four steps or a hundred: Vermilion City
took five rounds to turn up five doors one at a time, while one sweep
that stopped for nothing put 935 cells and six doorways on the page in a
single round (user: "a quick explore of the region to get everything in
sight and then choosing from all the warps now available is the ideal way
of handling a new region"). So the FIRST sweep of a place sees it out;
after that, stopping at the first new thing is right again. The model's
own "until" always wins, and the Safari Zone, where every step is spent
from a fixed allowance, is never swept out by the harness's choice.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# ---- the shim tells the truth about the word --------------------------------
i0 = sh.index("function OPS.sweep(G, c)")
body = sh[i0:sh.index("\nfunction ", i0 + 10)]
ck("a sweep skips every warp tile, so it cannot change the map by walking",
   "if warps[k] or script_holes[k] then" in body)
ck("...and asking for map_change says so in the result",
   "a sweep never steps onto a doorway, so it " in body
   and "cannot change the map by walking" in body, "")
ck("...and says what the value does buy",
   "stops for nothing that comes into view" in body
   and "seen out to every cell a walk from here reaches" in body)
ck("'everything' and 'floor' are the same value",
   'everything = "map_change"' in body and 'floor = "map_change"' in body)

# ---- the vocabulary says it too ---------------------------------------------
ck("the vocabulary states the rule before the value",
   "A SWEEP NEVER STEPS ONTO A DOORWAY, so it cannot change the map by" in ex)
ck("...and why it is the cheapest way to meet a new place",
   "every door and person on it is then on the page" in ex)

# ---- explore's first sweep ---------------------------------------------------
i = ex.index('            _st = {"op": "sweep"}')
blk = ex[i:i + 3000]
ck("the first sweep of a place is told to stop for nothing",
   '_st["until"] = "map_change"' in blk)
# the swept set became one persisted fact, _swept, shared with the header
# that says when the party has never looked around where it stands
ck("...once per place, remembered and persisted",
   "self._note_swept(_reg_now)" in blk and "not self._has_swept(_reg_now)" in blk
   and '"swept": sorted(getattr(self, "_swept", set()))' in ex)
ck("...and never overrides an until the model asked for",
   '_params.get("until") is None' in blk
   and blk.index('for _k in ("until", "steps")') < blk.index('_st["until"] = "map_change"'))
ck("...never where steps are the clock",
   'not (obs or {}).get("safari")' in blk)
ck("...and never on a region with no name", '"None" not in str(_reg_now)' in blk)
ck("...and it is on the record", '"sweep_out_first_visit"' in blk)
ck("the trace says which of the two it ran",
   "seeing this place out, because it is the first sweep" in ex
   and 'else\n                    "sweeping unseen ground")' in ex)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
