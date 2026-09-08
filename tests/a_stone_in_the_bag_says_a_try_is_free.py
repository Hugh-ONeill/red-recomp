#!/usr/bin/env python3
"""An evolution stone in the bag says how it is used and that a wrong try
costs nothing.

Run 16 (2026-09-08): NIDORINA, GLOOM and EEVEE — three party members that
evolve by stone — rode along with two MOON STONEs for a day while the run
fished for a Surf learner; user: "three pokemon who evolve using stones that
its just not taking advantage of". The knows-move page said a stone evolves
"a Pokemon it suits" and left the cost of finding out unsaid. The game's own
answer to a wrong try is "It won't have any effect" with the stone kept, so
trying is free — a mechanic, not a species fact. The bag line carries it on
every stone, and the knows-move page says the stones can be tried on every
member for free. WHICH Pokemon a stone suits stays the model's.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
from executor import Executor                                  # noqa: E402

ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


note = Executor._stone_note("MOON_STONE")
ck("a stone gets a note", note != "" and "evolution stone" in note)
ck("...that names the op and the slot", '{"op":"use_item","item":"MOON_STONE","slot":N}' in note)
ck("...that says a wrong try is free, in the game's words", "It won't have any effect" in note and "a try costs nothing" in note)
ck("...and that an evolved form can take machines its earlier form could not", "an evolved form can take machines" in note)
ck("...without naming any species", not any(w in note for w in ("NIDORINA", "NIDOQUEEN", "EEVEE", "VAPOREON", "GLOOM", "VILEPLUME")))
ck("a non-stone gets nothing", Executor._stone_note("POTION") == "" and Executor._stone_note("HM_SURF") == "")
ck("the bag line carries it", "{self._rod_note(k)}{self._stone_note(k)}" in ex)
ck("the knows-move page says the stones can be tried for free", "stones in your bag can be tried on every member for free" in ex)
sys.exit(1 if fails else 0)
