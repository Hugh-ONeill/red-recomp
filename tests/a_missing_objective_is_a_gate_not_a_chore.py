#!/usr/bin/env python3
"""The missing rung inserts LEGS, and it was handed a step.

It is asked to name a deed "the game will not let you past until it is
done", and it was never told that the answer has to be leg-sized.  So it
answered "revive all fainted party members" and the outline gained a whole
objective, with its own plan and its own attempts, for walking into a
Pokemon Center -- something the leg it was blocking already does, as the
first subgoal of its own plan (user, 2026-09-11: "its weird to have an
entire leg for just going to the pokecenter thats more of an escalation
within an already established goal sorta thing").

The distinction is the game's, not ours: a gate is a thing the game
REFUSES until some other deed is done, and a chore is a thing the stuck
leg could simply do.  Which side a given deed falls on stays the model's
read; what is added is the question.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

import re                                              # noqa: E402
S = A.CHECKMISSING_SYS
# the prompt is a wrapped triple-quoted string, so a sentence can break
# across a newline while reading as one line to the model
FLAT = re.sub(r"\s+", " ", S)

ck("the rung still asks for one missing objective or none",
   "Name ONE missing objective, or none" in S)
ck("...still refusing what is on the docket already",
   "Do NOT restate something already on the docket" in S)
ck("...and what the events show is done",
   "recorded events show is already done" in S)

ck("a gate is distinguished from a chore",
   "A MISSING OBJECTIVE IS A GATE, NOT A CHORE" in S)
ck("...by asking whether the stuck leg could just do it",
   "could simply DO the thing as one of its own steps" in S)
ck("...naming the ordinary steps it means",
   all(w in S for w in ("heal", "buy an item", "teach a move")))
ck("...and what a gate looks like instead",
   "a badge it checks at a gate" in S and "barrier that opens on a flag" in S)
ck("both sides get a worked example",
   "Revive the fainted party members" in S and "Obtain the SILPH SCOPE" in S)
ck("...the chore one drawn from what actually happened",
   "the grind leg already heals" in FLAT)
_tail = S.split("A MISSING OBJECTIVE IS A GATE, NOT A CHORE", 1)[1]
ck("it does not decide for the model",
   "you must" not in _tail.lower() and "always" not in _tail.lower())

# the reply shape is untouched
ck("the reply is still one JSON object, reason first",
   '{"why": "one sentence", "insert": "the objective"}' in S
   and '"insert": null' in S)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
