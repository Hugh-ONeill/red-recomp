#!/usr/bin/env python3
"""A leg the judge will not confirm after two plans is moved later, not
counted done.

Run 16 (2026-09-08): the drink for Saffron's guards was crossed off with no
drink bought — a reused plan ending on lacks_item FRESH_WATER read "met",
the judge refused ("never once stood on SAFFRON_CITY"), and the chain's rule
for a second unconfirmed plan was to count the leg and move on. The run
reached Silph Co's leg unable to enter the city. Now such a leg is pushed
two places later on a fresh plan, where the judge looks again; counting is
the fallback only when there is no later to move it to. Lands at the next
chain launch (a running bash script keeps the file it opened).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "fresh_discovery.sh").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("AN UNCONFIRMED LEG IS MOVED, NOT COUNTED")
blk = sh[i:i + 2200]
ck("an unconfirmed leg is pushed two places later", 'python planner/push_leg.py "$i" "$_after"' in blk and '_after=$((i + 2))' in blk)
ck("...on a fresh plan, with the round not counted", 'archive_plans_of "$leg"' in blk and "continue" in blk and blk.index("continue") < blk.index('echo "$i" > "$PROGRESS"'))
ck("...and is still listed among the unconfirmed", "printf '%s\\n' \"$leg\" >> run/leg_unconfirmed" in blk)
ck("counting is only the fallback with nowhere later to go", "nowhere later to move it" in blk and '[ "$_after" -lt "${#LEGS[@]}" ]' in blk)
ck("the old unconditional count is gone", '"counting it and moving on)"\n      # the legs the run walked past' not in sh)
sys.exit(1 if fails else 0)
