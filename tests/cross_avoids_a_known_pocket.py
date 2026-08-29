"""Do not cross into a pocket the atlas has already mapped (2026-08-26).

`cross` picks a gap on the edge — always the same one — and from ROUTE_13 that
gap lands in ROUTE_14|16,6, a nook whose one recorded way out is straight back.
`_uncork_seam` has known how to try another cell since 08-19 and only fires
AFTER the run is stuck inside it (user: "we shouldnt be routing it
automatically into the pocket in the first place, a generic cross west lands it
in the pocket to begin with").

The atlas already says where this seam lands from here. If that landing is a
dead end, cross at another cell. WHICH CELL of a seam to use is pathfinding —
the call _uncork_seam itself documents as "the direction stays the model's" —
and the direction is untouched."""
import sys, json, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("DO NOT WALK INTO A POCKET WE HAVE ALREADY MAPPED")
ck("the guard exists", i > 0)
blk = src[i:i + 2400]

ck("it reads the landing from the atlas, not a guess",
   'self.explored.get(_h0) or {})' in blk and '.get("to")' in blk)
ck("a pocket is defined by the helper: only way out comes back here, and never entered from elsewhere",
   "self._is_pocket(_lands, _h0)" in blk)
ck("it crosses at another cell rather than refusing",
   'step = dict(step, skip=1)' in blk)
ck("the direction is never changed", 'step["dir"]' in blk
   and "dir=" not in blk.split("step = dict(step, skip=1)")[1][:200])
ck("a skip the model asked for is never overridden",
   'if step.get("skip") is None:' in blk)
ck("it is said out loud in the trace",
   "_skipped_why" in blk and "another cell of the same edge was used" in blk)
ck("...and logged", 'self.log("cross_skip_pocket"' in blk)
ck("the trace line carries it on the ok path",
   "_note += _skipped_why" in src)

# behaviour against the live atlas: both known pockets, no false positives

def _atlas():
    """The richest ledger on disk: the live one is whatever chain is running
    (a fresh chain starts it empty); the Hall of Fame world's is archived
    beside it as explored.<ts>.pre-discovery.bak.json."""
    cands = sorted(Path("run").glob("explored*.json"), key=lambda f: f.stat().st_size)
    return json.loads(cands[-1].read_text())

ex = _atlas()["explored"]
def fires(here, dirn):
    lands = ((ex.get(here) or {}).get(dirn) or {}).get("to")
    if not lands or lands == here:
        return False
    outs = {(e or {}).get("to") for e in (ex.get(lands) or {}).values()
            if (e or {}).get("to") and (e or {}).get("to") != lands}
    return bool(outs and outs <= {here})
ck("fires on ROUTE_13 west (the ROUTE_14 nook)",
   fires("ROUTE_13|50,0", "west"))
ck("fires on SAFFRON west (the ROUTE_7 pocket that ate four crossings)",
   fires("SAFFRON_CITY|12,0", "west"))
ck("does NOT fire on CERULEAN east (ROUTE_9 has more ways out)",
   not fires("CERULEAN_CITY|26,7", "east"))
ck("does NOT fire on ROUTE_6 south (Vermilion is a real place)",
   not fires("ROUTE_6|0,3", "south"))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
