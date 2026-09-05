#!/usr/bin/env python3
"""A slope moves the ground under every op, so the page says so (2026-09-05).

Cycling Road pulls the bike one cell SOUTH on every idle poll
(field.forcedMovement.slopeMaps). The run was told this only when a NORTHWARD
cross was refused, so sweep, explore and every walk worked the map with no idea
the ground moves under them — a 300-step sweep read as ordinary exploring
(user: "i dont think the shim handles exploration on a slope very well"). The
shim now publishes the slope on the observation and the page says it at the
head, where every op's reader sees it. Which way it pulls is on the screen the
moment you stop pedalling; nothing here says where to go.

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
ex.visits, ex.explored = {"ROUTE_17|7,31": 2}, {}
ex._where = lambda o: "ROUTE_17|7,31"
def page(slope):
    m = {"id": "ROUTE_17", "region": "7,31", "warps": [], "connections": {},
         "objects": [], "frontier": []}
    if slope: m["slope"] = slope
    return L.render([], ex, {"mode": "overworld", "player": {"x": 7, "y": 31},
                             "bag": {}, "map": m}, "map:ROUTE_18")
t = page("south")
ck("the page says the map is a slope", "THIS MAP IS A SLOPE" in t, t[:400])
ck("...and which way it pulls you", "moves you one cell south" in t, t[:400])
ck("...that walking the other way still works while you keep walking",
   "still works while you keep walking" in t, t[:400])
ck("...and what a pause costs", "every pause gives some back" in t, t[:400])
ck("...naming the cost to exploring, since that is what reads it",
   "exploring here costs more steps uphill than down" in t, t[:400])
ck("an ordinary map says nothing of the kind", "THIS MAP IS A SLOPE" not in page(None))
ck("it never says which way to travel", "go south" not in t.lower() and "you should" not in t.lower())

lua = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim publishes it from the engine's own slope list",
   'for _, mm in ipairs((fm and fm.slopeMaps) or {}) do' in lua
   and 'o.map.slope = "south"' in lua)
ck("...and the older northward-cross refusal is untouched",
   "THIS MAP IS A SLOPE: on the bike here the game moves you " in lua)
ct = (ROOT / "tests" / "contract.py").read_text()
ck("the contract knows the field, and that it is absent off a slope",
   'Field("map.slope"' in ct and "required=False" in ct)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
