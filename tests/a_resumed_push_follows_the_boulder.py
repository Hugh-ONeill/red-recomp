#!/usr/bin/env python3
"""A resumed push follows the boulder.

Victory Road 1F, 2026-09-06: push(x=15,y=14,to_x=17,to_y=13) moved the
boulder part way, a wild fight interrupted, and the executor's resume
re-sent the push with the boulder's ORIGINAL cell — "resumed 1x and it is
still not on (17,13): FAILED — nothing is standing at (15,14) to push"
(user: "unsure why push is failing here also"). The model fixed it by hand
a round later, re-sending from (16,14), and landed the boulder in four
shoves.

The boulder that moved is the one whose cell is new since the op began;
when exactly one is, the resume aims there. And the shim's refusal now
names where the boulders stand, so a hand re-send has the cell too.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EXEC = (ROOT / "planner/executor.py").read_text()
SHIM = (ROOT / "harness/shim.lua").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

i = EXEC.index("def _follow(_step, _o):")
blk = EXEC[i - 1200:i + 2600]
ck("the boulders' cells at op start are remembered",
   "_rocks0 = {(t.get(\"x\"), t.get(\"y\"))" in blk and "(pre_obs or {})" in blk)
ck("the one that moved is the one whose cell is new",
   "_new = list(_now - _rocks0)" in blk and "if len(_new) == 1" in blk)
ck("...and the resume aims there", 'self.b.send("push", **_cur)' in blk
   and "_cur = _follow(step, obs)" in blk)
ck("...saying so in the journal", 'self.log("push_resume_followed"' in blk)
ck("the trace still names the op as written", "push({','.join(f'{k}={v}' for k, v in step.items())})" in EXEC)
ck("the shim's refusal names where the boulders stand",
   "the boulders on this floor stand at " in SHIM
   and "a boulder already shoved is " in SHIM)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
