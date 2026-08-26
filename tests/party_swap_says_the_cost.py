"""A deposit says what the party lost, and a failed teach says why
(2026-08-26).

Holding HM_SURF, the run met "CHARIZARD is NOT COMPATIBLE with HM_SURF",
boxed CHARIZARD :L47 to free a slot, withdrew LAPRAS :L15, and taught SURF to
it — user: "it taught surf to lapras -- unfortunately it put char in the box to
do it".

Two harness gaps on that path. The deposit said "deposited CHARIZARD :L47 —
party is now 5" and did not say that L47 was the HIGHEST level in it, so the
cost was legible only as a number buried in a label. And the use_item that
followed, in the SAME macro (which renumbers every slot), failed with seven
bare words: "the teach did not go through"."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()

# --- the failed teach ---
ck("the bare teach failure is gone",
   'return false, "the teach did not go through"\n' not in lua)
i = lua.find("AND THE LAST CASE SAID SEVEN WORDS")
ck("the last teach case explains itself", i > 0)
t = lua[i:i + 1400]
ck("...naming the slot and who is in it",
   "tostring(slot)" in t and "mon and mon.species" in t)
ck("...and what they already know", "table.concat(monmoves" in t)
ck("...and that a mid-macro party change renumbers slots",
   "CHANGED " in t and "every slot " in t and "moved with it" in t)
ck("the incompatible and four-moves cases are untouched",
   "is NOT COMPATIBLE with " in lua
   and "it already knows four moves: " in lua)

# --- the deposit ---
j = lua.find("WHAT THE PARTY JUST LOST, IN ITS OWN NUMBERS")
ck("a deposit says what is left", j > 0)
d = lua[j:j + 1600]
ck("...as the range of levels still in the party",
   "_lo" in d and "_hi" in d and "what is left is L" in d)
ck("...and says so when the one boxed was the highest",
   "that was the highest level in it" in d and "_lv > _hi" in d)
ck("...read from the label the op already builds",
   'label):match(":L(%d+)")' in d)
ck("a party with no readable levels still reports plainly",
   'or ""' in d)
ck("it does not tell the model whether the swap was right",
   not re.search(r"(?i)(you should|mistake|do not box|bad idea)",
                 " ".join(re.findall(r'"([^"]*)"', d))))

# the withdraw side is unchanged
ck("withdraw still reports plainly",
   'return true, ("withdrew %s — party is now %d")' in lua)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
