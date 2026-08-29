#!/usr/bin/env python3
"""A flag guess that is a placeholder in a series the plan itself named
gets the members of that series, and nothing else.

Leg 13, 2026-08-29: "Clear Route 4 of trainers" was authored five rounds
running with done_when flag EVENT_BEAT_ROUTE_4_TRAINER_N — a literal N —
and the refusal only ever said the name was wrong, so the leg could not be
written at all and the chain stopped for a person. Suggesting flags in
general is deliberately refused (fired ones are rejected by the next rule
by construction, and whole-list matching once handed over the Marowak
ghost's identity). This is narrower: the series is the model's own words,
and how many trainers a route holds is on the screen.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
def probs_for(flag):
    return A.validate({"goal": "g", "subgoals": [
        {"id": "a", "goal_text": "t", "done_when": {"flag": flag}}]})
p = " ".join(probs_for("EVENT_BEAT_ROUTE_4_TRAINER_N"))
ck("the series the plan named is spelled out, as a did-you-mean the retry prompt obeys",
   "EVENT_BEAT_ROUTE_4_TRAINER_0" in p and "Did you mean" in p
   and "use that exact id verbatim" in p, p[:260])
ck("...and a one-member series says so, which answers 'all of them'",
   "the ONLY event of that series" in p, p[:260])
ck("...and the refusal still stands on its own terms",
   "is not an event this game defines" in p and "do not spell a different one" in p
   and "Finish this subgoal on something you can SEE" in p)
q = " ".join(probs_for("EVENT_TOWER_GHOSTS_GONE"))
ck("a made-up name in no series gets no suggestion at all",
   "does define are" not in q and "is not an event this game defines" in q, q[:200])
ck("a real flag is not refused", not probs_for(sorted(A.ENGINE_FLAGS)[0]))
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)
