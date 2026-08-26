"""An op whose world moved is not announced as FAILED (2026-08-26).

The Route 7 guard drank the water — EVENT_GAVE_GUARDS_DRINK fired, the bottle
left the bag — and the line the model read was:

  interact(name=ROUTE7GATE_GUARD,answer=yes): FAILED — stuck in a menu/dialog
  [FRESH_WATER -1 (now 0)] — it said: "...You can go on through"

The op ran out of A presses on a long speech. That is the BOX still being up,
not the interaction not happening, and the harness's own delta sat two clauses
later contradicting its own verdict. The run had to overrule us to continue.

ONLY the sentence changes: the strike, the touch retraction and everything else
keyed on `ok` stay as they were — whether an op should be RE-SENT is a
different question from whether the world moved."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("BUT THE WORLD MOVED")
ck("a moved world is said plainly instead of FAILED", i > 0)
blk = src[max(0, i - 1600):i + 600]

ck("it is gated on the harness's own delta",
   "_moved = self._goods_delta(pre_obs, obs)" in blk and "if _moved:" in blk)
ck("an op that moved nothing still reads FAILED",
   'else:' in blk and 'note += f": FAILED — {r.get(\'detail\')}"' in blk)
ck("the op's own reason is still carried either way",
   blk.count("r.get('detail')") >= 2)
ck("control flow keyed on ok is untouched",
   'self._strike(sig, r.get("detail"))' in blk
   and "_retract_touch" in src[i:i + 1200])
ck("it does not claim the op SUCCEEDED, only that something happened",
   "did not finish cleanly" in blk
   and not re.search(r"(?i)(succeeded|it worked|the op is done)", blk))

# the delta is what proves it, and it covers bag AND wallet
j = src.find("def _goods_delta")
ck("the delta covers the bag and the wallet",
   "(now {b1.get(k) or 0})" in src[j:j + 2400]
   and "money {m1 - m0:+d}" in src[j:j + 2400])

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
