#!/usr/bin/env python3
"""A floor you cannot route to right now is still on the page, and a door
seen but never reached is its own kind.

Route 23, 2026-09-06. The intra-map swim between Route 23's two halves was
stamped blocked, so no walked route reached Victory Road — and the
not-finished-floors list dropped every floor it could not route to, while
the unseen-ground list sorted no-route floors last and cut them with the
tail ("and 68 more floor(s)"). From the cave's own doorstep the page said
nothing about the cave, and the run planned to walk north into the Plateau
from the pond (user: "hooked on trying to get to indigo plateau without
going through victory road").

And even when a route existed, Victory Road 2F's four ways out that the run
had SEEN and never reached (the barriers) were filed as "on parts you have
never stood on" and ranked behind Saffron at 25 legs, fifteenth in an
"also" tail. They were seen from the part it stood on; that is the puzzle
floor's signature and it ranks between a plain untried door and a part
never stood on. A floor within three legs with anything to go back for
reads in full.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EXEC = (ROOT / "planner/executor.py").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

i = EXEC.index("FLOORS YOU HAVE WALKED THAT ARE NOT FINISHED")
blk = EXEC[i - 9000:i + 400]
ck("a floor with no walked route is no longer dropped",
   "if _p is None:\n                continue" not in blk
   and "else (len(_p) if _p is not None else 99)" in blk)
ck("...and says so in words", "no walked route from here right now (a way you " in blk)
ck("seen-but-never-reached doors are gathered from the run's own unreached record",
   '_unr |= {str(k) for k in (_ks or [])}' in blk and "_barred = sorted((_left - _fr) & _unr)" in blk)
ck("...and said as their own kind, claiming nothing about what blocks them",
   "seen from ground you have stood on " in blk and "something in " in blk
   and "that floor's " in blk and "boulder" not in blk[blk.index("seen from ground you have stood on "):][:600].lower())
ck("...ranking between plain untried doors and parts never stood on",
   "0 if r[3] else 1 if r[5] else 2" in blk)
ck("a near floor with anything to go back for reads in full",
   "_near = [r for r in _rows[3:] if r[0] <= 3 and (r[3] or r[5])]" in blk)
ck("the tail counts all three kinds", "len(_o) + len(_f) + len(_b)" in blk)
j = EXEC.index("FLOORS YOU HAVE WALKED WITH GROUND NEVER ON SCREEN")
blk2 = EXEC[j:j + 2200]
ck("the unseen-ground list names the no-route floors it used to cut",
   "No walked route from here right now reaches: " in blk2
   and "if r[0] >= 99][:6]" in blk2)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
