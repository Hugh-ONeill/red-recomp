#!/usr/bin/env python3
"""A hint quoted from a thing whose answers have differed says so, with
what else it has said.

A hint is filed under whoever said it, which is right for a person who
keeps saying the same thing and wrong for a thing whose answer moves.
Vermilion's gym listed "TRASH_CAN_6: Hey! There's a switch under the
trash! ... The 1st electric lock opened!" and "TRASH_CAN_7: ... Hey! The
electric locks were reset!" with no count and no history beside them, and
the run opened every attempt on that page with "I know TRASH_CAN_6 is a
switch and TRASH_CAN_8 resets the locks. I will start by re-triggering
TRASH_CAN_6 ... while strictly avoiding TRASH_CAN_8" (2026-09-14). The
candidate rows had said since that an answer belongs to the press; the
hint quoting the same sentence has to say it too, or the label is read
from here instead. Both hint blocks, here and elsewhere, go through
_dated, so it is said once.

Nothing here says WHY an answer changed.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "VERMILION_GYM|4,5"
SWITCH = "Hey! There's a switch under the trash! Turn it on! The 1st electric lock opened!"
TRASH = "Nope, there's only trash here."
RESET = "Nope! There's only trash here. Hey! The electric locks were reset!"
NURSE = "We heal your POKeMON back to perfect health!"

def ex(books):
    o = types.SimpleNamespace(_outcomes=books, _gone={}, hints_at={})
    for m in ("_said_variously", "_dated"):
        setattr(o, m, types.MethodType(getattr(E.Executor, m), o))
    o._same_saying = E.Executor._same_saying
    return o

BOOKS = {
    # one thing's history is split across the per-target books
    f"badge:THUNDERBADGE|{HERE}": {
        "TRASH_CAN_6": {"said": {TRASH: 10, SWITCH: 2}},
        "VERMILIONGYM_NURSE": {"said": {NURSE: 3}},
    },
    f"map:VERMILION_CITY|{HERE}": {"TRASH_CAN_6": {"said": {RESET: 1}}},
    f"badge:THUNDERBADGE|VERMILION_CITY|1,1": {"TRASH_CAN_6": {"said": {"elsewhere": 9}}},
}
E_ = ex(BOOKS)
OBS = {"flags": []}

out = E_._dated(HERE, f"TRASH_CAN_6: {SWITCH}", OBS)
ck("the sentence itself is untouched", out.startswith(f"TRASH_CAN_6: {SWITCH}"), out)
ck("...and is told the thing has not always said it",
   "TRASH_CAN_6 has NOT always said this" in out, out)
ck("...with what else it said, counted, commonest first",
   out.index('"%s" (10x)' % TRASH) < out.index('"%s" (1x)' % RESET), out)
ck("...gathered across every target's book for this region",
   TRASH in out and RESET in out, out)
ck("...but not from another region", "elsewhere" not in out, out)
ck("...saying the answer belongs to the press",
   "belongs to the PRESS and not to TRASH_CAN_6" in out
   and "does not settle what the next press will say" in out, out)
ck("the quoted line is not repeated back as one of the others",
   out.count(SWITCH) == 1, out)

ck("a thing that has only ever said one thing is quoted plainly",
   E_._dated(HERE, f"VERMILIONGYM_NURSE: {NURSE}", OBS)
   == f"VERMILIONGYM_NURSE: {NURSE}")
ck("...and so is a speaker with no book at all",
   E_._dated(HERE, "SOMEONE: a line", OBS) == "SOMEONE: a line")
ck("a line with no speaker is left alone", E_._dated(HERE, "sweep: a line", OBS) == "sweep: a line")

# the excerpt in the book and the whole saying in the hints are one line
ck("an excerpt of the quoted line counts as the same saying",
   E.Executor._same_saying(SWITCH[:60] + " ...", SWITCH)
   and E.Executor._same_saying(SWITCH, SWITCH))
ck("...and two different sayings do not", not E.Executor._same_saying(TRASH, SWITCH))
ck("...and nothing is the same as nothing", not E.Executor._same_saying("", ""))

# it survives beside the stamp the line already carried
G = ex({f"badge:THUNDERBADGE|{HERE}": {"TRASH_CAN_6": {"said": {TRASH: 4, SWITCH: 1}}}})
G._gone = {HERE: {"TRASH_CAN_6"}}
out2 = G._dated(HERE, f"TRASH_CAN_6: {SWITCH}", OBS)
ck("the gone stamp and the varied stamp both fit on one line",
   "NOT THERE ANY MORE" in out2 and "has NOT always said this" in out2, out2)

src = (ROOT / "planner" / "executor.py").read_text()
ck("both hint blocks are dated through the one gate",
   src.count("self._dated(here, l, obs)") == 1
   and "self._dated(_rg, _ls[_round], obs)" in src)
ck("the harness still says nothing about WHY an answer changed",
   not any(w in src[src.index("def _dated"):src.index("def _dated") + 3000].lower()
           for w in ("random", "re-roll", "reroll", "moves each time")))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
