#!/usr/bin/env python3
"""A pressed thing whose answers have differed is shown as a history, not a
label.

Vermilion Gym, run 16 (2026-09-07): each trash can was listed with the LAST
thing it said, so "the electric locks were reset!" read as a property of
cans 0, 5, 9, 13 and 14 and "the 1st electric lock opened!" as a property of
can 12, and the opener read "pressed 6x; nothing changed" though a lock had
opened. The game's rule ties both to the ORDER of presses, and the run had
watched the opener move five times. The model wrote "TRASH_CAN_0, 5, 9, 13,
and 14 reset the locks" and avoided them (user: "it has odd ideas about the
trash ... or if its something we just should let the model eventually reason
out"). The record now reads as what it is: every distinct reply with its
count, "nothing changed" withdrawn, and the room's presses in order. What
the rule is stays the model's to work out.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
ex_src = (ROOT / "planner" / "executor.py").read_text()
lg_src = (ROOT / "planner" / "ledger.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the executor keeps every distinct reply, counted, per pressed thing",
   "_sd = rec.setdefault(\"said\", {})" in ex_src and "_sd[_sd_txt] = int(_sd.get(_sd_txt) or 0) + 1" in ex_src)
ck("...and the room's presses in order, twelve deep",
   "_pl = self._press_log.setdefault(here, [])" in ex_src and "del _pl[:-12]" in ex_src)
ck("the ledger reads the outcome book once per render",
   "_book = ((getattr(ex, \"_outcomes\", None) or {})" in lg_src)
ck("a varied fixture loses 'nothing changed' and gets its replies counted",
   'words = words.replace("; nothing changed", "")' in lg_src and "it has NOT always said the same thing" in lg_src)
ck("the room's presses are printed in order when answers here have varied",
   "WHAT PRESSING THINGS HERE HAS SAID, IN ORDER" in lg_src and "The order is the record; what it means is yours to read." in lg_src)
# the wording is a record, not a rule
ck("nothing on the page names the rule",
   "adjacent" not in lg_src.split("WHAT PRESSING THINGS HERE HAS SAID")[1][:600].lower()
   and "next to" not in lg_src.split("it has NOT always said the same thing")[1][:400].lower())

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
