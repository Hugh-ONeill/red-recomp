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
    ("...ui, which is what a PC actually reports",
     {"mode": "ui"}, False),

    # A REAL MODE THAT IS NEVER TRUE WHEN IT IS TESTED. done_when is
    # evaluated against a SETTLED observation and settle() rides plain text
    # to the next decision, so the box has always closed by then. The run
    # spoke to the Viridian old man and sat through the entire catch
    # tutorial, over and over, with {"mode":"dialog"} never once holding.
    ("dialog is a real mode and still refused as a condition",
     {"mode": "dialog"}, True),
    ("...boot", {"mode": "boot"}, False),

    # THE PREDICATE THAT MAKES "pc" UNNECESSARY. `mode` can only say that
    # SOME menu is open; `screen` names which one, off the label the shim
    # has always passed through as ui.screenId and nothing could test.
    ("the PC's Pokemon storage is nameable", {"screen": "BoxMenu"}, False),
    ("...and its item storage", {"screen": "PlayerPC"}, False),
    ("...and the shop counter", {"screen": "ShopMenu"}, False),
    ("a screen the engine never pushes is refused",
     {"screen": "PC"}, True),
    ("...including the one the old mode guess meant",
     {"screen": "pc"}, True),

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

    # THE REFUSAL MUST CARRY ITS REASON. "dialog is not allowed" invites
    # the model to try "ui" next and lose another leg; the reason is what
    # sends it to a flag instead.
    msg = " ".join(probs_for({"mode": "dialog"}))
    ok = "settle" in msg and ("flag" in msg or "CHANGED" in msg)
    print(f"  {'ok  ' if ok else 'FAIL'}  ...and says WHY dialog can never "
          f"hold, and what to use instead")
    if not ok:
        print(f"          {msg}")
        fails.append("dialog reason")

    # the note must warn about BOTH halves: screens and people
    note = A.PREDICATES["mode"]
    ok = "naming box" in note and "dialog" in note
    print(f"  {'ok  ' if ok else 'FAIL'}  the published note covers screens "
          f"AND people, not just screens")
    if not ok:
        fails.append("half-written note")

    # and the model must be TOLD, not only corrected afterwards
    told = all(m in A.PREDICATES["mode"] for m in A.OBS_MODES)
    print(f"  {'ok  ' if told else 'FAIL'}  ...and published in the "
          f"predicate list the author is shown")
    if not told:
        fails.append("published")

    # THE SCREEN VOCABULARY, same three properties: read from the engine,
    # published, and a real key rather than a string the loop ignores.
    eng = ""
    root = Path.home() / "Developer" / "gen1recomp" / "src"
    if root.is_dir():
        for p in root.rglob("*.lua"):
            eng += p.read_text(errors="ignore")
    live = set(re.findall(r'Screens\.push\(\s*\w+\s*,\s*"([A-Za-z]+)"', eng))
    ok = bool(live) and live == set(A.UI_SCREENS)
    print(f"  {'ok  ' if ok else 'FAIL'}  the screen list is read from the "
          f"engine, not copied ({len(live)} screens)")
    if not ok:
        print(f"          engine {sorted(live)}")
        print(f"          author {sorted(A.UI_SCREENS)}")
        fails.append("screen source")

    ok = ("screen" in A.VALID_KEYS
          and all(s in A.PREDICATES["screen"] for s in A.UI_SCREENS))
    print(f"  {'ok  ' if ok else 'FAIL'}  ...and screen is a real predicate "
          f"key with its values published")
    if not ok:
        fails.append("screen published")

    # BoxMenu must be reachable as a predicate for the storage work to be
    # writable at all — this is the whole point of the exercise
    ok = "BoxMenu" in A.UI_SCREENS and "PlayerPC" in A.UI_SCREENS
    print(f"  {'ok  ' if ok else 'FAIL'}  both halves of the PC are "
          f"nameable (BoxMenu, PlayerPC)")
    if not ok:
        fails.append("pc screens")

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
