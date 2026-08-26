"""A crossing says where it put you down, and a split map says it is split
(2026-08-26).

Crossing west out of Saffron lands in ROUTE_7|18,12, a pocket whose ONE
recorded exit is back east. The run crossed west three times in a row, landing
in the same nine cells each time, before it reached for `go` (user: "it kept
trying to cross west again and landing itself in the same area").

Two asymmetries. `go` reports "now at ROUTE_7|0,2" and use_warp reports
"(map->ROUTE_7_GATE, moved, warped)"; `cross` reported the bare word
"crossed". And beyond()'s search refuses to double back through `here`, so it
is blind to the rest of the destination's map — while standing OUTSIDE that
map there is no other line that says it is split at all."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import ledger as L

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()
ck("cross names where it landed", "local function crossed_at()" in lua)
c = lua[lua.find("local function crossed_at()"):][:420]
ck("...the map and the cell", 'ow.map and ow.map.id' in c and "cellX" in c)
ck("no bare 'crossed' return is left", '"crossed"' not in lua.split("crossed_at")[-1])
ck("every success path uses it", lua.count("return true, crossed_at()") == 3
   and lua.count("G.input.state[dir] = false; return true, crossed_at()") == 1)

# --- other_part_note ---
led = Path("planner/ledger.py").read_text()
ck("the split-map note exists", "def other_part_note(" in led)
b = led[led.find("def other_part_note("):][:3200]
ck("...it only fires when the other part still has something",
   "parts = _left_parts(ex, reg)" in b and "if not parts:" in b)
ck("...and only when no walk on that map joins them",
   "_joined_on_map" in b and 'return ""            # one map, one walk' in b)
ck("it says the walked route leaves the map",
   "and leaves this map" in b)
ck("...or that no walked route between them is recorded",
   "no walked route between them is recorded" in b)
ck("it recommends nothing",
   not re.search(r"(?i)(you should|go there|instead|use go)",
                 " ".join(re.findall(r'"([^"]*)"',
                          "\n".join(l for l in b.splitlines()
                                    if not l.lstrip().startswith("#"))))))
ck("beyond() carries it on both of its verdicts",
   led.count("_other = other_part_note(ex, dest, here or \"\")") == 1
   and led.count('+ " and ".join(p2) + _other)') == 1
   and led.count('f"have walked" + _other)') == 1)

# behaviour: a map that is NOT split yields nothing
class Ex:
    explored = {"A|0,0": {"n": {"to": "B|0,0"}}, "B|0,0": {}}
    region_seen = {}
    _tried_objs = {}
    sightings = {}
    def _frontier_left(s, r): return []
    def _route(s, a, b): return []
ck("an unsplit destination adds nothing",
   L.other_part_note(Ex(), "B|0,0", "A|0,0") == "")

import ast
try:
    ast.parse(led); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
