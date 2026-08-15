#!/usr/bin/env python3
"""Find the plan authored for an objective — by the objective, not by slot.

A PLAN BELONGS TO AN OBJECTIVE, NOT TO A POSITION. Plans were named
leg_NN.json for the outline position they were written at, so any
rearrangement of the list left every plan from the shift onward pointing
at the wrong objective — and the rungs "fixed" that by deleting them.
One pull-forward took all eleven leg_11 rewrites with it.

But pulling a leg ahead only says THAT ONE was misordered against the
others (user, 2026-08-15). The rest kept their order, their work and
their evidence, and a pull is exactly the move that would have been right
for "Retrieve the Silph Scope from Team Rocket" had the sweep not already
crossed it off. Losing their plans was pure damage.

So the position in the filename is now only where a plan was first
written, and every leg finds its own by asking. Nothing is invalidated by
a reorder, because nothing was ever addressed by position. A REWORDED
objective simply matches nothing and is authored fresh, which is right:
that leg really is a different one now.

Prints the highest-versioned matching plan and exits 0, or exits 3.
Usage: find_plan.py "<objective>"
"""
import json
import re
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
want = sys.argv[1].strip()
# the chain appends the outline's own recorded doubt to the goal it hands
# the author; the plan stores the bare objective, so compare bare
want = re.sub(r"\s*\(a doubt you recorded when outlining:.*$", "", want)


def version(p: Path) -> int:
    m = re.search(r"\.v(\d+)\.json$", p.name)
    return int(m.group(1)) if m else 0


best = None
for p in sorted(Path("plans").glob("leg_*.json")):
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        continue
    if not isinstance(d, dict) or not d.get("subgoals"):
        continue
    if str(d.get("goal") or "").strip() != want:
        continue
    if best is None or version(p) > version(best):
        best = p

if best is None:
    sys.exit(3)
print(best)
