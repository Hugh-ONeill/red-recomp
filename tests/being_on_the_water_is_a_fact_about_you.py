#!/usr/bin/env python3
"""Whether you are on the water is a fact about you (2026-09-05).

The observation carried x, y, facing and moving for the player and nothing
else, so with the party afloat in the Seafoam Islands every page described it
as if it stood on land, its own plans read "I am not standing on a water tile",
and the only way it learned otherwise was pressing SURF again and being told
"you are ALREADY on the water" — a refusal doing a fact's job (user: "its on
the water now"). The sprite on screen is a Pokemon carrying you across the
waves. Now the flag is exported and the page says it at the head, where every
op's reader sees it.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
ex = E.Executor.__new__(E.Executor)
ex.visits, ex.explored = {"SEAFOAM_ISLANDS_B3F|14,0": 3}, {}
ex._where = lambda o: "SEAFOAM_ISLANDS_B3F|14,0"

def page(surfing):
    obs = {"mode": "overworld", "bag": {},
           "player": {"x": 17, "y": 2, "facing": "down", "moving": False, "surfing": surfing},
           "map": {"id": "SEAFOAM_ISLANDS_B3F", "region": "14,0", "warps": [],
                   "connections": {}, "objects": [], "frontier": []}}
    return L.render([], ex, obs, "map:SEAFOAM_ISLANDS_B2F")

t = page(True)
ck("afloat, the page says so at the head", "YOU ARE ON THE WATER right now" in t, t[:400])
ck("...that water is what you can walk on", "WATER is what you can walk on" in t, t[:400])
ck("...that you leave it only at a shore", "only where the shore lets you off" in t, t[:400])
ck("...and that SURF again is how you get off, not a move",
   "that is how you get OFF" in t and "does not move you" in t, t[:400])
ck("on foot the page says none of it", "YOU ARE ON THE WATER" not in page(False))
ck("...and an observation with no such field is treated as on foot",
   "YOU ARE ON THE WATER" not in page(None))
ck("it never says where to swim", "swim to" not in t.lower() and "you should" not in t.lower())

lua = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim exports the engine's own flag",
   "surfing = p.surfing and true or false }" in lua)
ck("...with the reason recorded", "WHETHER YOU ARE ON THE WATER IS A FACT ABOUT YOU" in lua)
ct = (ROOT / "tests" / "contract.py").read_text()
ck("the contract checks the field", 'Field("player.surfing"' in ct)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
