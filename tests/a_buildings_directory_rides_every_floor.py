#!/usr/bin/env python3
"""A sign about the whole building rides every floor of it (2026-09-04).

The run read the Celadon department store's directory on 1F — "1F: SERVICE
COUNTER 2F: TRAINER'S MARKET ... 5F: DRUG STORE ROOFTOP SQUARE: VENDING
MACHINES" — and the hint sat under CELADON_MART_1F|1,1, shown only there. On
5F, in the lift and on 3F the page carried the lift panel ("1F, 2F, 3F, 4F,
5F") and nothing about a roof; the run wrote "1F, 2F, 3F, 5F checked, 4F is
the only floor left" and rode the lift (user: "has it read the floor
directory, is the fact that theres vending machines on the roof in its
ledger?" — it was, on one floor). Its own reading, repeated where it applies;
which floor to go to is not said.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

DIR = ("TEXT_CELADONMART1F_DIRECTORY_SIGN: 1F: SERVICE     COUNTER 2F: TRAINER'S     MARKET "
       "3F: TV GAME SHOP 4F: WISEMAN GIFTS 5F: DRUG STORE ROOFTOP SQUARE: VENDING MACHINES")
e = object.__new__(E.Executor)
e.hints = {"CELADON_MART_1F|1,1": [DIR, "TEXT_CELADONMART1F_CURRENT_FLOOR_SIGN: 1F: SERVICE     COUNTER"],
           "CELADON_MART_5F|1,1": ["CELADONMART5F_SAILOR: I want a drink!"],
           "CELADON_CITY|2,1": ["TEXT_CELADONCITY_DEPTSTORE_SIGN: Find what you need at CELADON DEPT. STORE!"],
           "SILPH_CO_1F|0,0": ["TEXT_SILPHCO1F_SIGN: 1F: RECEPTION 2F: OFFICES"]}
e._where = lambda o: str((o.get("map") or {}).get("id")) + "|1,1"

w = e._building_directory_words({"map": {"id": "CELADON_MART_5F"}})
ck("on 5F the 1F directory is on the page", "ROOFTOP SQUARE: VENDING MACHINES" in w and "on CELADON_MART_1F:" in w, w)
ck("...as the run's own reading", "as you read it" in w, w)
ck("...with the lift/building distinction and no floor named as the way", "the LIFT serves" in w and "take" not in w.lower(), w)
ck("a current-floor sign is not a directory", "CURRENT_FLOOR_SIGN" not in w, w)
ck("another building's directory stays in that building", "SILPHCO" not in w, w)
w2 = e._building_directory_words({"map": {"id": "CELADON_MART_ELEVATOR"}})
ck("in the lift car too", "ROOFTOP SQUARE" in w2, w2)
w3 = e._building_directory_words({"map": {"id": "CELADON_MART_ROOF"}})
ck("on the roof too", "ROOFTOP SQUARE" in w3, w3)
ck("on 1F, where the hint already shows, nothing is repeated", e._building_directory_words({"map": {"id": "CELADON_MART_1F"}}) == "")
ck("a one-room map has no building", e._building_directory_words({"map": {"id": "CELADON_CITY"}}) == "")
e2 = object.__new__(E.Executor)
ck("an executor from before the hints existed does not die of it",
   e2._building_directory_words({"map": {"id": "CELADON_MART_5F"}}) == "")

bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
