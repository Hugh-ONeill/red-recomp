"""A field move that could not be placed says WHICH thing failed (2026-08-26).

field_move's adjacency refusal has three cases. Two were explained — somebody
standing on the tiles you would use it from, and none of the four tiles being
walkable at all. The third returned seven bare words, "no reachable tile
adjacent to the target", and it is the awkward one: a tile beside the target
IS ground the reach map says you can walk to, and the approach walk still did
not arrive (a step budget run out, a wanderer moving into the way, a one-way
drop).

It fired twice on ROUTE_13 while the ledger's own entry 1 read "CUT the bush
at (34,4) — a party Pokemon knows CUT and it is a way on" (user: "uh oh its in
the rt 14 pocket")."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()

ck("the bare refusal is gone",
   'return false, "no reachable tile adjacent to the target"\n' not in lua)
i = lua.find("AND THE THIRD CASE, WHICH SAID NOTHING AT ALL")
ck("the third case is explained", i > 0)
blk = lua[i:i + 1800]

ck("it names the tiles that ARE reachable",
   'reach[a[1] .. "," .. a[2]]' in blk and "_ok[#_ok + 1]" in blk)
ck("...and says it is the WALK that failed, not the ground",
   "this is the WALK failing, not the ground" in blk)
ck("it offers the causes without picking one",
   "step budget" in blk and "moving into the way" in blk
   and "one-way drop" in blk)
ck("it names the op that separates them",
   'walk_to' in blk and "then the move" in blk)
ck("it decides nothing",
   not re.search(r"(?i)(you should|instead|give up|do not)",
                 " ".join(re.findall(r'"([^"]*)"', blk))))

# the other two branches are untouched
ck("the occupied-tile branch still explains itself",
   "standing " in lua and "on the tiles you would use it from: " in lua)
ck("the no-side branch still explains itself",
   "none of " in lua and "the four tiles around (%d,%d) is ground you can walk to from " in lua)
ck("...and still names what stands between",
   "bushes_blocking(G, c.x, c.y, reach)" in lua)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
