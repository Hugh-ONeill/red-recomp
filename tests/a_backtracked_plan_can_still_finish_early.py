#!/usr/bin/env python3
"""A plan that went back to step one can still notice it is done.

When a plan's final condition holds part way through, the rest is skipped:
the leg's aim is achieved and grinding the remaining steps buys nothing.
That shortcut is barred at subgoal 0, because a witness true before the
plan moves witnesses nothing -- {"lacks_item": ["FRESH_WATER"]} held with
no water ever bought and the leg completed in zero rounds.

But BACKTRACK sends a stuck plan back to an earlier subgoal, so a plan
that regresses to its FIRST one sits at index 0 for ever and can never
take the shortcut however much it has achieved since.

Leg 47, "revive all fainted party members", is the case.  CHARIZARD came
back to 158hp mid-leg, so party_healthy held, and the plan went on working
go_to_cinnabar_island from Seafoam B3F because it had backtracked to step
one (2026-09-11).

The bar is now "no step has run yet" rather than "index is 0", which is
what it always meant.  Source-anchored: the loop needs a live game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "executor.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the loop tracks whether any step has run",
   "_ran_any = False" in SRC and "ok = self._attempt(sg)\n            _ran_any = True" in SRC)
ck("the before-the-first-step notice asks that, not the index",
   "if idx == 0 and not _ran_any and _fin \\" in SRC)
ck("...and still only warns, still runs the plan",
   "running the plan anyway" in SRC)
ck("the shortcut fires once a step has run, whatever the index",
   "if (idx > 0 or _ran_any) and idx < len(subgoals) - 1 and _fin \\" in SRC)
ck("...and still never on the last subgoal",
   "idx < len(subgoals) - 1" in SRC)
ck("...and still refuses a witness that cannot vouch",
   "objective_vouches(_fin)" in SRC)

# the rule that bars absence-only witnesses is untouched
ck("an absence-only objective still cannot end a leg early",
   'ABSENCE_KEYS = frozenset({"lacks_item", "bag_kinds_below"})' in SRC)
ck("...and objective_vouches is what says so",
   "return bool(ks) and not ks <= ABSENCE_KEYS" in SRC)

# the reason is written where the next reader will look
blk = SRC.split("AND WHETHER ANY STEP HAS ACTUALLY RUN", 1)[1][:900]
import re                                               # noqa: E402
flat = re.sub(r"\s+", " ", blk)
ck("the incident is recorded beside the flag",
   "revive all fainted party members" in flat and "Seafoam B3F" in flat)
ck("...and why index 0 was the wrong question",
   "backtrack" in flat.lower() and "sits at idx 0" in flat)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
