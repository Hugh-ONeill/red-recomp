"""One blackout is one blackout, and the party's HP is on every page.

Run 16, the Brock leg (2026-09-07): two real blackouts, and every page said
"Your party has been WIPED OUT 4x pursuing this goal".  Four detectors
notice a blackout -- the state watch, the battle handler, the op-result
reader, the round-level check -- and each bumped the counter.  Told it had
lost twice as often as it had, the model walked between the gym and Route 2
for twenty rounds unable to decide whether it was strong enough (user: "its
pingponging now between the gym and rt2, not training").

And the page before the Brock fight carried no HP at all: the party walked
in at 18/39 straight from the gym trainer's fight.  HP is on the screen
every round; now it is on the page every round.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

ex = E.Executor.__new__(E.Executor)
ex._blackouts, ex._blackout_lead = {}, {}
obs = {"money": 658, "party": [{"species": "CHARMANDER", "level": 14, "hp": 39, "max_hp": 39},
                               {"species": "NIDORAN_F", "level": 13, "hp": 33, "max_hp": 33}]}
ck("the first detector counts the wipe", ex._count_blackout("badge:BOULDERBADGE", obs)
   and ex._blackouts["badge:BOULDERBADGE"] == 1)
ck("...and records the lead's level", ex._blackout_lead["badge:BOULDERBADGE"] == 14)
ck("a second detector reading the same wipe does not",
   not ex._count_blackout("badge:BOULDERBADGE", obs)
   and ex._blackouts["badge:BOULDERBADGE"] == 1)
ck("...nor a third", not ex._count_blackout("badge:BOULDERBADGE", dict(obs)))
obs2 = {"money": 329, "party": [{"species": "CHARMANDER", "level": 15, "hp": 41, "max_hp": 41},
                                {"species": "NIDORAN_F", "level": 13, "hp": 33, "max_hp": 33}]}
ck("a later wipe, with the money halved again, counts",
   ex._count_blackout("badge:BOULDERBADGE", obs2) and ex._blackouts["badge:BOULDERBADGE"] == 2)
ck("no target, no count", not ex._count_blackout(None, obs2))

src = Path("planner/executor.py").read_text()
ck("every detector goes through the one counter", src.count("self._count_blackout(") == 4
   and "self._blackouts.get(self._cur_target, 0) + 1" not in src
   and "self._blackouts.get(tk0, 0) + 1" not in src)
ck("the party's HP is written into every round's stuck note",
   'stuck_note += "\\nYOUR PARTY RIGHT NOW: " + "; ".join(_pl) + "."' in src
   and src.index('stuck_note += "\\nYOUR PARTY RIGHT NOW: "') < src.index("_wn = getattr(self, \"_wipe_note\", None)"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
