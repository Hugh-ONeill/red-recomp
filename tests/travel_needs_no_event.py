"""Arriving somewhere leaves no event at all.

The place-guard exists for a DEED done in a place: "Wake the Snorlax
sleeping on ROUTE 12" was once judged done on EVENT_BEAT_ROUTE16_SNORLAX,
the other Snorlax a map away.  But for a TRAVEL objective the place IS the
deed and Kanto writes no flag for standing on a shore, so "Reach
ROUTE_20|58,9, the shore of Route 20 on the far side of the Seafoam
Islands" was refused -- the run having just crossed the whole island, with
its area predicate satisfied and its visit count up -- because the events
mentioning Route 20 are a rival battle on Route 22 and a Snorlax on Route
12.  The already-stood-in validator has drawn this line all along.
"""
import re
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

TRAVEL = ("go", "travel", "return", "reach", "head", "walk", "fly",
          "enter", "visit", "arrive")

def refuses(goal, bearing, gained=""):
    """The guard as author.py applies it."""
    gained_speaks = bool(re.search(r"items gained:|badges earned:|"
                                   r"events that fired:", gained or ""))
    if str(goal).strip().split()[:1] and \
            str(goal).strip().split()[0].lower().rstrip(",:") in TRAVEL:
        gained_speaks = True
    place = re.search(r"\b(ROUTE\s*\d+|[A-Z][a-z]+\s+(?:CITY|TOWN|ISLAND))\b",
                      goal, re.I)
    if place and bearing and not gained_speaks:
        want = re.sub(r"\s+", "_", place.group(1).strip()).upper()
        names = re.findall(r"EVENT_[A-Z0-9_]+", bearing)
        if names and not any(want in n or want.replace("ROUTE_", "ROUTE") in n
                             for n in names):
            return True
    return False

ELSEWHERE = "EVENT_1ST_ROUTE22_RIVAL_BATTLE, EVENT_BEAT_ROUTE12_SNORLAX"

ck("the travel leg is no longer refused",
   not refuses("Reach ROUTE_20|58,9, the shore of Route 20 on the far side "
               "of the Seafoam Islands", ELSEWHERE))
for verb in ("Go", "Travel", "Return", "Head", "Fly", "Enter", "Visit",
             "Arrive", "Walk"):
    ck(f"{verb} is travel too",
       not refuses(f"{verb} to ROUTE 20", ELSEWHERE))

# the case the guard was built for still refuses
ck("a deed in a place still needs the right place",
   refuses("Wake the Snorlax sleeping on ROUTE 12", 
           "EVENT_BEAT_ROUTE16_SNORLAX"))
ck("a deed whose events DO name the place is fine",
   not refuses("Wake the Snorlax sleeping on ROUTE 12",
               "EVENT_BEAT_ROUTE12_SNORLAX"))
ck("an item gained still speaks for a deed",
   not refuses("Exchange the voucher in Cerulean CITY", ELSEWHERE,
               gained="items gained: BICYCLE x1"))
ck("no bearing events, nothing to refuse on",
   not refuses("Defeat the trainer on ROUTE 20", ""))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
