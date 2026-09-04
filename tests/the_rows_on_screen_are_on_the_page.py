#!/usr/bin/env python3
"""The rows on screen are on the page (2026-09-04).

At the Celadon roof vending machine the game window showed FRESH WATER, SODA
POP, LEMONADE; the page said only "a box is up, saying: 'Hi there! May I help
you?' ... tap b to close it", and the run closed it, standing on the one thing
its next step was for (user: "the vending machine page is literally just a
display of fresh water, lemonade, soda pop"). The shim now exports the list's
rows, numbered as they read (scalars() had dropped `items`), and the ledger's
not-the-overworld line prints them with the op that picks one. Which row is
not said.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402
import ledger                                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ex = E.Executor.__new__(E.Executor)
ex.visits, ex.explored = {}, {}
ex._where = lambda o: "None|None"
obs = {"mode": "ui", "last_text": "Hi there! May I help you?",
       "recent_text": "Hi there! May I help you?",
       "ui": {"rows": ["1=FRESH WATER ¥200", "2=SODA POP ¥300", "3=LEMONADE ¥350"]}}
t = ledger.render([], ex, obs, "item:FRESH_WATER")
ck("a list on screen is called a list", "a LIST is up" in t, t)
ck("...and its rows are printed as they read", "1=FRESH WATER ¥200" in t and "3=LEMONADE ¥350" in t, t)
ck("...with the op that picks a row", '{"op":"menu","index":N}' in t, t)
ck("...and the op that closes it without picking", '{"op":"tap","btn":"b"}' in t, t)
ck("the box's words still ride along", "May I help you" in t, t)
ck("which row is not said", "index\":1" not in t and "FRESH_WATER" not in t.replace("FRESH WATER", ""), t)
obs2 = {"mode": "ui", "last_text": "So! You want the fire POKéMON, CHARMANDER?",
        "recent_text": "So! You want the fire POKéMON, CHARMANDER?", "ui": {"is_choice": True}}
t2 = ledger.render([], ex, obs2, "party_size:1")
ck("a box with no rows reads as before", "a box is up" in t2 and "LIST" not in t2, t2)
obs3 = dict(obs); obs3["ui"] = {"rows": ["1=1F", "2=2F", "3=3F"], "title": "FLOOR"}
t3 = ledger.render([], ex, obs3, "map:X")
ck("a titled list carries its title", "(FLOOR)" in t3 and "1=1F" in t3, t3)

lua = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim exports the rows, numbered as they read",
   "o.ui.rows = _rows" in lua and '("%d=%s"):format(\n          i, tostring(r.label or r.value or "?"))' in lua)
ck("...and the title when the list has one", "if top.title then o.ui.title = tostring(top.title) end" in lua)

bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
