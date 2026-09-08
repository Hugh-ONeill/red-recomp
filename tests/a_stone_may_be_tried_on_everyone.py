#!/usr/bin/env python3
"""use_item with an evolution stone and slot "any" tries each party member
in turn, stops at the one it evolves, and an evolution is said in the op's
own words.

Run 16 (2026-09-08): three party members that evolve by stone rode along
with two MOON STONEs all day. Using a stone on a member it does not suit
costs nothing — "It won't have any effect", stone kept — so "use it on
whoever takes it" is one decision the model can make in one op: spending
the stone is its call, finding the taker is the party menu's own answer,
member by member. WHICH species a stone suits is never said by the harness;
the game says it by evolving them. And a stone that worked used to come
back as a flat "used MOON_STONE": now it names who evolved into what.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
st = (ROOT / "planner" / "state_text.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


u = sh[sh.index("function OPS.use_item(G, c)"):sh.index("function OPS.use_item(G, c)") + 9000]
ck("a stone with slot any is tried on each member in turn", 'if c.item:match("_STONE$") and tostring(c.slot or ""):lower() == "any" then' in u and "for i = 1, #party do" in u)
ck("...stopping at the one it evolves and naming who it had no effect on", 'if ok and tostring(why):find("EVOLVED") then' in u and "it had no effect on " in u)
ck("...and saying so when nobody in the party is one it suits", "tried on every party member" in u and "No one in this party is one it suits as they stand" in u)
ck("...without the harness naming any species", not any(w in u for w in ("NIDORINA", "NIDOQUEEN", "EEVEE", "VAPOREON", "GLOOM")))
ck("the species is read before the item is used", "local _sp0 = mon and mon.species" in sh)
ck("an evolution is reported in the op's own words", 'return true, ("used %s on %s — it EVOLVED into %s"):format(' in sh)
ck("the catalogue names slot any for stones", 'An evolution STONE may be sent with "slot":"any"' in ex)
ck("the author's bag line carries the stone's cost of a wrong try", 'def _stone_word(k):' in st and "{_stone_word(k)}" in st and "keeps the stone" in st)
sys.exit(1 if fails else 0)
