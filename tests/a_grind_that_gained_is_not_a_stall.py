#!/usr/bin/env python3
"""A subgoal that ran out of rounds having WON battles reports progress, not
a failure.

A level curve fails by budget, over and over, for as long as the curve
takes: train_gyarados fought 109 wild battles, took Gyarados from 22 to 33,
and every attempt was reported "gave up without reaching its done_when" —
the same words as a step standing at a locked door (2026-09-09; user asked
for the discriminator). A step whose own battles were won moved the world
the way it was asked to. The third failure still trips the stalemate alarm,
so a grind that really is going nowhere stays loud.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
nb = (ROOT / "planner" / "notable.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ck("battles won inside a subgoal are counted", 'if k == "battle_done" and str(r.get("mode") or "") == "overworld":' in nb and 'self.won = int(getattr(self, "won", 0) or 0) + 1' in nb)
ck("...and the count resets when a subgoal begins", 'self.won = 0                 # battles won inside THIS subgoal' in nb)
ck("a failure with wins reports progress at info", '"info", "subgoal_progress"' in nb and "it is closer, not stuck" in nb)
ck("...naming how many it won", 'having won {_won} ' in nb)
ck("a failure with no wins is still a warning", '"warn", "subgoal_failed"' in nb and "gave up without reaching its done_when" in nb)
i = nb.index("A LEVEL CURVE IS NOT A STALL")
ck("the stalemate alarm is untouched, and still comes first",
   nb.index("STALEMATE_TRIP") < i and 'self.once(f"stale:{sub}"' in nb)
ck("the reason is written where the next reader will look", "109 wild" in nb)
sys.exit(1 if fails else 0)
