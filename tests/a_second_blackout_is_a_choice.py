#!/usr/bin/env python3
"""The first wipe happened to you. The sixth one you chose.

Run 17, leg 5 (2026-09-13). "Catch a NIDORAN on Route 22" spent six
identical rounds on {"op":"explore"}, and every one of them walked north
into the rival — a Squirtle against an under-levelled Charmander, with a
Pidgey behind it — and blacked the party out to Pallet Town. Six rounds,
six wipes, and the step's budget never moved, because a blackout was
pardoned: it did not spend a round and it did not count toward staleness.
So nothing escalated, nothing went stale, no rung was reached, and the
plan opened "I will first explore the remaining unseen ground" every time
(user: "its trying to explore instead of catching in the patch of grass it
can see, leading it to fight the rival and inevitably lose each time").

The pardon's reasoning was sound and stays for the FIRST one: a blackout's
map-jump was not chosen, and the walk back to where the party fainted is
not circling. It is the repeat that is a decision, and from the second on
the round is spent like any other.

And the record is put where the next round can read it. A wipe was
reported once, in the trace of the round it happened in, and by the next
page it was gone.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SRC = (ROOT / "planner" / "executor.py").read_text()


class Budget:
    """The two counters as run_plan keeps them, and nothing else."""
    def __init__(self):
        self.spent = 0
        self.stale = 0
        self.wipes = 0
        self.pardon = False

    def round(self, blackout=False, news=False, exempt=False):
        if blackout:
            self.wipes += 1
        n = self.wipes
        if news:
            pass                                   # the news bonus, untouched
        elif (blackout or self.pardon) and n <= 1:
            self.pardon = blackout
        else:
            self.spent += 1
        _ex = exempt or (blackout and n <= 1)
        if _ex:
            return
        self.stale += 1


# ---- the run 17 loop, as it ran ----------------------------------------
b = Budget()
for _ in range(6):
    b.round(blackout=True)
ck("six wipes no longer cost nothing", b.spent >= 4)
ck("...and the stale counter sees them too", b.stale >= 4)

# ---- but the first is still free ---------------------------------------
b2 = Budget()
b2.round(blackout=True)
ck("one wipe is something that happened to you, not a spent round",
   b2.spent == 0 and b2.stale == 0)
b2.round(blackout=True)
ck("...the second is a decision, and costs", b2.spent == 1)

# ---- and the walk back after the first is still pardoned ---------------
b3 = Budget()
b3.round(blackout=True)          # wiped
b3.round()                       # the walk back to where it fainted
ck("the round after the first wipe is still free", b3.spent == 0)

# ---- an ordinary round is untouched ------------------------------------
b4 = Budget()
for _ in range(3):
    b4.round()
ck("a round with no wipe still spends", b4.spent == 3)
b5 = Budget()
b5.round(news=True)
ck("a round that found something still costs nothing", b5.spent == 0)

# ---- the code says all of this -----------------------------------------
ck("the pardon is gated on how many wipes this step has taken",
   "elif (had_blackout or pardon) and _bo_n <= 1:" in SRC)
ck("...and so is the stale exemption",
   "or _switches or (had_blackout and _bo_n <= 1)" in SRC)
ck("the count is per STEP, reset with the other per-step budgets",
   "self._bo_here = 0         # wipes this subgoal has taken" in SRC)
ck("...and the macro that caused each one is kept",
   "self._bo_ops = (getattr(self, \"_bo_ops\", [])" in SRC)
ck("...and written to the journal", 'self.log("blackout_round"' in SRC)

# ---- and the page carries it, not just the round it happened in --------
ck("the page says how many times this step has wiped",
   "THIS STEP HAS BLACKED OUT" in SRC)
ck("...what a blackout actually costs", "HALF YOUR MONEY GONE" in SRC)
ck("...and which macro did it last", "followed this macro:" in SRC)
ck("...and after the first, that repeating it is the same walk",
   "the same walk into " in SRC and "has to \"\n                       \"change"
   in SRC or "Something about the plan has to" in SRC)
ck("...while a single wipe only says what is still there",
   "What beat you is still there." in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
