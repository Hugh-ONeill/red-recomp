#!/usr/bin/env python3
"""A component cut off from the cell it is named for gets its own name,
and the doors on its side move with it.

Region names are painted once and kept, which is right when the space
only grows (a tree cut, a boulder pushed). The Mansion's statue switches
also SHRINK it: both halves of 1F were first walked joined, every cell of
both carried "1,1", the sealed basement-stairs half kept answering to the
main half's name, and its door to B1F was filed under a region that
cannot walk to it — so a route from the main half advertised B1F one hop
away (TODO 2026-08-23; user 2026-08-28: "the rooms change depending on
the switch position").
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
i = lua.index("A COMPONENT CUT OFF FROM THE CELL IT IS NAMED FOR")
blk = lua[i:i + 2600]
ck("the split fires only when the name's own cell is not in the component",
   "not rreach[name] and known[name] == name" in blk)
ck("...and only when well under the named ground is here (an NPC on the anchor is not a split)",
   "here_n * 10 < total * 7" in blk and "total >= 12" in blk)
ck("...repaints only this component", "for k in pairs(rreach) do" in blk and "if known[k] == name then known[k] = new end" in blk)
ck("...and reports the split with the doors on this side",
   "o.map.region_split = { from = split_from, to = name, doors = doors }" in lua)
ck("an anchor is the cell the name names whenever that cell still carries it",
   "if known[v] == v then" in lua and "anchors[v] = v" in lua)

def fresh():
    ex = C.make()
    ex.explored = {"POKEMON_MANSION_1F|1,1": {
        "21,23": {"to": "POKEMON_MANSION_B1F|10,9", "n": 1},
        "26,27": {"to": "CINNABAR_ISLAND|1,0", "n": 3},
        "2,3": {"to": "POKEMON_MANSION_2F|4,4", "n": 2}}}
    ex.region_anchors = {"POKEMON_MANSION_1F": {"1,1": "1,1", "24,20": "1,1"}}
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda *a, **k: None
    return ex
obs = {"map": {"id": "POKEMON_MANSION_1F", "region": "20,19",
               "region_anchors": {"1,1": "1,1", "20,19": "20,19"},
               "region_split": {"from": "1,1", "to": "20,19", "doors": ["21,23", "26,27", "27,27"]}}}
ex = fresh()
ex.note_region_anchors(obs)
new = ex.explored.get("POKEMON_MANSION_1F|20,19") or {}
old = ex.explored.get("POKEMON_MANSION_1F|1,1") or {}
ck("the sealed half's doors are re-keyed under its new name",
   new.get("21,23", {}).get("to") == "POKEMON_MANSION_B1F|10,9" and "26,27" in new)
ck("...and no longer sit under the main half's name", "21,23" not in old and "26,27" not in old)
ck("a door the sealed half never had stays where it was", old.get("2,3", {}).get("to") == "POKEMON_MANSION_2F|4,4")
ck("a door listed that was never recorded is simply not there", "27,27" not in new)
st = ex.region_anchors["POKEMON_MANSION_1F"]
ck("the old name's stray anchor on this side is dropped; its own cell and the new name stay",
   "24,20" not in st and st.get("1,1") == "1,1" and st.get("20,19") == "20,19")
ex2 = fresh()
ex2.note_region_anchors({"map": {"id": "POKEMON_MANSION_1F", "region": "1,1", "region_anchors": {"1,1": "1,1"}}})
ck("an observation without a split changes nothing", "21,23" in ex2.explored["POKEMON_MANSION_1F|1,1"])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
