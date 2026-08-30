"""A bush is felled because it bars the path, not because it is there.

The room sweep fells every reachable CUT_TREE in the room whenever a round
achieves nothing. Crossing SOUTH into Vermilion lands the party at (19,0) on
the north seam, and the sweep walked it the length of the city to the gym's
bush and cut that — a bush which bars nothing at all, on a map the run was
only passing through (user, 2026-08-30: "when crossing we dont need to use
cut unless its actually barring the path, crossing south into vermillion
moves us to the cut tree next to the gym and cuts it automatically").

Pressing A on a bush is no better: it does nothing and marks the bush spent,
which is how Cerulean's east bush — the road to Rock Tunnel — stayed standing
with CUT in the party for hours. So the sweep does neither. It says the bush
is there, that it can be walked to, and that the party carries the move; the
walk is a cost and the ground behind it is a want, and both are the model's.

The same lie had a second home: the walk refusal names bushes in three lists
and heads the third "Also near that edge, though not what stopped you". The
re-cut searched the whole text, so it could fell the very bush the shim had
just ruled out.
"""
import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
# The sweep's sentences are wrapped across adjacent literals, so a
# check on the source reads the wrapping, not the words. Join them
# first and the checks below are about what the model is told.
def _flat(t): return re.sub(r'"\s*\n\s*f?"', "", t)

# --- the sweep ---
i = src.find("A BUSH IS NOT SWEPT EITHER")
ck("the sweep says why it no longer fells", i > 0)
# the window spans the collection, the press loop and the trace
blk = src[i:i + 8200]
flat = _flat(blk)
ck("...a reachable bush is collected, not swept",
   "_bushes = [" in blk and 'o.get("kind") == "cut_tree"' in blk
   and 'o.get("reachable")' in blk)
ck("...and dropped from the list the sweep presses A on",
   'loose = [n for n in loose if kinds.get(n) != "cut_tree"]' in blk)
ck("...so no field_move rides the sweep loop",
   'self._send_safe("field_move", move="CUT"' not in blk)
ck("...and the sweep's old fell log is gone with it",
   'self.log("sweep_cut"' not in src)
ck("the bush is NAMED with where it stands",
   "stands' if _one else 'stand" in blk and "_bn = " in blk)
ck("...with the op that clears it, on the model's word",
   'field_move' in blk and '\\"move\\":' in blk
   and '\\"x\\":{_bx}' in blk)
ck("...and the claim it makes is honest about what was tried",
   "everything reachable here that PRESSES has now been tried"
   in flat)
# THE ROOM WHOSE ONLY UNTOUCHED THING IS A BUSH is the case this was written
# for: Vermilion. Bushes leaving `loose` must not put them behind a guard
# that tests `loose`.
ck("a bush-only room still sweeps and still speaks",
   "if loose or (_bushes and knows_cut):" in blk)
ck("...and claims nothing was pressed when nothing was",
   "if _pressed:" in blk)
ck("...saying plainly that the sweep declined to fell it",
   "The sweep did NOT fell " in blk)

# --- the re-cut ---
j = src.find("AND ONLY A BUSH THE REPORT BLAMES")
ck("the route re-cut is scoped to the blaming half", j > 0)
rblk = src[j:j + 1200]
ck("...cutting the text at the shim's own disclaimer",
   'split(\n                        "Also near that edge, though not what '
   'stopped you")[0]' in rblk)
ck("...and searching only that half",
   re.search(r"_re\.search\(\s*r\"CUT_TREE.*?\",\s*\n\s*_blame\)",
             rblk, re.S) is not None)
# the disclaimer is the shim's, verbatim: if its wording moves, this split
# silently stops splitting, so the two are checked against each other.
shim = (ROOT / "harness" / "shim.lua").read_text()
ck("the disclaimer this splits on is the shim's own words",
   "Also near that edge, though not what stopped you" in shim)

# --- AND THE HARNESS SAYS WHICH ONE IS IN THE WAY ---
# The rule needs the fact behind it, or the model is left to guess at
# something the flood already knows. ROUTE_9|0,8 is the case: a nine-cell
# pocket whose east seam is a bush that GREW BACK, so the ledger retired it
# as a recut, the pocket read fully worked, and explore walked at a wall.
shim_src = (ROOT / "harness" / "shim.lua").read_text()
k = shim_src.find("AND WHETHER FELLING IT WOULD OPEN ANYTHING")
ck("the shim computes whether felling one opens ground", k > 0)
sblk = shim_src[k:k + 1600]
ck("...as walkable ground on the far side that no walk reaches",
   "lm:isWalkableCell(nx, ny)" in sblk and "not stand_ok(" in sblk)
ck("...published on the object, and absent when it opens nothing",
   "opens = _opens or nil," in sblk)
ck("...claiming only that, never how much lies behind it",
   "opens_n" not in sblk and "cells beyond" not in sblk)

led = (ROOT / "planner" / "ledger.py").read_text()
ck("a regrown bush across the only way out is a way on again",
   'if _again and o.get("opens"):' in led and "_again = False" in led)
ck("...and says so in its own words",
   "it is across the only way out of the " in led)
ck("an ordinary regrown bush is still a recut",
   '"recut" if _again else "cuttable"' in led)
ck("the sweep's line marks the one that is in the way",
   "ground NO walk from here reaches" in blk)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
