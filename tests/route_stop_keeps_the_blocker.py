"""The tail of a refusal is where the blocker is named (2026-08-26).

`go` from Vermilion to Celadon routes Cerulean -> ROUTE_9|0,8, a 9-cell
pocket whose east seam is sealed by a CUT_TREE at (5,8). The cross refusal
names that tree — geometry first, what stands in the way LAST — and
yesterday's WHAT-STOPPED-IT passed the refusal through at [:300], cutting it
mid-clause at "...and standing at its edge". The model read a wall, tried
FLY (which it cannot use), and re-issued the same go (user: "from
vermillion stopped at rt9 again").

Second half: the sweep that follows claimed "pressed A on CUT_TREE —
everything reachable here has now been tried" over a bush that presses
nothing. The sweep no longer touches bushes at all (2026-08-30, and see
a_bush_is_cut_when_it_is_in_the_way), so what is left to hold here is the
CLAIM: a sweep that presses cannot say everything here has been tried while
a bush it declined to fell is standing in the room."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))
# The sweep's sentences are wrapped across adjacent literals, so a
# check on the source reads the wrapping, not the words. Join them
# first and the checks below are about what the model is told.
def _flat(t): return re.sub(r'"\s*\n\s*f?"', "", t)

src = Path("planner/executor.py").read_text()

# --- the refusal is no longer cut at 300 ---
ck("a named budget replaces the bare [:300]",
   "WHY_BUDGET" in src
   and 'and what it said was: {str(_last_det)[:300]}' not in src
   and 'and what it said was: {str(_wdet)[:300]}' not in src)
m = re.search(r"WHY_BUDGET = (\d+)", src)
ck("the budget exists and clears a whole refusal",
   m and int(m.group(1)) >= 900)
ck("every give-up path uses it (the two originals and the Safari-clock verdict)",
   src.count("str(_last_det)[:self.WHY_BUDGET]") == 1
   and src.count("str(_wdet)[:self.WHY_BUDGET]") == 1
   and src.count("{_det[:self.WHY_BUDGET]}") == 1)

# --- the sweep's claim is scoped to what it actually did ---
i = src.find("(swept this area: ")
ck("the sweep still reports itself", i > 0)
blk = src[max(0, i - 3600):i + 1400]
flat = _flat(blk)
ck("...pressing is reported for what presses",
   "_pressed = list(loose[:8])" in blk
   and "pressed A on {', '.join(_pressed)}" in flat)
ck("...and the claim covers only that",
   "everything reachable here that PRESSES has now been tried" in flat
   and "everything reachable here has now been tried" not in flat)
ck("a standing bush is named rather than claimed done",
   "The sweep did NOT fell " in blk)
ck("it does not claim a cut opened any particular way",
   not re.search(r"(?i)(the road to|you can now reach [A-Z_]+\||the way "
                 r"(east|west|north|south) is now|this opens the)", blk))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
