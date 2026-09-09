#!/usr/bin/env python3
"""A floor whose shut way once asked for something the bag now holds says so
from anywhere, not only when you are standing on it.

Silph 3F's two-tile shutter at (17,8) holds 83 cells of that floor. The
LOCAL page says the useful thing outright: pressed when you held no
CARD_KEY, you hold it now, the same press is a different press. From any
other floor the same door read only "a way never taken, blocked by nobody",
which is scenery. The run carried the Card Key for an hour, worked 5F, 7F
and the lift, and began exactly ONE round standing on 3F in all that time
(2026-09-09; user: "the thing it needs to do now is take care of the
shutters on 3F"). The note names no route and no destination: which floor
holds a lock, and that its key is already in the bag.
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


class _E(Executor):
    def __init__(self, hints):
        self.hints = hints


HINTS = {"SILPH_CO_3F|20,0": [
    "DOOR_SILPH_CO_3F_17_8: Darn! It needs a CARD KEY!",
    "SILPHCO3F_ROCKET: A hint? You can open doors with a CARD KEY!"]}
e = _E(HINTS)
note = e._shut_asked_for_held("SILPH_CO_3F|20,0", {"bag": {"CARD_KEY": 1, "LIFT_KEY": 1}})
ck("the note fires when the bag holds what the door asked for", "CARD_KEY" in note and "holds NOW" in note)
ck("...and says the press has changed meaning", "a different press than the one the record remembers" in note)
ck("...without naming a route, a destination or a cell", not any(w in note for w in ("17,8", "SILPH", "11F", "7F", "go ", "walk")))
ck("it says nothing while the bag lacks the item", e._shut_asked_for_held("SILPH_CO_3F|20,0", {"bag": {"LIFT_KEY": 1}}) == "")
ck("...and nothing for a floor that said nothing", e._shut_asked_for_held("SILPH_CO_9F|14,0", {"bag": {"CARD_KEY": 1}}) == "")
ck("...and nothing with an empty bag", e._shut_asked_for_held("SILPH_CO_3F|20,0", {"bag": {}}) == "")
ck("a zero count is not holding it", e._shut_asked_for_held("SILPH_CO_3F|20,0", {"bag": {"CARD_KEY": 0}}) == "")
ck("both remote lines carry it, routed and unrouted",
   ex.count("+ self._shut_asked_for_held(region, obs)))") == 2)
ck("the reason is written where the next reader will look", "A shut way THERE once asked for a thing the bag holds NOW." in ex)
sys.exit(1 if fails else 0)
