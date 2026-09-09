#!/usr/bin/env python3
"""use_warp at a doorway no walk reaches rides a way in the run has used
before, exactly as a press at an unreachable item does.

The pad recross had three ways in — a walk_to that found no path, a press by
name, a press by coordinates — and none for the op a model actually sends at
a pad it can SEE and cannot walk to. Silph 7F's unused pads sit in a band the
run cannot reach on foot, so use_warp was refused for want of a path and the
machinery that had just won the Card Key never ran (2026-09-09; user: "it
recognizes the unused pads on 7F it just needs to get to them a different
way"). The probe is the warp itself, the same shape as the item's probe
being the press itself. Which doorway is wanted stays the model's; standing
where it can be taken is the harness's.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ck("a refused warp is the fourth way into the recross",
   ex.count("self._pad_recross_for_target(") == 4)
i = ex.index("AND THE SAME RIDE FOR A DOORWAY")
blk = ex[i:i + 3200]
ck("it keys on the warp's own refusal", 'op == "use_warp" and step.get("x") is not None' in blk and '"couldn\'t reach the warp tile" in det' in blk)
ck("the probe is the warp itself", 'self._send_safe("use_warp", **_st)' in blk and "probe=_probe_warp" in blk)
ck("a ride that worked is said in the trace", "used again — and from the cell it set you down" in blk)
ck("...and a ride that did not is said too, with the count", "way(s) " in blk and "ridden again" in blk and "_last_pad_rides" in blk)
ck("the reason is written where the next reader will look", "none for the op a" in blk and "use_warp" in blk)
sys.exit(1 if fails else 0)
