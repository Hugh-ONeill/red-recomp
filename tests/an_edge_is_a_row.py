"""An edge is a row, and the walk that chooses a cell is not stripped
(2026-08-26).

ROUTE_13's west crossing lands in ROUTE_14|16,6, a four-cell nook. Every way in
went there: `{"op":"go","to":"ROUTE_14"}` (the nook is the only walked part of
that map) and `{"op":"cross","dir":"west"}` (cross picks its own gap on the
edge). User: "go to rt 14 routes directly into the pocket", "so does cross west
from rt 13".

walk_to cannot path between maps, so [walk_to <another cell of that edge>,
cross] is the ONLY way to say where to cross from — and the macro sanitiser
stripped a trailing walk_to before ANY map-changing op, which made the correct
play unwritable (user: "its because of the precise boundary, if walk_to doesnt
go between maps it wont route").

The hazard that rule was written for is a DOOR MAT: walking onto one teleports.
A seam is not a mat."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

i = src.find("AND NOT BEFORE A CROSS")
ck("the strip is scoped", i > 0)
blk = src[i:i + 1900]
ck("...kept for a cross",
   'macro[-1].get("op") == "cross"' in blk and "stripped = 0" in blk)
ck("...still stripped for everything else (the door-mat case)",
   'if _s.get("op") != "walk_to":' in blk and "keep = body[:_j + 1]" in blk)
ck("the log still fires when something is stripped",
   'self.log("escalate_stripped_walkto"' in src)

# the contract says so
j = src.find("AN EDGE IS\nA ROW, NOT A POINT")
ck("the op contract says an edge is a row", j > 0)
doc = src[j:j + 900]
ck("...and that the crossing cell decides where you come out",
   "decides which part of the next map you come out in" in doc)
ck("...names the pairing that chooses it",
   'walk_to' in doc and "immediately before" in doc)
ck("...says why the pairing is required",
   "cannot path between maps" in doc)
ck("...and warns a ledge can be one-way",
   "one-way ledge" in doc)
ck("it points at no particular map or cell",
   not re.search(r"(?i)(route_?1[0-9]|you should|go west|the pocket)", doc))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
