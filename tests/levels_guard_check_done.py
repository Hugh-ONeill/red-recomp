"""A level bar the party does not clear refuses check-done.

check-done has hard guards for places, badges and items — a claim the record
disproves is refused before the judge is asked. Levels had none, so "every
party member is at least level 50" was judged purely by the model doing
arithmetic across six members. It is the longest, dullest leg in the outline
and the easiest to wave through, and a leg crossed off never comes back: the
Elite Four would be reached underlevelled with no record of why.

Only the unambiguous scope is checked (EVERY / ALL / EACH party member). A
bar with no stated scope is left to the judge, because guessing it would be
the same mistake one layer down.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "planner"))
from author import _levels_not_reached as guard

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


LOW = ("standing in CINNABAR_POKECENTER with TENTACOOL L22 (WATER/POISON), "
       "NIDOQUEEN L46 (POISON/GROUND), CHARIZARD L64 (FIRE/FLYING)")
HIGH = ("standing in CINNABAR_POKECENTER with TENTACOOL L50 (WATER/POISON), "
        "NIDOQUEEN L51 (POISON/GROUND), CHARIZARD L64 (FIRE/FLYING)")
G = "every party member is at least level 50"

ck("refuses while one member is short", guard(G, LOW) is not None)
ck("...and names the offender's level", "L22" in (guard(G, LOW) or ""))
ck("allows once every member clears it", guard(G, HIGH) is None)
ck("exactly at the bar counts as clear",
   guard("every party member is at least level 46",
         "NIDOQUEEN L46 (POISON/GROUND)") is None)

ck("'all' is the same scope", guard("all party members at least level 50", LOW))
ck("'each' is the same scope", guard("each party member at least level 50", LOW))

# scope it does NOT claim to judge
ck("a bar with no scope is left to the judge",
   guard("the LEAD is at least level 50", LOW) is None)
ck("a goal with no level bar is untouched",
   guard("Defeat Blaine for the Volcano Badge", LOW) is None)
ck("no readable levels is not our call",
   guard(G, "standing in CINNABAR_POKECENTER with no party") is None)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
