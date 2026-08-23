"""The statues share ONE setting, and we had it in hand.

Pressing any Mansion statue flips the same wall blocks on every floor
(story6.lua's shared EVENT_MANSION_SWITCH_ON).  The run pressed 1F, found
its door still shut, walked up and pressed 2F -- putting the whole Mansion
straight back -- and did that for a whole attempt, reporting "activated"
each time and getting no nearer the basement.  The setting was in the
observation the whole time and stripped before the model saw anything.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import ledger

class _Ex:
    explored = {"POKEMON_MANSION_1F|1,1": {}}
    visits = {"POKEMON_MANSION_1F|1,1": 24}
    frontier = {}
    def _where(self, _o): return "POKEMON_MANSION_1F|1,1"
    def __getattr__(self, _n): return {}

def head(switches, on):
    m = {"id": "POKEMON_MANSION_1F", "region": "1,1",
         "switch_statues": switches}
    if on is not None:
        m["switches_on"] = on
    return ledger.render([], _Ex(), {"party": [], "map": m}).splitlines()[0]

SW = [{"x": 2, "y": 5, "reachable": True}]

h_on = head(SW, True)
h_off = head(SW, False)

ck("it says the setting is shared", "SHARE ONE SETTING" in h_on)
ck("pressed reads as pressed", "currently PRESSED" in h_on)
ck("unpressed reads as unpressed", "currently UNPRESSED" in h_off)
ck("it warns a second press undoes the first",
   "puts the first back" in h_on)
ck("the statue is still named", "(2,5)" in h_on)
ck("it still says press facing up", "FACING" in h_on)
ck("it does not say which setting is wanted",
   "should" not in h_on.lower() and "you need" not in h_on.lower())

# a map with statues but no known setting says nothing about sharing
h_unknown = head(SW, None)
ck("unknown setting stays quiet about sharing",
   "SHARE ONE SETTING" not in h_unknown and "(2,5)" in h_unknown)
ck("no statues, no line at all", "SWITCH STATUE" not in head([], None))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD:", h_on[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
