#!/usr/bin/env python3
"""Wild ground elsewhere names its species (2026-09-04).

The "wild ground elsewhere" note gave other maps' level bands and exp per
grind and never who lives there, so a catch or type gate read "ROUTE_11 L9-L17
in 217 battle(s)" with fifty Drowzee behind the number. The run's own tally now
rides each row, three species at most; what a species is stays the model's.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
e._wild_lv = {"ROUTE_11": {"lo": 9, "hi": 17, "n": 217}, "ROUTE_24": {"lo": 7, "hi": 14, "n": 863}, "DIGLETTS_CAVE": {"lo": 15, "hi": 21, "n": 20}}
e._offered = {"ROUTE_11": {"SPEAROW": 89, "EKANS": 78, "DROWZEE": 50}, "ROUTE_24": {"ODDISH": 202, "KAKUNA": 172, "PIDGEY": 165, "WEEDLE": 158, "ABRA": 117}}
e._grind_exp = {}
e.explored = {"ROUTE_11|9,0": {}, "ROUTE_24|0,0": {}, "DIGLETTS_CAVE|1,1": {}}
e._where = lambda o: "SAFFRON_CITY|12,0"
e._route = lambda a, b: ["x"] * (2 if b.startswith("ROUTE_11") else 9 if b.startswith("ROUTE_24") else 3)
w = e._wild_elsewhere_note("SAFFRON_CITY", {"map": {"id": "SAFFRON_CITY"}})
ck("each row names who was fought there", "ROUTE_11 L9-L17 in 217 battle(s) (SPEAROW, EKANS, DROWZEE)" in w, w)
ck("...three species at most", "ODDISH, KAKUNA, PIDGEY)" in w and "WEEDLE" not in w, w)
ck("...a map with fights but no tally keeps its old row", "DIGLETTS_CAVE L15-L21 in 20 battle(s)," in w, w)
ck("nothing about what a species is", "PSYCHIC" not in w and "-type" not in w and "Ground type" not in w, w)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
