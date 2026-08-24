"""A thing you have stood beside is not out of reach.

Doors learned this (shut_settings: "looked at it with the statues PRESSED
and with them UNPRESSED"); things never did. POKEMON_MANSION_B1F's two item
balls read "not walkable-to right now" on 73 pages and were plainly
reachable on 8 — the run HAD walked to them and pressed them — and nothing
on the page remembered it, so the run concluded "the items there remain
unreachable" and left to hunt the Secret Key elsewhere (2026-08-24).
"""
import re
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


class Ex:
    reach_settings = {"POKEMON_MANSION_B1F": {
        "ONE_SETTING": ["unpressed"],
        "BOTH_SETTINGS": ["pressed", "unpressed"]}}

    def _where(self, o):
        return f"{o['map']['id']}|{o['player']['x']},{o['player']['y']}"

    def __getattr__(self, k):
        return {}


def line_for(key, kind="item", status="untouched"):
    obs = {"map": {"id": "POKEMON_MANSION_B1F", "warps": []},
           "player": {"x": 20, "y": 1}, "party": [], "bag": {}}
    c = ledger.Candidate(key=key, kind=kind, status=status,
                         x=5, y=13, reachable=False)
    out = ledger.render([c], Ex(), obs)
    return [l for l in out.splitlines()
            if key in l and re.match(r"\s*\d+\.", l)][0]


l1 = line_for("ONE_SETTING")
ck("one setting recorded: says it was reached before", "REACHED IT BEFORE" in l1)
ck("...and names that setting", "UNPRESSED" in l1)
ck("...and does not claim the other", "PRESSED and UNPRESSED" not in l1)

l2 = line_for("BOTH_SETTINGS")
ck("both settings recorded: names both", "PRESSED and UNPRESSED" in l2)

l3 = line_for("NEVER_REACHED")
ck("nothing recorded: says nothing about settings",
   "REACHED IT BEFORE" not in l3)

l4 = line_for("BOTH_SETTINGS", kind="trainer", status="unreachable")
ck("it reaches non-item things too", "REACHED IT BEFORE" in l4)

# a DOOR keeps its own wording, not this one
l5 = line_for("BOTH_SETTINGS", kind="door", status="unreachable")
ck("a door is left to the door wording", "REACHED IT BEFORE" not in l5)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
