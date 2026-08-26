"""A seam you cannot walk to is not an exit from here (2026-08-26).

A connection belongs to the MAP, not to the pocket you stand in. The nine-cell
strip at the top of Route 6 — the bit the Saffron gate opens onto — listed

  3. walk south -> VERMILION_CITY|18,0 — never taken from here

with no caveat, while every DOOR and every object on the same page carried "you
cannot walk to it from where you stand". The run read the south road as open,
could not take it, and concluded the gate guard was blocking it — after that
guard had just said "Hi, thanks for the cool drinks!" (user: "but then it went
out and north back into saffron").

Only the NEGATIVE is claimed: no reached cell touches that side at all.
Touching it is not proof the crossing is there, and cross() still decides."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import ledger as L

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# --- the shim publishes it ---
lua = Path("harness/shim.lua").read_text()
i = lua.find("AND WHETHER A WALK FROM HERE EVEN REACHES THAT EDGE")
ck("the shim publishes per-side reachability", i > 0)
blk = lua[i:i + 2200]
ck("...from the reached set, against each edge",
   "reachable_cells()" in blk
   and "_cr.north = true" in blk and "_cr.south = true" in blk
   and "_cr.west = true" in blk and "_cr.east = true" in blk)
ck("...in cells, not blocks", ") * 2" in blk)
ck("...published beside connections",
   "o.map.connections_reach = _cr" in blk)

# --- the ledger marks it ---
led = Path("planner/ledger.py").read_text()
j = led.find("AND A SEAM YOU CANNOT WALK TO IS NOT AN EXIT FROM HERE")
ck("the ledger marks an unreachable seam", j > 0)
lblk = led[j:j + 1400]
ck("...only when the shim actually said so",
   "if _cr and not _cr.get(d)" in lblk)
ck("...and only for a seam not already taken or sealed",
   'c.status in ("untried", "back")' in lblk)
ck("it says what it means, without claiming the crossing is gone",
   "touches that side of this map" in lblk
   and "no ground you can walk to from here" in lblk)

# --- an unreachable seam already feeds the honest 'ways never taken' line ---
src = led
k = src.find("def unreached_ways")
ck("an unreachable seam counts as a way never taken",
   'c.kind in ("door", "seam") and c.status == "unreachable"'
   in src[k:k + 900])
ck("and 'you cannot walk to it from where you stand' is its wording",
   L._STATUS_WORDS["unreachable"]
   == "you cannot walk to it from where you stand")

# --- an old shim (no field) changes nothing ---
ck("absent connections_reach leaves every seam as it was",
   'm.get("connections_reach") or {}' in lblk
   and 'isinstance(' in lblk)

import ast
try:
    ast.parse(src); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
