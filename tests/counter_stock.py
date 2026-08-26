"""A counter's stock is on screen the moment you press A at it (2026-08-26):
the run stood at Celadon 4F twice, was told "that is a shop COUNTER", and was
never told it sells a WATER_STONE — with an EEVEE in slot 6 and a leg asking
for a WATER type. The shelf used to be learned only from a FAILED purchase."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

shim = Path("harness/shim.lua").read_text()
ck("the shim reads a counter's list from the game's own table",
   "function counter_stock(G, tx, ty)" in shim
   and "G.data:textEntry(ow.map.def.label, txt)" in shim)
ck("...and says it when the counter opens", "THIS COUNTER SELLS: " in shim)
ck("it is read at the pressed tile, not guessed",
   "n.cellX == tx and n.cellY == ty" in shim)
ck("a counter with no mart entry says nothing extra",
   "if not (ok and entry and entry.mart) then return nil end" in shim)

# the engine's own signature, so this cannot drift silently
data = Path.home() / "Developer/gen1recomp/src/core/Data.lua"
if data.exists():
    ck("Data:textEntry(mapLabel, textConst) still exists",
       "function Data:textEntry(mapLabel, textConst)" in data.read_text())

# the fact itself: 4F really does stock the stones
tp = Path.home() / "Developer/gen1recomp/data/generated/text_pointers.lua"
if tp.exists():
    blk = tp.read_text()
    m = re.search(r"TEXT_CELADONMART4F_CLERK = \{(.*?)\n    \},", blk, re.S)
    ck("Celadon 4F stocks WATER_STONE", bool(m) and "WATER_STONE" in m.group(1))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
