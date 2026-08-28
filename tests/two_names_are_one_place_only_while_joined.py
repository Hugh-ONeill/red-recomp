#!/usr/bin/env python3
"""Two names on one floor are one place only while a walk joins them,
and go names the boulders in the way instead of routing around them.

Sharing an exit tile was the old alias test, and it welded Victory Road
1F's 5,9 (the entrance side) and 14,0 (the stairs side) into one place —
the same stairway sits in both records — while a pushed boulder had cut
them apart. `go 1F|5,9` then walked one hop from 2F back onto 14,0 and
called it arrival, fifty rounds running (2026-08-28, user: "it's also
trying to use 'go' as way around the boulder puzzles ... maybe we can do
the same thing we do with cut"). The shim now reports the names the
current ground carries (parts_here); only names seen joined on the latest
look at a map are aliases; go says when it landed on a part not joined to
the one asked for; and with no walked way to a part of THIS floor, go
names the pushable boulders at the edge and hands over the push op.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import executor as E          # noqa: E402
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
lua = (ROOT / "harness/shim.lua").read_text()
ck("the shim reports the names the current component carries", "o.map.parts_here = parts" in lua)

def fresh():
    ex = C.make()
    ex.explored = {}; ex.region_anchors = {}; ex._parts_by_map = {}; ex.frontier = {}
    ex.log = lambda *a, **k: None; ex._save_memory = lambda *a, **k: None
    return ex
ex = fresh()
ex.frontier = {"VICTORY_ROAD_1F|5,9": {"1,1": {}}, "VICTORY_ROAD_1F|14,0": {"1,1": {}}}
ex._rebuild_area_aliases()
ck("sharing an exit tile no longer makes two names one place",
   "VICTORY_ROAD_1F|14,0" not in E.AREA_ALIASES.get("VICTORY_ROAD_1F|5,9", ()))
ck("...so the two are not the same area", not E.Executor._same_area("VICTORY_ROAD_1F|14,0", "VICTORY_ROAD_1F|5,9"))
ex.note_region_anchors({"map": {"id": "VICTORY_ROAD_1F", "region": "14,0", "parts_here": ["14,0", "5,9"],
                                "region_anchors": {"5,9": "5,9", "14,0": "14,0"}}})
ck("names the current ground carries together are one place",
   E.Executor._same_area("VICTORY_ROAD_1F|14,0", "VICTORY_ROAD_1F|5,9"))
ex.note_region_anchors({"map": {"id": "VICTORY_ROAD_1F", "region": "14,0", "parts_here": ["14,0"],
                                "region_anchors": {"5,9": "5,9", "14,0": "14,0"}}})
ck("a later look that finds them cut apart un-joins them",
   not E.Executor._same_area("VICTORY_ROAD_1F|14,0", "VICTORY_ROAD_1F|5,9"))
src = (ROOT / "planner/executor.py").read_text()
ck("the joined names persist with the atlas", '"parts_by_map": getattr(self, "_parts_by_map", {})' in src
   and 'self._parts_by_map = data.get("parts_by_map", {}) or {}' in src)
ck("go says when it landed on a part not joined to the one asked for",
   "is NOT joined to it right now" in src and "moved between them (a boulder, a switch)" in src)
i = src.index("THE CUT RULE'S HONEST TWIN")
blk = src[i:i + 2200]
ck("with no walked way to a part of THIS floor, go names the pushable boulders at the edge",
   'self._knows_move(obs, "STRENGTH")' in blk and 'o.get("kind") == "boulder" and o.get("reachable")' in blk
   and "go does not push" in blk)
ck("...and hands over the push op without saying where to push", "to_x" in blk and "is yours" in blk)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
