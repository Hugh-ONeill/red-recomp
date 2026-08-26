"""A LEVEL goal is told where the run has already fought (2026-08-26).

The catch branch of training_text has carried the wild record since
2026-08-24; the level branch carried none of it and said only "somewhere
wild is where to go". Holding DIGLETT L22 -> L35 the run stood on ROUTE_24's
L7-L14 grass and spent six rounds walking Cerulean -> 24 -> 25 hunting
DIGLETTS_CAVE, which its own atlas records it fighting in 76 times (user:
"for some reason its thinking digletts cave is rt 25 but it should have it
in its memory that its rt2 or rt11").

Recall of its own battles only. Where any map SITS is never stated, and no
ground is recommended over another."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

# --- the block exists, in the LEVEL branch ---
i = src.find("WHAT THE FIGHTING HAS ACTUALLY BEEN")
ck("the level page names what the fighting has been", i > 0)
blk = src[i:i + 900]
ck("...it is the else-branch (levels), not the catch branch",
   "HOW TO DO IT: {\\\"op\\\":\\\"grind\\\"} walks onto this floor's"
   in src[max(0, i - 4000):i]
   and "party_size" not in src[max(0, i - 1200):i])

# --- all four helpers reach it ---
for helper in ("_wild_level_note", "_grind_yield_note", "_exp_needed_note",
               "_wild_elsewhere_note"):
    ck(f"{helper} feeds the level page", helper in src[max(0, i - 900):i + 900])

ck("the ground it stands on and the ground elsewhere are both offered",
   "_here2" in blk and "_away2" in blk)
ck("it stays silent when there is no record at all",
   "if _here2 or _away2:" in src[max(0, i - 400):i])

# --- never points ---
# comments carry the case history (Route 9, Diglett's Cave); only the text
# that actually reaches the model is under test here
_said = "\n".join(l for l in blk.splitlines()
                  if not l.lstrip().startswith("#"))
ck("no map is placed for it, and no ground is recommended",
   not re.search(r"(?i)(route \d|diglett's cave|is located|you should|go to "
                 r"the|best place|pays more|worth going)", _said))
ck("the choice is left with the model",
   "worth the walk is yours to read" in blk)

# --- the elsewhere note no longer cuts at five, and dates its samples ---
j = src.find("WILD GROUND ELSEWHERE YOU HAVE ALREADY FOUGHT ON")
ck("the elsewhere note exists", j > 0)
note = src[max(0, j - 1600):j + 400]
ck("...it no longer stops at five floors", "rows[:5]" not in note)
ck("...and the tail keeps the level range, which is the evidence",
   "the levels alone" in note and "more floor" not in note
   and 'f"L{_wl[\'lo\']}-L{_wl[\'hi\']}"' in note)
ck("an exp-per-grind figure carries its sample size",
   "exp per grind over " in note and "grind(s)" in note)

# --- and it still compiles ---
import ast
try:
    ast.parse(src)
    ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
