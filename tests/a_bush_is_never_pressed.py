"""A bush is cleared with CUT, and saying otherwise cost the run a road.

explore's thing-op dispatched on STATUS: `if c.status == "cuttable"` sent
field_move, and every other state fell through to interact-by-name. A bush
that had grown back carries the status "recut", so explore pressed A at it —
and bushes come from the tileset scan and have no object to press, so the
shim answered "object 'CUT_TREE' not visible" about a bush standing three
cells away in plain sight. The ledger row then wore that failure.

Two fixes, one each side. The op is chosen by KIND, because what reaches a
thing is a property of what it is, not of how worked it is. And the refusal
says what a bush IS rather than the one thing that is false about it.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
src = (ROOT / "planner" / "executor.py").read_text()
shim = (ROOT / "harness" / "shim.lua").read_text()

i = src.find("A BUSH IS NEVER PRESSED, WHATEVER ITS STATUS")
ck("explore chooses the op by kind", i > 0)
blk = src[i:i + 900]
ck("...a cut_tree is cut, in any state",
   'if c.kind == "cut_tree" and c.x is not None:' in blk
   and '"op": "field_move", "move": "CUT"' in blk)
ck("...and status no longer decides it",
   'if c.status == "cuttable":' not in blk)
ck("everything else is still pressed", '{"op": "interact", "name": c.key}' in blk)

j = shim.find("A BUSH IS NOT INVISIBLE, IT IS NOT PRESSABLE")
ck("the shim answers a pressed bush honestly", j > 0)
sblk = shim[j:j + 1200]
ck("...saying it is a bush, not that it cannot be seen",
   "A bush is not a thing that " in sblk and "presses" in sblk
   and "no object there to talk to" in sblk)
ck("...and naming the op that does reach it",
   "field_move" in sblk and "CUT" in sblk)
ck("...before the generic not-visible answer, not after",
   j < shim.find('return false, "object \'" .. c.name .. "\' not visible"'))
ck("the generic answer still stands for everything else",
   "\"' not visible\"" in shim)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
