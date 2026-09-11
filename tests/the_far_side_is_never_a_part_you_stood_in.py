#!/usr/bin/env python3
"""Two refusals in one list must not point at each other's answer.

A step whose words say it comes OUT of somewhere cannot end on {"map": X}
when the run has already stood on X, because the condition holds before the
plan takes a step.  When the run has come out onto a part of X before, the
validator names that part and says "if this step means the far side, that
part IS it".

On ROUTE_23 that is exactly backwards.  VICTORY_ROAD_1F's door lands at
ROUTE_23|4,31, which is the way IN, so the advice pointed at a part the run
had stood in -- and the very next refusal in the same list rejects any part
already stood in.  Five authoring rounds, twice over, and the leg could not
be written at all while the party stood one door from the Indigo Plateau
(2026-09-10).

The excludes rule one screen up learned this on 2026-09-09 and this one had
not.  The fact is kept -- you did come out there, and that is worth knowing
-- and the advice becomes new_part, which is the answer that works.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "author.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

blk = SRC.split("and its words say it comes OUT somewhere", 1)[1][:1400]
head = SRC.split("and its words say it comes OUT somewhere", 1)[0][-2200:]

ck("the branch asks whether the part was stood in",
   "_far5 = _pt not in _parts5" in head or "_far5 = _pt not in _parts5" in blk)
ck("...using the same list the refusal below it uses",
   "_parts5 = sorted(" in SRC and SRC.count("_parts5") >= 3)
ck("a genuine far side is still offered as the witness",
   'if this step means the far side, that part IS it' in blk)
ck("...and a part already stood in is not",
   "is a part you have STOOD IN, so ending there" in blk)
ck("...it is sent to new_part instead",
   '{"new_part": "' in blk)
ck("the fact that you came out there is kept either way",
   "come out of {_flr} onto {_pt}" in head + blk)
ck("...with the door and the count",
   "its door at {_door}, {_n}x" in head + blk)

# the two sentences must never both name the same part as the answer
_advice = blk.split("_far5", 1)[-1]
ck("the far-side advice and the stood-in advice are exclusive",
   "if _far5 else" in blk or "else" in _advice)

# and the rule it was contradicting is still there
ck("the refusal it used to contradict still stands",
   "which this run has ALREADY stood in" in SRC
   or "already stood on" in SRC)

# the sibling rule that learned this first is untouched
ck("the excludes rule still filters the near side",
   "_walk_joined(pt, w)" in SRC and "A far side is a part" in SRC)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
