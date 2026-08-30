"""Two entries, one bush; and the vaguer clause was read first.

ROUTE_9|0,8's blocker record read "the walk was fenced — CUT_TREE (a bush CUT
clears) at (5,8), CUT_TREE (a bush CUT clears) at (5,8)": two obstacles where
the map has one. The pocket scan and bushes_blocking both reach the cell that
seals a nook, and each appended it (2026-08-30).

And the ledger preferred the wrong clause. A cross refusal can carry both
"Right where the walk stopped: X" — the shim naming what the walk actually
died against — and "standing at its edge: Y" — the whole fence of the pocket
it ended in. The blocker took whichever came first in its own tuple, which
was the wider list, and wrote it down as the cause.
"""
import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
shim = (ROOT / "harness" / "shim.lua").read_text()
src = (ROOT / "planner" / "executor.py").read_text()

ck("the fence refuses a repeat",
   shim.count("if #fence < 6 and not _dup then") == 2
   and shim.count("ONE BUSH IS ONE BUSH") == 2)
ck("...and no builder appends without that test",
   "if #fence < 6 then fence[#fence + 1] = b end" not in shim)
# the dedupe must compare the whole rendered entry, since two bushes on one
# map differ only by their coordinates
_i = shim.find("ONE BUSH IS ONE BUSH")
ck("...comparing the whole entry, so two real bushes both survive",
   "if _f == b then _dup = true end" in shim[_i:_i + 700])

ck("the precise clause is read first",
   '("Right where the walk stopped:", "standing at its edge:")' in src)
ck("...and the wider one is still read when it is all there is",
   '"standing at its edge:"' in src)
ck("...still recorded as a fence either way",
   'f"the walk was fenced — {clause}"' in src)

# the shim must still SAY both, in that order: this changes which one the
# ledger keeps, not what the model is told
ck("the refusal still names what stopped the walk before the fence",
   shim.find("Right where the walk stopped: ")
   < shim.find("cell(s), and standing at its edge: "))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
