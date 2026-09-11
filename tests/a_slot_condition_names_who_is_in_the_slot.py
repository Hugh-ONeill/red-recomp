#!/usr/bin/env python3
"""A slot condition reads the SLOT, and the step's words name a Pokemon.

Only the party-wide level form had a "what this condition counts" line, so
a slot_level step said nothing about its slot at all.  Its goal_text names
whoever stood there when the plan was WRITTEN, and a party is reordered by
switching, depositing and withdrawing, while an evolution renames one in
place.

Leg 46's five training steps ended up testing slots holding none of the
Pokemon they were named for: train_eevee on a slot holding DODRIO, and
train_gloom on a slot already at L50, so it could never complete and spent
its attempts finding that out (user, 2026-09-11: "fix the subgoal names to
use the slot's current occupant").

The plan is not rewritten -- the model wrote those words and they are its
record.  The page says who the condition is actually reading.
Source-anchored: the paragraph is built inside the goal reader.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "executor.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

blk = SRC.split("AND FOR A SLOT, WHO IS STANDING IN IT", 1)[1][:3600]
import re                                               # noqa: E402
flat = re.sub(r"\s+", " ", blk.replace('"', "").replace("\\", ""))

ck("slot_level reads the slot off the condition",
   'int(dw_val.get("slot") or 0)' in blk and '_kind == "slot_level"' in blk)
ck("lead_level is slot 1", '1 if _kind == "lead_level" else 0' in blk)
ck("the occupant is named, with its types",
   "_occ.get('species')" in blk and "_mon_types(_occ)" in blk)
ck("...and how far short it is", "short of L{_need}" in blk)
ck("a slot already at the bar is said to HOLD",
   "already at L{_need}" in flat.replace("{_need}", "{_need}")
   or "already at L" in flat)
ck("...and that battling there changes nothing",
   "battling changes nothing here" in flat)
ck("an empty slot says so rather than raising",
   "there is nobody in it" in flat)
ck("the page explains why the words can disagree",
   "reordered by switching, depositing and withdrawing" in flat
   and "evolution renames one in place" in flat)
ck("...and which of the two is authoritative", "The SLOT is what is read" in flat)
ck("the plan itself is left alone",
   "The plan is not rewritten" in SRC.split("AND FOR A SLOT", 1)[1][:1400])

# the party-wide form is untouched
ck("party_min_level still counts every member",
   'if _kind == "party_min_level" and _short:' in SRC
   and "every Pokemon IN YOUR " in SRC)
ck("...and still lists who is short",
   "Still short of " in SRC and "(+{_need - lv})" in SRC)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
