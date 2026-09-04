#!/usr/bin/env python3
"""The round that finds new ground is not the last (2026-09-04).

buy_fresh_water, round 12 of 12 (rounds*3, the hard cap): "explore" took the
untried 5F stairs onto CELADON_MART_ROOF, the first time the run stood there,
with the machines holding FRESH WATER a few cells away — and the cap ended the
step on that round. The plan backtracked to "exit the store" and the run
walked down past them. A round that lands the party on ground it has never
stood on, when the cap would otherwise end the step, moves the cap out by one;
twice per step at most. What to do with the round stays the model's.

Source-shape test: the loop is the escalation itself and is not run here."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

ck("the cap admits the bonus", "while spent < rounds and rnd < rounds * 3 + _fresh_bonus:" in src)
ck("the bonus starts at zero per step", "_fresh_bonus = 0      # rounds the cap moves out" in src)
ck("it is earned only on a first-ever region, only at the cap, at most twice",
   "if (visits[sig1[0]] == 1 and _fresh_bonus < 2\n                        and rnd >= rounds * 3 + _fresh_bonus\n"
   "                        and (getattr(self, \"visits\", {}) or {})\n                        .get(here_now, 0) <= 1):" in src)
ck("...and is written down, in the journal and to the model",
   'self.log("round_for_new_ground", subgoal=sg["id"],' in src
   and "this step gets one more round \"\n                        f\"for it)" in src)
ck("a first visit is still not charged as circling",
   "if visits[sig1[0]] >= 2:\n                    spent += 1   # back on a map already visited: circling" in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok   " if ok else "FAIL ") + n)
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
