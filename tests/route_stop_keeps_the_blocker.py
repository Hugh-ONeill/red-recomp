"""The tail of a refusal is where the blocker is named (2026-08-26).

`go` from Vermilion to Celadon routes Cerulean -> ROUTE_9|0,8, a 9-cell
pocket whose east seam is sealed by a CUT_TREE at (5,8). The cross refusal
names that tree — geometry first, what stands in the way LAST — and
yesterday's WHAT-STOPPED-IT passed the refusal through at [:300], cutting it
mid-clause at "...and standing at its edge". The model read a wall, tried
FLY (which it cannot use), and re-issued the same go (user: "from
vermillion stopped at rt9 again").

Second half: the sweep that follows sends field_move CUT and reported it as
"pressed A on CUT_TREE — everything reachable here has now been tried",
which is the opposite of what happened."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

# --- the refusal is no longer cut at 300 ---
ck("a named budget replaces the bare [:300]",
   "WHY_BUDGET" in src
   and 'and what it said was: {str(_last_det)[:300]}' not in src
   and 'and what it said was: {str(_wdet)[:300]}' not in src)
m = re.search(r"WHY_BUDGET = (\d+)", src)
ck("the budget exists and clears a whole refusal",
   m and int(m.group(1)) >= 900)
ck("both give-up paths use it",
   src.count("str(_last_det)[:self.WHY_BUDGET]") == 1
   and src.count("str(_wdet)[:self.WHY_BUDGET]") == 1)

# --- a felled bush is reported as felled ---
i = src.find("CUT DOWN {', '.join(felled)}")
ck("the sweep says a bush was CUT DOWN", i > 0)
blk = src[max(0, i - 3600):i + 700]
ck("...only when the op actually reported ok",
   '((o2 or {}).get("result") or {}).get("ok")' in blk
   and "felled.append(" in blk)
ck("...and pressing is still reported for everything else",
   "_pressed = [n for n in loose[:8]" in blk
   and "pressed A on {', '.join(_pressed)}" in blk)
ck("it says the ground changed, so a stopped walk may now get further",
   "walkable now" in blk and "send it again" in blk)
ck("it does not claim the cut opened any particular way",
   not re.search(r"(?i)(the road to|you can now reach [A-Z_]+\||the way "
                 r"(east|west|north|south) is now|this opens the)", blk))
ck("a floor with nothing felled reads exactly as before",
   "if felled else []" in blk)

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
