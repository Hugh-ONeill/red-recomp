#!/usr/bin/env python3
"""Grass seen but never fought in is named (2026-09-04).

The wild-ground ledger only ever held maps the run had FOUGHT on, so a grind
step saw levels and species for those and nothing at all for grass it had
walked past without a battle (user: "there are other spots that would be better
for grinding but it hasnt grinded in those spots yet so it doesnt have the
evidence"). The shim now counts grass cells and cave floor in the footprint,
the executor keeps the largest count per map, and both the page and the plan
author list walked ground with wild ground on it that has never been fought
on. Who lives there, and at what level, is still learned only by fighting.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402
import author as A                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

e = object.__new__(E.Executor)
e._wild_lv = {"ROUTE_11": {"lo": 9, "hi": 17, "n": 217}}
e._offered = {"ROUTE_11": {"SPEAROW": 89, "EKANS": 78, "DROWZEE": 50}}
e._grind_exp = {}
e._wild_seen = {"ROUTE_11": {"grass": 60, "cave": 0}, "ROUTE_12": {"grass": 34, "cave": 0},
                "ROCK_TUNNEL_1F": {"grass": 0, "cave": 120}, "SAFFRON_CITY": {"grass": 0, "cave": 0},
                "ROUTE_8": {"grass": 12, "cave": 0}}
e.explored = {"ROUTE_11|9,0": {}, "ROUTE_12|8,0": {}, "ROCK_TUNNEL_1F|4,2": {}, "ROUTE_8|16,2": {}}
e._where = lambda o: "SAFFRON_CITY|12,0"
e._route = lambda a, b: ["x"] * (3 if b.startswith("ROUTE_12") else 7 if b.startswith("ROCK") else 2 if b.startswith("ROUTE_8") else 1)
obs = {"map": {"id": "SAFFRON_CITY"}}
w = e._wild_never_fought_note("SAFFRON_CITY", obs)
ck("walked grass never fought in is named, nearest first",
   w.index("ROUTE_8 (12 grass cell(s) seen, 2 walked leg(s) away)") < w.index("ROUTE_12 (34 grass cell(s) seen, 3 walked leg(s) away)"), w)
ck("...cave floor counts as wild ground", "ROCK_TUNNEL_1F (120 cave-floor cell(s) seen" in w, w)
ck("...a map already fought on is not in this list", "ROUTE_11" not in w, w)
ck("...a map with no wild ground seen is not either", "SAFFRON_CITY" not in w.replace("SAFFRON_CITY|12,0", ""), w)
ck("...and it says what is NOT known", "who lives there, and at what level, is not known" in w, w)
full = e._wild_elsewhere_note("SAFFRON_CITY", obs)
ck("the elsewhere note carries both halves", "ROUTE_11 L9-L17 in 217 battle(s) (SPEAROW, EKANS, DROWZEE)" in full and "NEVER FOUGHT ON" in full, full)
e2 = object.__new__(E.Executor); e2._wild_lv = {}; e2._offered = {}; e2._grind_exp = {}; e2.explored = {}; e2._where = lambda o: "X|0,0"; e2._route = lambda a, b: None
ck("an executor with no wild_seen ledger says nothing", e2._wild_never_fought_note("X", obs) == "")

REC = {"offered": {"ROUTE_11": {"SPEAROW": 89, "DROWZEE": 50}}, "wild_lv": {"ROUTE_11": {"lo": 9, "hi": 17, "n": 139}},
       "wild_seen": {"ROUTE_11": {"grass": 60, "cave": 0}, "ROUTE_12": {"grass": 34, "cave": 0}, "ROCK_TUNNEL_1F": {"grass": 0, "cave": 120}}}
t = A.wild_met_text(REC)
ck("the author's block lists the fought map and the never-fought ground", "ROUTE_11 (139 wild fight(s), levels 9-17)" in t and "NEVER FOUGHT ON" in t and "ROCK_TUNNEL_1F (0 grass cell(s), 120 cave-floor cell(s) seen)" in t and "ROUTE_12 (34 grass cell(s) seen)" in t, t)
ck("...with nothing fought anywhere, the never-fought tail still speaks", "NEVER FOUGHT ON" in A.wild_met_text({"wild_seen": {"ROUTE_12": {"grass": 34, "cave": 0}}}))
ck("...and with nothing at all, silence", A.wild_met_text({}) == "")
lua = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim counts grass and cave floor in the footprint", "m.wild_seen = { grass = g, cave = cv }" in lua and 'if _lm:isGrassCell(x, y) then g = g + 1 end' in lua)
ct = (ROOT / "tests" / "contract.py").read_text()
ck("the contract checks the field", 'Field("map.wild_seen.grass"' in ct and 'Field("map.wild_seen.cave"' in ct)
src = (ROOT / "planner" / "executor.py").read_text()
ck("the executor keeps the largest count per map and persists it", '"wild_seen": getattr(self, "_wild_seen", {})' in src and 'self._wild_seen = data.get("wild_seen") or {}' in src and 'self._wild_seen[_mid] = {' in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:500]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
