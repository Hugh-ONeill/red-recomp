#!/usr/bin/env python3
"""A slot is a kind, not a count.

The bag holds twenty KINDS. "tossed 1 POKE_BALL, 11 left" read as room made,
and the run tossed one ball of twelve to make space; the bag line offered
USING, SELLING, TOSSING and STORING as four equal ways to "free the slot",
reversible last, and the run's routine answer was to throw away its TMs —
the one-of-a-kind items, which ARE the quick frees and the ones a toss loses
for good (2026-09-03; user: "throwing out one item of twenty doesnt lighten
the bag, only throwing out something with 1 left of its kind will free bag
space" / "i honestly hate that its solution is routinely 'lets throw away
usable TMs'").

Now a partial toss, sale or deposit says NO slot freed and why, on the op
that did it; and the bag line leads with the rule, names the kinds held ONE
of and the stacks, puts the reversible way first with the nearest walked PC
named, and says what a TM toss costs. The choice stays the model's.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

e = object.__new__(E.Executor)
e.visits = {"ROUTE_10|0,4": 40, "ROCK_TUNNEL_POKECENTER|0,3": 3, "CERULEAN_POKECENTER|0,3": 41}
e.explored = {}
e._where = lambda obs: "ROUTE_10|0,4"
e._route = lambda a, b: ["x"] if b.startswith("ROCK_TUNNEL_POKECENTER") else ["x"] * 5
bag = {"POKE_BALL": 11, "POTION": 4, "TM_DIG": 1, "TM_WATER_GUN": 1, "HM_CUT": 1,
       "BICYCLE": 1, "MOON_STONE": 1, "ESCAPE_ROPE": 1, "REPEL": 1, "OLD_ROD": 1,
       "DOME_FOSSIL": 1, "S_S_TICKET": 1, "TOWN_MAP": 1, "MAX_ETHER": 1,
       "TM_TELEPORT": 1, "TM_THUNDERBOLT": 1, "TM_THUNDER_WAVE": 1, "TM_MEGA_PUNCH": 1}
line = e._bag_pressure_line({"bag": bag})
ck("at 18 kinds the line speaks", line.startswith("\nYOUR BAG holds 18 of 20 KINDS"), line[:80])
ck("it leads with the rule", "A slot is a KIND, not a count" in line
   and "the slot frees only when the LAST of that kind goes" in line)
ck("it names the kinds held one of", "Kinds you hold ONE of (one action frees the slot): BICYCLE" in line)
ck("...and the stacks with their counts", "Stacks (the whole count must go): POKE_BALL x11, POTION x4." in line)
ck("the reversible way comes first, with the nearest walked PC named",
   line.index("STORING at a Pokemon Center's PC") < line.index("USING spends one")
   < line.index("SELLING at a mart clerk") < line.index("TOSSING destroys")
   and "nearest you have walked into is ROCK_TUNNEL_POKECENTER, 1 leg(s) away" in line)
ck("a TM toss is priced", "a TM tossed is a move the party will never get from it" in line
   and "TM_DIG" in line.split("you hold one each of")[1])
ck("below 18 kinds it says nothing", e._bag_pressure_line({"bag": {"POTION": 3}}) == "")
full = dict(bag); full.update({"ANTIDOTE": 1, "BURN_HEAL": 1})
ck("at 20 it says FULL", "20 of 20 KINDS: FULL" in e._bag_pressure_line({"bag": full}))
e2 = object.__new__(E.Executor); e2.visits = {}; e2.explored = {}
e2._where = lambda obs: "X|0,0"; e2._route = lambda a, b: None
ck("with no walked Center, no PC is named",
   "nearest you have walked into" not in e2._bag_pressure_line({"bag": bag}))

shim = (ROOT / "harness" / "shim.lua").read_text()
ck("a partial toss says NO slot freed, on the op", 'left — NO slot freed: a slot is a "' in shim
   and shim.count("NO slot freed: a slot is a KIND") >= 2)
ck("...and so does a partial sale", 'or (" — NO slot freed: a slot is a KIND, and the " .. have .. " "' in shim)
ck("...and a partial deposit", 'after > 0 and (" — NO slot freed: a slot is a KIND, and the "' in shim)
src = (ROOT / "planner" / "executor.py").read_text()
ck("the page uses the new line", "memory += self._bag_pressure_line(start)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
