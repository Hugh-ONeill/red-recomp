#!/usr/bin/env python3
"""A condition the game can never report is rejected where it is written.

`mode` was the one predicate whose values were freeform. Every other
vocabulary in author.py is enumerated and spell-checked — map ids, flags,
items, moves, species, types — while the mode description said only
'obs mode equals VALUE (usually "overworld")' and named none of them.

So run 10, given the objective "Access the PC for the first time", wrote

    use_pc: done_when={"mode": "pc"}

which is the obvious guess and is not one of the five modes the shim can
emit. The plan validated. It ran four attempts. Every rung of the ladder
was spent on it: check-done said NOT_DONE, check-wording said "the
wording stands", check-later said "stays where it is". Then

    === chain stopped at leg 3/47: Access the PC for the first time ===

and the run was over. The galling part is that it HAD opened the PC —
the trace carries the machine's own reply, "What? There are no POKéMON
here!" — so the deed was done and no predicate on offer could say so.

A condition that can never be true is the most expensive kind of typo,
and rejecting it at authoring time is the same treatment every other
vocabulary already gets: the model is told, and re-authors.

THE MODE LIST IS READ OUT OF THE SHIM, not copied here, so the two cannot
drift apart. That is also what the last case below checks.

Synthetic only: no game, no model, no chain.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import author as A                                     # noqa: E402


def probs_for(dw):
    out = []
    A._check_pred_shapes(dw, "subgoal", "use_pc", out)
    return out


CASES = [
    ("the mode that stopped run 10 is refused", {"mode": "pc"}, True),
    ("...and so is any other screen somebody might reach for",
     {"mode": "shop"}, True),
    ("...and a plausible-looking one",
     {"mode": "menu"}, True),
    ("every mode the shim really emits is accepted: overworld",
     {"mode": "overworld"}, False),
    ("...battle", {"mode": "battle"}, False),
    ("...dialog", {"mode": "dialog"}, False),
    ("...ui, which is what a PC actually reports",
     {"mode": "ui"}, False),
    ("...boot", {"mode": "boot"}, False),

    # the shapes this validator already caught, so the new branch has not
    # eaten any of them on its way in
    ("a string where a bool belongs is still refused",
     {"party_nonempty": "true"}, True),
    ("a string where an int belongs is still refused",
     {"party_size": "2"}, True),
    ("a good int is still fine", {"party_size": 2}, False),
]


def main():
    fails = []
    for name, dw, want_problem in CASES:
        got = probs_for(dw)
        ok = bool(got) is want_problem
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          {dw} -> {got or 'accepted'}")
            fails.append(name)

    # THE MESSAGE HAS TO NAME THE FIVE. Being told "no" without being told
    # what yes looks like is how the model burns its rewrites guessing, and
    # this whole class exists because nothing published the list.
    msg = " ".join(probs_for({"mode": "pc"}))
    named = all(m in msg for m in A.OBS_MODES)
    print(f"  {'ok  ' if named else 'FAIL'}  the refusal names every mode "
          f"that does exist")
    if not named:
        print(f"          {msg}")
        fails.append("names the modes")

    # ...AND THE LIST COMES FROM THE SHIM. A copy here would drift the
    # moment a mode is added, and drift is what put "pc" in a plan.
    src = (ROOT / "harness" / "shim.lua").read_text()
    live = tuple(dict.fromkeys(re.findall(r'o\.mode = "([a-z]+)"', src)))
    ok = set(live) == set(A.OBS_MODES) and len(live) > 0
    print(f"  {'ok  ' if ok else 'FAIL'}  the vocabulary is read from the "
          f"shim, not copied ({len(live)} modes)")
    if not ok:
        print(f"          shim says {live}, author says {A.OBS_MODES}")
        fails.append("vocabulary source")

    # and the model must be TOLD, not only corrected afterwards
    told = all(m in A.PREDICATES["mode"] for m in A.OBS_MODES)
    print(f"  {'ok  ' if told else 'FAIL'}  ...and published in the "
          f"predicate list the author is shown")
    if not told:
        fails.append("published")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"AN UNSATISFIABLE CONDITION CAN STILL BE WRITTEN: "
              f"{len(fails)} case(s)")
        return 1
    print(f"a condition the game can never report is refused where it is "
          f"written ({len(CASES) + 3} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
