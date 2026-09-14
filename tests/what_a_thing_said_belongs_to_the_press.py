#!/usr/bin/env python3
"""A thing whose answers have differed says so as a fact about the PRESS,
never as a property of the thing.

Vermilion's gym rows read "TRASH_CAN_6 ... it has NOT always said the same
thing: "Nope, there's only trash here." (5x); "Hey! There's a switch under
the trash! ... The 1st electric lock opened!" (2x) -- its answer changed
between presses -- a fixture; it can be pressed again", and TRASH_CAN_8's
the same shape with "the electric locks were reset". The run read both as
labels: "I know TRASH_CAN_6 is a switch and TRASH_CAN_8 resets the locks.
I will start by re-triggering TRASH_CAN_6 ... while strictly avoiding
TRASH_CAN_8" (2026-09-14, user: "its very much focused on 6 and 8 as the
switch and reset respectively"). The record says the opposite of that, and
"it can be pressed again" made re-triggering sound like a free retry of a
known result.

So: the varied clause says the answer belongs to the press and does not
settle the next one; a varied thing is not also offered as pressable
again; and the room's ordered log folds runs of one answer into a single
entry, so a change of answer survives its window however many identical
presses lie between (fifteen cans, twelve of them saying "only trash",
had filled the list and pushed both turns off the end). Nothing here says
WHY an answer changed.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

TRASH = "Nope, there's only trash here."
SWITCH = "Hey! There's a switch under the trash! The 1st electric lock opened!"
RESET = "Nope! There's only trash here. Hey! The electric locks were reset!"
HERE = "VERMILION_GYM|4,1"
OBS = {"map": {"id": "VERMILION_GYM", "region": "4,1", "warps": [], "objects": []},
       "party": []}

class Ex:
    searched: dict = {}
    visits: dict = {}
    _cur_target = "badge:THUNDERBADGE"          # the book is keyed by it
    def __init__(self, book=None, log=None):
        self._outcomes = {f"{self._cur_target}|{HERE}": book or {}}
        self._press_log = {HERE: [list(x) for x in (log or [])]}
    def _where(self, o): return HERE
    def _route(self, a, b, **kw): return None
    def _taken_here(self, region): return {}

def C(key, **kw):
    return L.Candidate(key=key, kind="fixture", status="touched",
                       reachable=True, **kw)

def page(book, log=(), cands=None):
    return L.render(cands or [C("TRASH_CAN_6", x=5, y=7, n=7),
                              C("TRASH_CAN_8", x=5, y=11, n=2),
                              C("TRASH_CAN_1", x=1, y=9, n=5)],
                    Ex(book, log), OBS, target="badge:THUNDERBADGE", limit=30)

BOOK = {"TRASH_CAN_6": {"n": 7, "last": TRASH, "said": {TRASH: 5, SWITCH: 2}},
        "TRASH_CAN_8": {"n": 2, "last": RESET, "said": {TRASH: 1, RESET: 1}},
        "TRASH_CAN_1": {"n": 5, "last": TRASH, "said": {TRASH: 5}}}
import re
p = page(BOOK)

def row(key, txt):
    """The numbered row for one thing, not the header that names them all."""
    return next(l for l in txt.splitlines()
                if re.match(r"\s*\d+\.", l) and key in l)

row6, row8, row1 = row("TRASH_CAN_6", p), row("TRASH_CAN_8", p), row("TRASH_CAN_1", p)

# ---- the varied row ----------------------------------------------------------
ck("a thing that has said two things still lists both, counted",
   '"%s" (5x)' % TRASH in row6 and '"%s" (2x)' % SWITCH in row6, row6)
ck("...and says the answer belongs to the PRESS, not to the thing",
   "belongs to the PRESS and not to this thing" in row6, row6)
ck("...and that the last answer does not settle the next",
   "does not settle what the next one will be" in row6, row6)
ck("...in words no label can be made of", "its answer changed between presses" not in p)
ck("a varied thing is NOT also offered as a free retry",
   "it can be pressed again" not in row6, row6)
ck("...nor is the one that announced a reset", "it can be pressed again" not in row8, row8)
ck("a thing that has always said the same IS still pressable again",
   "a fixture; it can be pressed again" in row1, row1)
ck("the harness says nothing about WHY an answer changed",
   not any(w in p.lower() for w in ("random", "moves each", "re-roll", "reroll", "elsewhere now")))

# ---- the ordered log ---------------------------------------------------------
LOG = ([["TRASH_CAN_6", SWITCH]]
       + [[f"TRASH_CAN_{i}", TRASH] for i in (1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14)]
       + [["TRASH_CAN_8", RESET]])
p2 = page(BOOK, LOG)
log = next(l for l in p2.splitlines() if "WHAT PRESSING THINGS HERE HAS SAID" in l)
ck("both turns survive a window of twelve sames",
   SWITCH in log and RESET in log, log[:400])
ck("...because a run of one answer folds into one entry",
   "12 presses, all the same answer" in log, log)
ck("...naming some of them and counting the rest",
   "TRASH_CAN_1, TRASH_CAN_2, TRASH_CAN_3, TRASH_CAN_4 +8 more" in log, log)
ck("the switch press is still its own entry, in order",
   log.index(SWITCH) < log.index("12 presses") < log.index(RESET), log[:400])
ck("the header counts presses, not entries", "the last 14 press(es)" in log, log)
ck("it still refuses to read the record for the model",
   "what it means is yours to read" in log)

# ---- and the executor keeps enough history for that to be possible -----------
src = (ROOT / "planner" / "executor.py").read_text()
ck("the press log is deep enough to hold a turn plus a room of sameness",
   "del _pl[:-60]" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
