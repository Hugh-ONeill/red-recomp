#!/usr/bin/env python3
"""A fixture whose answers have varied is answering presses, not giving
hints, and its line leaves the hints ledger.

Vermilion Gym, run 17 (2026-09-14): the hints ledger listed "TRASH_CAN_14:
Hey! There's a switch under the trash! ... The 1st electric lock opened!"
at the top of every gym page under the can's own name, caveat appended,
and the run held "14 opens the 1st lock" through five plan starts while
four different cans opened it once each. A sign says one thing for ever
and stays. A person who has said two things stays, with the caveat, since
a person's second line is often the one that matters. A can, a switch, a
machine whose reply has moved has no line worth keeping under its name:
its rows and the room's ordered log hold the whole history.

The outcome book now keeps each pressed thing's kind as the screen lists
it, so the ledger can tell a can from a person without a name rule.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "VERMILION_GYM|4,5"
SWITCH = "Hey! There's a switch under the trash! Turn it on! The 1st electric lock opened!"
TRASH = "Nope, there's only trash here."
HINT = "LT.SURGE set up double locks! Here's a hint! When you open the 1st lock, the 2nd lock is right next to it!"
THANKS = "Thanks for the battle!"
SIGN = "VERMILION CITY GYM LEADER: LT.SURGE The Lightning American!"

def ex(books):
    o = types.SimpleNamespace(_outcomes=books)
    for m in ("_said_variously", "_thing_kind", "_hint_stands"):
        setattr(o, m, types.MethodType(getattr(E.Executor, m), o))
    return o

BOOKS = {
    f"badge:THUNDERBADGE|{HERE}": {
        "TRASH_CAN_14": {"kind": "fixture", "said": {TRASH: 12, SWITCH: 1}},
        "TRASH_CAN_0": {"kind": "fixture", "said": {TRASH: 3}},
        "TEXT_VERMILIONGYM_SIGN": {"kind": "fixture", "said": {SIGN: 2}},
        "VERMILIONGYM_SAILOR": {"kind": "person", "said": {HINT: 1, THANKS: 2}},
        "OLD_CAN": {"said": {TRASH: 2, SWITCH: 1}},
    },
    f"map:VERMILION_CITY|{HERE}": {"TRASH_CAN_14": {"said": {"reset": 1}}},
    f"badge:THUNDERBADGE|CERULEAN_GYM|0,1": {"TRASH_CAN_14": {"kind": "person"}},
}
X = ex(BOOKS)

# the kind is read from the record, for this region only
ck("a thing's kind is read from its record in this region",
   X._thing_kind(HERE, "TRASH_CAN_14") == "fixture" and X._thing_kind(HERE, "VERMILIONGYM_SAILOR") == "person")
ck("...not from another region's record", X._thing_kind("CERULEAN_GYM|0,1", "TRASH_CAN_14") == "person"
   and X._thing_kind(HERE, "TRASH_CAN_0") == "fixture")
ck("...and is empty when no record carries one", X._thing_kind(HERE, "OLD_CAN") == "" and X._thing_kind(HERE, "") == "")

# what stands and what does not
ck("a can whose answers have varied is not a hint", not X._hint_stands(HERE, f"TRASH_CAN_14: {SWITCH}"))
ck("...whatever it was quoted saying", not X._hint_stands(HERE, f"TRASH_CAN_14: {TRASH}"))
ck("a can that has only ever said one thing stands", X._hint_stands(HERE, f"TRASH_CAN_0: {TRASH}"))
ck("a sign stands", X._hint_stands(HERE, f"TEXT_VERMILIONGYM_SIGN: {SIGN}"))
ck("a person who has said two things stands (the caveat is theirs)", X._hint_stands(HERE, f"VERMILIONGYM_SAILOR: {HINT}"))
ck("a thing of unknown kind stands, however it has varied", X._hint_stands(HERE, f"OLD_CAN: {SWITCH}"))
ck("a line with no speaker stands", X._hint_stands(HERE, "sweep: something seen"))
ck("a speaker with no record stands", X._hint_stands(HERE, f"NOBODY: {SWITCH}"))

# the screen's word for the kind is what gets kept
OBS = {"map": {"objects": [{"name": "TRASH_CAN_14", "kind": "fixture", "x": 9, "y": 11},
                           {"name": "VERMILIONGYM_SAILOR", "kind": "person"}, "junk"]}}
ck("the kind comes off the map's object list by name",
   E.Executor._kind_on_map(OBS, "TRASH_CAN_14") == "fixture" and E.Executor._kind_on_map(OBS, "VERMILIONGYM_SAILOR") == "person")
ck("...and is empty for a name not on it", E.Executor._kind_on_map(OBS, "TRASH_CAN_3") == "" and E.Executor._kind_on_map({}, "X") == "")

# both hint sites go through the gate, and the recorder keeps the kind
src = (ROOT / "planner" / "executor.py").read_text()
ck("this room's hints are filtered through the gate",
   "said_here = [l for l in (self.hints.get(here) or [])\n                     if self._hint_stands(here, l)]" in src)
ck("...and so are the hints from elsewhere",
   "_stand = [l for l in _lines if self._hint_stands(_rg, l)]" in src
   and "said_away.append((len(_p), _rg, _stand))" in src)
ck("the recorder keeps the kind with the record",
   '_kd = self._kind_on_map(pre_obs, key)' in src and 'rec["kind"] = _kd' in src)
i = src.index("def _hint_stands")
ck("nothing here names the rule or which can to press",
   not any(w in src[i:i + 2500].lower() for w in ("adjacent", "next to it", "random", "re-roll")))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
