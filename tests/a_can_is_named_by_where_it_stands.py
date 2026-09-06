"""A crowd of the same fixture says where each one stands, and does not
claim they all do the same thing.

Lt. Surge's gym has fifteen TRASH_CANs; two of them hold the switches that
open his door, and the second is in a can NEXT TO the first.  The crowd
fold read "15 x TRASH_CAN -- none of them pressed; they are the same thing
over and over, so whatever one of them does, all of them do: TRASH_CAN_1,
TRASH_CAN_2, TRASH_CAN_3, TRASH_CAN_4 and 11 more".  Run 15 spent 50 rounds
in that room (autopsy, 2026-09-06) being told the cans were interchangeable,
with no way to say which one it had pressed or which stood beside it.

A shared name is on-screen tier.  "All of them do the same" was a claim
about the world, and a false one.  So the line carries the name, the count,
where each stands, and -- once any of that name has been pressed here --
what each pressed one said, which is the fact the puzzle turns on.  The
fold itself stays: thirty-six slot machines still read as one line, and the
people in the room stay on the page.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import ledger as L            # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


class Ex:
    searched: dict = {}
    visits: dict = {}

    def _where(self, o):
        return "VERMILION_GYM|4,1"

    def _route(self, a, b, **kw):
        return None

    def _taken_here(self, region):
        return {}


OBS = {"map": {"id": "VERMILION_GYM", "region": "4,1", "warps": [],
               "objects": []}, "party": []}


def C(key, kind, status, **kw):
    return L.Candidate(key=key, kind=kind, status=status, reachable=True, **kw)


# fifteen cans in three rows, none pressed yet
CANS = [(1, 1, 7), (2, 3, 7), (3, 5, 7), (4, 7, 7), (5, 9, 7),
        (6, 1, 9), (7, 3, 9), (8, 5, 9), (9, 7, 9), (10, 9, 9),
        (11, 1, 11), (12, 3, 11), (13, 5, 11), (14, 7, 11), (15, 9, 11)]


def gym(pressed=()):
    out = []
    for n, x, y in CANS:
        if n in pressed:
            out.append(C(f"TRASH_CAN_{n}", "fixture", "touched", x=x, y=y,
                         n=1, note=pressed[n]))
        else:
            out.append(C(f"TRASH_CAN_{n}", "fixture", "untouched", x=x, y=y))
    out += [C("VERMILIONGYM_LT_SURGE", "trainer", "unspoken", x=5, y=1),
            C("VERMILIONGYM_GENTLEMAN", "trainer", "unspoken", x=8, y=6),
            C("4,17", "door", "taken", n=1, dest="VERMILION_CITY|10,12")]
    return out


page = L.render(gym(), Ex(), OBS, target="badge:THUNDER", limit=20)
line = next((l for l in page.splitlines() if "x TRASH_CAN" in l), "")
ck("the cans still fold to one line", "15 x TRASH_CAN" in line
   and page.count("TRASH_CAN_") <= 2)
ck("the line no longer claims they all do the same",
   "same thing over and over" not in page
   and "whatever one of them does" not in page)
ck("it says a shared name is all that is shared",
   "share a name" in line and "its own to say" in line)
for n, x, y in CANS:
    ck(f"can {n} is placed at ({x},{y})", f" {n} ({x},{y})" in line
       or f": {n} ({x},{y})" in line)
ck("the people are still on the page",
   "VERMILIONGYM_LT_SURGE" in page and "VERMILIONGYM_GENTLEMAN" in page)
ck("the door is still on the page", "door (4,17)" in page)

# two pressed: the line says what each said, and keeps the rest placed
SAID = {3: "Nope! There's only trash here.",
        8: "Hey! There's a switch under the trash! Turn on!"}
page = L.render(gym(pressed=SAID), Ex(), OBS, target="badge:THUNDER",
                limit=20)
line = next((l for l in page.splitlines() if "x TRASH_CAN" in l), "")
ck("thirteen are still folded", "13 x TRASH_CAN" in line)
ck("the two pressed are counted on the line",
   "2 of that name pressed here already" in line)
ck("...each with where it stands and what it said",
   '3 (5,7) said "Nope! There\'s only trash here."' in line
   and "8 (5,9) said \"Hey! There's a switch under the trash! Turn on!\""
   in line)
ck("the pressed can with the switch is not called 'the same' as the rest",
   "same thing over and over" not in page)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("LINE WAS:", line[:800])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
