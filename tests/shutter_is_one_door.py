"""A Silph card-key shutter is ONE door, not two (2026-08-26).

The shutters are drawn two cells tall or wide and were minted one object per
TILE: six entries on 9F for three doors (18,4 + 19,4; 3,8 + 3,9; 18,10 +
19,10). That doubles every "N thing(s) never pressed" count on every Silph
floor, and the second half is a round spent on a door already answered — after
DOOR_SILPH_CO_9F_11_12 said "Bingo! The CARD KEY opened the door!", the very
next op pressed DOOR_SILPH_CO_9F_11_13 and got "no reachable tile adjacent to
target", because there was no door there any more (user: "the shutter doors
register as two objects, they should only register as one").

The engine's own unit settles it: OverworldController:tryCardKeyDoor does
replaceBlock(floor(fx/2), floor(fy/2)), so both cells of a block ARE one
shutter and open together."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()
i = lua.find("A SHUTTER IS ONE DOOR, AND THE ENGINE SAYS SO")
ck("the shim groups shutter tiles", i > 0)
blk = lua[i:i + 3000]

ck("...on the engine's own block, not on tile adjacency",
   "math.floor(cx / 2)" in blk and "math.floor(cy / 2)" in blk)
ck("one object per block, named at its first cell",
   'kind = "shut_door"' in blk and blk.count('o.map.objects[#o.map.objects + 1]') == 1
   and 'head.x, head.y' in blk)
ck("the other cells ride along as twins, not dropped",
   "twins[#twins + 1]" in blk and "twins = (#twins > 0) and twins or nil" in blk)
ck("reachable is true if ANY cell of it can be walked up to",
   "if adjacent_reachable(c.x, c.y, false) then reach = true end" in blk)
ck("the 11F door tile is still handled apart",
   "silphCo11F" in blk)

# --- the ledger carries and says it ---
led = Path("planner/ledger.py").read_text()
ck("an object's twins reach the candidate",
   "c.twins = [f\"{t.get('x')},{t.get('y')}\"" in led)
j = led.find("ONE shutter, ")
ck("the shut-door line says how wide it is", j > 0)
sblk = led[max(0, j - 900):j + 1400]   # the key-in-hand branch now sits above the plain one
ck("...only when it actually has twins",
   'if _tw else ""' in sblk)
ck("a one-cell shut door reads exactly as before",
   'words = ("a CLOSED DOOR, drawn shut across the way"' in sblk)
ck("the status wording is unchanged",
   "_STATUS_WORDS.get(" in sblk and "sealed_untried" in sblk)

# --- and it never says how to open one ---
# only the STRINGS the model can ever read; ck.doorTiles / cardKeyDoors are
# engine field names in our own code, not anything emitted
_code = "\n".join(l for l in blk.splitlines()
                  if not l.lstrip().startswith("--"))
_emitted = " ".join(re.findall(r'"([^"]*)"', _code))
ck("nothing is said about what opens a shutter",
   not re.search(r"(?i)(card.?key|you need|to open|press this)", _emitted))

import ast
try:
    ast.parse(led); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
