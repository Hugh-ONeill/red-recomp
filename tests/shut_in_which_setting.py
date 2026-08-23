"""A door is only ever unreachable IN A SETTING, and a door the game has
answered in words is not an untried door.

Both facts were in the run's own history and on no page: six subgoals went
press -> walk -> press back -> walk against POKEMON_MANSION_1F's (21,23),
and Cinnabar's gym went on being advertised as "never taken from here"
after it had said "The door is locked..." (2026-08-23).
"""
import re
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class _Ex:
    def __init__(self, shut=None, hints=None):
        self.shut_settings = shut or {}
        self.hints = hints or {}

    def _where(self, obs):
        p = obs["player"]
        return f"{obs['map']['id']}|{p['x']},{p['y']}"

    def __getattr__(self, k):
        return {}


def line_for(shut, status="unreachable", key="21,23"):
    obs = {"map": {"id": "POKEMON_MANSION_1F", "warps": []},
           "player": {"x": 1, "y": 1}, "party": []}
    c = ledger.Candidate(key=key, kind="door", status=status)
    out = ledger.render([c], _Ex(shut=shut), obs)
    # the NUMBERED entry, not the header (which quotes the same coords)
    return [l for l in out.splitlines()
            if key in l and re.match(r"\s*\d+\.", l)][0]


both = {"POKEMON_MANSION_1F": {"21,23": ["pressed", "unpressed"]}}
one = {"POKEMON_MANSION_1F": {"21,23": ["unpressed"]}}

l1 = line_for(both)
ck("both settings seen: says so", "PRESSED and with them UNPRESSED" in l1)
ck("both settings seen: says no walk reached it either way",
   "either way" in l1)

l2 = line_for(one)
ck("one setting seen: names which", "UNPRESSED" in l2)
ck("one setting seen: says the other was never tried",
   "never been tried" in l2)
ck("one setting seen: does NOT claim both",
   "PRESSED and with them UNPRESSED" not in l2)

l3 = line_for({})
ck("nothing recorded: says nothing about settings",
   "setting" not in l3 and "UNPRESSED" not in l3)

# ...and the spoken answer rides on the door that gave it
c = ledger.Candidate(key="18,3", kind="door", status="untried")
c.spoke = "The door is locked..."
obs = {"map": {"id": "CINNABAR_ISLAND", "warps": []},
       "player": {"x": 1, "y": 0}, "party": []}
l4 = [l for l in ledger.render([c], _Ex(), obs).splitlines()
      if "18,3" in l and re.match(r"\s*\d+\.", l)][0]
ck("a door quotes what trying it said", "The door is locked" in l4)
ck("...as its own answer, not someone else's", "trying it said" in l4)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
