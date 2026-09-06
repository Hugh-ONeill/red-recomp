#!/usr/bin/env python3
"""A boulder down the hole is a push that worked.

Victory Road 3F, 2026-09-06. push(x=22,y=15,to_x=23,to_y=15) shoved the
boulder into the hole the map lists for boulders; the game hid it and set
it down on 2F beside the second switch, which is the one move the whole
cave turns on. The op's success test asked "is a boulder standing on
(23,15)", which a hole can never satisfy, so the resume rule re-sent the
push and the round read:

  resumed 1x and it is still not on (23,15): FAILED — nothing is standing
  at (22,15) to push — the boulders on this floor stand at (22,3), (13,12),
  (24,10)

A success reported as a failure, about the puzzle's key move. Now a push
aimed at a listed boulder hole has worked when the floor holds one boulder
fewer than when the op began, and the trace says the boulder went down the
hole and is no longer on this floor. Where it landed is not this floor's
to say.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                 # noqa: E402
EXEC = (ROOT / "planner/executor.py").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def floor(boulders, holes=((23, 15),)):
    return {"map": {"id": "VICTORY_ROAD_3F",
                    "boulder_holes": [{"x": x, "y": y, "reachable": True} for x, y in holes],
                    "objects": [{"kind": "boulder", "name": f"B{i}", "x": x, "y": y}
                                for i, (x, y) in enumerate(boulders)]}}

before = floor([(22, 3), (13, 12), (24, 10), (22, 15)])
after = floor([(22, 3), (13, 12), (24, 10)])
ck("the incident's own shove is a success", E.push_went_down_hole(before, after, 23, 15))
ck("a push at a hole where no boulder left the floor is not",
   not E.push_went_down_hole(before, before, 23, 15))
ck("a push at a cell that is not a hole is judged the old way",
   not E.push_went_down_hole(before, after, 22, 14))
ck("a floor change is not a drop", not E.push_went_down_hole(
   before, {"map": {"id": "VICTORY_ROAD_2F", "boulder_holes": [{"x": 23, "y": 15}], "objects": []}}, 23, 15))
ck("no holes listed, no claim", not E.push_went_down_hole(floor([(22, 15)], holes=()), floor([], holes=()), 23, 15))

i = EXEC.index('self._push_hole_note = ""')
blk = EXEC[i:i + 1500]
ck("the drop is checked before the resume rule",
   "push_went_down_hole(pre_obs, obs, step.get(\"to_x\")," in blk
   and blk.index("push_went_down_hole") < blk.index("not _rock_on(obs, step.get(\"to_x\")"))
ck("...and the trace says the boulder left the floor, claiming nothing about where it landed",
   "the boulder went down the hole at " in blk and "where it landed is not recorded " in blk)
ck("the note rides the ok line", '+ (getattr(self, "_push_hole_note", "") or ""))' in EXEC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
