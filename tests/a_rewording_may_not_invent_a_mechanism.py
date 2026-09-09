#!/usr/bin/env python3
"""The wording rung may say WHAT an objective wants, not HOW it is got.

Run 16, 2026-09-08: "Retrieve the Card Key inside Silph Co." was rewritten
to "Obtain the Card Key from the Team Rocket executive inside Silph Co.",
justified as "obtained from the Team Rocket executive on the 3rd floor after
defeating him". In this game the Card Key is a Poke Ball on the floor of 5F
at (21,16) — object SILPHCO5F_CARD_KEY — and the run had already seen it
("ITEM_SILPH_CO_5F_21_16 (item) at (21,16), across ground no walk from here
reaches"). The invented mechanism sent two attempts hunting a person, and
the rewrite that followed added a climb to 11F. A vague line would have been
better than a wrong one, so the rung is now told it may name a thing, a
place or a person the run has MET, and may not add who hands a thing over
or what must be beaten first unless the evidence shows it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


w = A.WORDING_SYS
ck("the rung is told to say what is wanted, not how it is got", "SAY WHAT IS WANTED, NOT HOW IT IS GOT." in w)
ck("...naming the mechanisms it may not invent", "who hands the thing over, which floor holds them, what must\nbe beaten first" in w)
ck("...unless the run's own evidence shows it", "unless the evidence below shows it" in w)
ck("...with the case that taught it", "Card Key" in w and "2026-09-08" in w)
ck("...and the rule that a vague line beats a wrong one", "If you know only WHAT is wanted, say\nonly that." in w)
ck("the rung can still reword, void or stand", '"reword": "the objective, said accurately"' in w and '"void": true' in w)
sys.exit(1 if fails else 0)
