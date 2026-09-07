#!/usr/bin/env python3
"""A missing step is something the game said or did, not something typical.

Run 16, leg 14 (2026-09-07): the run wandered the S.S. Anne for an attempt
without finding the captain's cabin (it never walked 2F past the stairs),
and the missing rung answered "Defeat all trainers on the S.S. Anne" with
the reason "... they have not yet defeated the ship's trainers, which is
typical". Nobody on the ship said so; nothing turned the run back. The
chain inserted the leg. A prerequisite reasoned from what is usual in games
is the same class as a done verdict reasoned from another fact
(a_leg_inferred_done_is_not_done): the reason must point at something the
game said or did, or the answer is none.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
src = (ROOT / "planner" / "author.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

ck("'which is typical' is an inference",
   A._inferred("they have not yet defeated the ship's trainers, which is typical"))
ck("'usually' / 'in most games' are inferences",
   A._inferred("the captain usually needs all trainers beaten")
   and A._inferred("in most Pokemon games the gym opens after the event"))
ck("a reason that quotes the game is not",
   not A._inferred("the sailor said the captain is seasick and cannot be seen")
   and not A._inferred("the gym door turned the run back: the tree blocks it"))
i = src.find("def check_missing(")
j = src.find("\nWORDING_SYS = ", i)
body = src[i:j]
ck("check_missing turns an inferred reason down and quotes it back",
   "if _inferred(_why):" in body and "your reason infers it" in body)
ck("...before asking whether the deed is already done",
   body.find("if _inferred(_why):") < body.find("if check_already_done(ins, start, model"))
ck("...and the turned-down list is re-asked, not re-rolled",
   "YOU ALREADY PROPOSED THESE AND THEY WERE TURNED" in body)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
