#!/usr/bin/env python3
"""A map with no edges is not thereby indoors.

Standing in SAFARI_ZONE_WEST — tall grass, fences, open sky — the page
read "WHERE YOU STAND: SAFARI_ZONE_WEST|20,0 — indoors, no edges; the
doors are the only ways out" (leg 36, 2026-08-26). The engine's own
outside test counts only OVERWORLD and PLATEAU, so every FOREST map
(Viridian Forest, the four Safari areas) fell into the "indoors" branch
along with buildings. The shim now emits the map's tileset and the words
follow it: a forest is walled ground under open sky, a building is
indoors, and a map whose tileset is unknown is just "no edges".
"""
from __future__ import annotations
import ast, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "planner"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger as L            # noqa: E402
import untried as U           # noqa: E402
import candidates as C        # noqa: E402  (its fixture, checks guarded by __main__)

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def page(tileset):
    ex = C.make(frontier={U.HERE: ["1,1"]})
    o = C.obs(ex, ["1,1"])
    o["map"]["connections"] = {}
    if tileset is not None:
        o["map"]["tileset"] = tileset
    cands = L.build(ex, o, target="flag:X")
    return L.render(cands, ex, o, target="flag:X")

forest = page("FOREST")
ck("a FOREST map with no edges is not called indoors", "indoors" not in forest)
ck("...it is walled ground under open sky", "open sky" in forest)
ck("...and its gates/doors are still the only ways out", "only ways out" in forest)
room = page("INTERIOR")
ck("an INTERIOR map with no edges is still indoors", "indoors, no edges" in room)
bare = page(None)
ck("no tileset at all: no edges, and no claim either way",
   "no edges" in bare and "indoors" not in bare and "open sky" not in bare)
ck("an OVERWORLD map with no connections is not indoors either",
   "indoors" not in page("OVERWORLD"))

# the same words on the executor's exits block, and the shim's refusal
ex_src = Path("planner/executor.py").read_text()
ck("the executor's no-edge line takes its words from the ledger",
   "ledger.no_edge_words(m)" in ex_src)
tree = ast.parse(ex_src)
lits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
ck("...and no longer says a no-edge map \"is indoors\" on its own",
   not any("NO EDGES AT ALL" in v and "indoors" in v for v in lits))
lua = Path("harness/shim.lua").read_text()
ck("the shim's observation carries the map tileset",
   re.search(r"tileset = md and md\.tileset", lua) is not None)
ck("the shim's no-edge refusal is worded by tileset",
   '_ts == "FOREST"' in lua and "open sky" in lua)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
