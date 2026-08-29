#!/usr/bin/env python3
"""A step that names a Pokemon this world does not have says so.

Run 15, 2026-08-29 (user: "why does it think it has gloom? that was a
different run"): the kept plan leg_14_a_party_pokemon_knows_cut.v1 said
"Teach the move CUT to Gloom using HM01 from the bag" — Gloom belonged to
the Hall of Fame world, whose leg plans a fresh chain keeps as banked
luck. The run opened every PC in Vermilion hunting it. The party and the
boxes are both in the observation; the note states the fact, points out
that the step's own condition usually names no species, and leaves the
choice (skip, or satisfy it another way) to the model.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
ex = E.Executor.__new__(E.Executor); ex.log = lambda *a, **k: None
SG = {"id": "teach_cut_to_gloom",
      "goal_text": "Teach the move CUT to Gloom using HM01 from the bag",
      "done_when": {"knows_move": {"move": "CUT", "slot": 1}}}
ck("the species list comes from the game's own data",
   len(E.Executor._species_names()) == 151 and "GLOOM" in E.Executor._species_names())
n = ex._absent_species_note({"party": [{"species": "RATICATE"}], "pc_mons": []}, SG)
ck("a named Pokemon absent from party and boxes is said, with what it means",
   "THIS STEP NAMES A POKEMON YOU DO NOT HAVE: GLOOM" in n
   and "not in any PC box this run has looked in" in n, n)
ck("...and that the step's own condition does not name it",
   "Its own condition does not name it" in n and '"knows_move"' in n, n)
ck("...offering skip or another way, never a hunt",
   '{"op":"skip"}' in n and "hunting for it is not one of them" in n, n)
ck("in the party: nothing said", ex._absent_species_note({"party": [{"species": "GLOOM"}]}, SG) == "")
ck("in a box: nothing said",
   ex._absent_species_note({"party": [], "pc_mons": [{"species": "GLOOM"}]}, SG) == "")
SG2 = dict(SG, done_when={"has_species": "GLOOM"})
n2 = ex._absent_species_note({"party": [{"species": "RATICATE"}]}, SG2)
ck("a condition that names it too is said to be unmeetable as written",
   "Its own condition names it too" in n2, n2)
ck("a step naming no species says nothing",
   ex._absent_species_note({"party": []}, {"id": "go_north", "goal_text": "Walk north to Route 4"}) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("the note rides the round-1 page beside the reset-flag note",
   "memory += self._absent_species_note(start, sg)" in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
