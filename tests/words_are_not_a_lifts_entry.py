#!/usr/bin/env python3
"""Words are not a lifts entry: a need the plan names for a way that turned
the run back is tallied on that way's row, as the model's own word read back.

Eight rounds in a row (2026-09-04, leg 28) the plan said "a Ghost blocks the
path to the 7th floor on the 6th floor and that I need the Silph Scope", and
every round the door's row read "nothing named yet as what lifts it", because
the reply never carried a "blockers" key. The ladder's plan-writer then read
the same "nothing named". The row now carries what the plans said and how
often, and the entry that would make it count. Nothing says whether the word
is right or where the thing is.

Synthetic: no game, no model.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

GHOST = ('a GHOST appeared on the way there — "Be gone... Intruders..." — '
         'you pressed FIGHT: "GYARADOS is too scared to move!"')
WATER = ("the walk was fenced — WATER at (7,4) — a walk will not cross water; "
         "nobody in the party knows SURF")
TREE = "the walk was fenced — CUT_TREE (a bush CUT clears) at 5,8"

def fresh(bag=None):
    e = object.__new__(E.Executor)
    e.blockers = {
        "POKEMON_TOWER_6F|10,2|9,16": {"where": "POKEMON_TOWER_6F|10,2", "key": "9,16", "kind": "door", "n": 10, "what": GHOST, "lifts": None, "cleared": False},
        "ROUTE_12|8,0|west": {"where": "ROUTE_12|8,0", "key": "west", "kind": "seam", "n": 1, "what": WATER, "lifts": None, "cleared": False},
        "ROUTE_9|6,2|west": {"where": "ROUTE_9|6,2", "key": "west", "kind": "seam", "n": 44, "what": TREE, "lifts": None, "cleared": False},
        "ROUTE_9|50,6|west": {"where": "ROUTE_9|50,6", "key": "west", "kind": "seam", "n": 29, "what": TREE, "lifts": None, "cleared": False},
        "ROUTE_9|0,8|east": {"where": "ROUTE_9|0,8", "key": "east", "kind": "seam", "n": 2, "what": TREE, "lifts": None, "cleared": True},
        "ROUTE_6|0,3|north": {"where": "ROUTE_6|0,3", "key": "north", "kind": "seam", "n": 10, "what": WATER, "lifts": {"has_item": {"HM_SURF": 1}}, "cleared": False},
    }
    return e, {"map": {"id": "POKEMON_TOWER_1F"}, "bag": dict(bag or {})}

TOWER_PLAN = ("I am currently at the base of the Pokemon Tower. I know from previous attempts that a Ghost "
              "blocks the path to the 7th floor on the 6th floor and that I need the Silph Scope to proceed. "
              "I will check Mr. Fuji's house first.")
MART_PLAN = ("I need FRESH WATER to pass the guards on Route 8 and reach the Silph Scope, which is required "
             "to get the Poke Flute from Mr. Fuji. I will now go to the 4th floor to see if FRESH WATER is sold there.")

e, obs = fresh({"HM_CUT": 1, "POTION": 4})
got = e._tally_named_needs(TOWER_PLAN, obs)
ghost = e.blockers["POKEMON_TOWER_6F|10,2|9,16"]
ck("the ghost door's row tallies the Scope the plan said it needs", ghost.get("named") == {"SILPH_SCOPE": 1}, got)
ck("...and nothing lands on the fences the sentence did not concern",
   not any(b.get("named") for k, b in e.blockers.items() if "TOWER" not in k), got)

got = e._tally_named_needs(MART_PLAN, obs)
ck("'I need FRESH WATER for the guards' does not land on a WATER fence",
   not e.blockers["ROUTE_12|8,0|west"].get("named"), got)
ck("...nor on the ghost door: that sentence never names the ghost", ghost.get("named") == {"SILPH_SCOPE": 1}, got)

got = e._tally_named_needs("I need HM Cut to cut the tree blocking Route 9.", obs)
ck("a need the bag already meets is not a need", got == [] and not e.blockers["ROUTE_9|6,2|west"].get("named"))

e2, obs2 = fresh({})
got = e2._tally_named_needs("I need HM Cut to cut the tree blocking Route 9.", obs2)
ck("...with the bag empty it lands on every live row that fence concerns",
   sorted(k for k, _ in got) == ["ROUTE_9|50,6|west", "ROUTE_9|6,2|west"] and all(nm == "HM_CUT" for _, nm in got), got)
ck("...never on a cleared row", not e2.blockers["ROUTE_9|0,8|east"].get("named"))
ck("...never on a row that already has a lifts entry", not e2.blockers["ROUTE_6|0,3|north"].get("named"))

e3, obs3 = fresh({})
got = e3._tally_named_needs("The Silph Scope reveals the ghost. The ghost is scary.", obs3)
ck("a sentence with no need-word tallies nothing", got == [])
got = e3._tally_named_needs("I need the Silph Scope for the ghost; without the SILPH_SCOPE the ghost stays.", obs3)
ck("twice in one plan counts once per round", e3.blockers["POKEMON_TOWER_6F|10,2|9,16"]["named"] == {"SILPH_SCOPE": 1}, got)
e3._tally_named_needs("I still need the Silph Scope to pass the Ghost.", obs3)
ck("...and the next round counts again", e3.blockers["POKEMON_TOWER_6F|10,2|9,16"]["named"] == {"SILPH_SCOPE": 2})
got = e3._tally_named_needs("I need a Pokéflute to wake the ghost.", obs3)
ck("prose spellings are the engine's items", got == [("POKEMON_TOWER_6F|10,2|9,16", "POKE_FLUTE")], got)

w = E.Executor._named_needs_words(e3.blockers["POKEMON_TOWER_6F|10,2|9,16"])
ck("the row says what was named and how often", "SILPH_SCOPE 2x" in w and "POKE_FLUTE 1x" in w, w)
ck("...and the entry that would make it count, in the model's own item",
   '"lifts":{"has_item":{"SILPH_SCOPE":1}}' in w and '"where":"POKEMON_TOWER_6F|10,2"' in w, w)
ck("...and nothing about where the thing is", "SILPH_CO" not in w and "HIDEOUT" not in w and "Rocket" not in w)
ck("an un-named row adds nothing", E.Executor._named_needs_words({"where": "X"}) == "")

e4 = object.__new__(E.Executor)
ck("an executor from before the ledger existed does not die of it", e4._tally_named_needs(TOWER_PLAN, {}) == [])

src = (ROOT / "planner" / "executor.py").read_text()
ck("the tally runs on every plan the model speaks", "_nn = self._tally_named_needs(plan_said, obs)" in src
   and 'self.log("need_named_not_written"' in src)
ck("the blockers page carries it", 'line += (" — nothing named yet as what lifts it")\n                line += self._named_needs_words(b)' in src)

import author as A                                     # noqa: E402
with tempfile.TemporaryDirectory() as td:
    pth = Path(td) / "explored.json"
    pth.write_text(json.dumps({"blockers": e3.blockers,
                                "explored": {"POKEMON_TOWER_1F|9,1": {"door(10,17)": {"to": "LAVENDER_TOWN|6,0"}}}}))
    try:
        txt = A.observed_text(pth)
    except Exception as ex:                            # pragma: no cover
        txt = f"RAISED {ex!r}"
ck("the plan-writer's row carries the run's own word", "the run's own plans named SILPH_SCOPE 2x" in txt, txt[-600:])
ck("...marked as unverified", "its word, unverified" in txt)

bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:500]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
