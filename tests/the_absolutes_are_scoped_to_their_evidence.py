#!/usr/bin/env python3
"""Absolutes the harness states are scoped to their evidence (audit,
2026-08-28). The over-claim meter found the model quotes "unreachable /
not here / fully worked" back before 80% of its stalls; the one verdict
wider than a sweep of reached-and-seen ground was the executor's "PROVEN:
what this goal needs is NOT in {here}", said while listing exits never
taken. This pins the scoped wording and guards the ledger proofs that the
2026-08-19 day already narrowed.
"""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

ex = (ROOT / "planner" / "executor.py").read_text()
ck("the goal-absent absolute no longer says PROVEN ... NOT in the area",
   "PROVEN: what this goal needs is NOT in" not in ex)
ck("...it is scoped to the ground reached and seen",
   "not on the ground you" in ex and "reached and seen in" in ex)
ck("...and says an untried exit is not proof",
   "not proof about what" in ex and "lies past an exit you have not walked" in ex)
ck("...while still naming the untried ways to take",
   "way(s) out of here have never been taken" in ex)

led = (ROOT / "planner" / "ledger.py").read_text()
ck("a seam proof stays scoped to THIS part, as of now",
   "proven uncrossable from THIS part of the" in led and "as things stand" in led)
ck("a spent exit is a true try-count, not a contents claim",
   "reached for and never once got through" in led)
ck("an inert fixture reports the press count, not a verdict",
   'pressed {n}x; nothing changed' in led)
ck("the finished-here head names the unreached ways or the stuck parts",
   "EVERYTHING YOU CAN REACH HERE IS DONE, but" in led
   and "sits where no walk from here goes" in led)

oc = (ROOT / "planner" / "overclaim.py").read_text()
ck("the meter no longer calls 'progressed after finished-here' a contradiction",
   "PROGRESSED\\n         (no escalate_end) — the room said done" not in oc
   and "leaving by a listed exit is the verdict" in oc)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
