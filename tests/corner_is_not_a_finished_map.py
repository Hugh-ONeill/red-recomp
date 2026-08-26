"""A sealed corner is not a finished map (2026-08-26).

Route 13's west crossing lands in ROUTE_14|16,6, a four-cell nook whose only
walked way out is back east. The page opened

  FULLY WORKED: nothing here is untried or unpressed

in the same breath as "its north, south, west side(s) have never been on
screen" and "GROUND YOU HAVE SEEN BUT CANNOT WALK TO FROM HERE: 38 cell(s)"
(user: "uh oh its in the rt 14 pocket"). Both true; together they say a route
nobody has looked at is finished.

The frontier branch already has the honest wording for a floor with unseen
ground you can WALK to. A sealed corner has none you can walk to and is
exactly as unfinished — so say what IS known: this is a corner, and where the
rest is entered from is not recorded."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/ledger.py").read_text()
i = src.find('"FULLY WORKED" IS ABOUT A REGION AND READS AS A MAP')
ck("the sealed-corner case is handled", i > 0)
blk = src[i:i + 2200]

ck("the bare 'FULLY WORKED' absolute is gone",
   'head += (". FULLY WORKED: nothing here is untried or unpressed'
   not in src)
ck("...replaced by what is actually known",
   '". NOTHING HERE IS UNTRIED OR UNPRESSED"' in blk)
ck("it names the map and which sides were never looked at",
   'm.get("id")' in blk and "never been on screen" in blk
   and "_unseen_sides" in blk)
ck("it says where the rest is entered from is NOT recorded",
   "is not " in blk and "recorded" in blk)
ck("...and offers both readings without choosing",
   "another cell of the same edge" in blk and "another map entirely" in blk)
ck("a region with every side seen reads as before",
   'if _unseen_sides else ""' in blk
   and "Staying finds nothing new" in blk)
ck("the frontier branch is still the one that fires when there IS a frontier",
   "elif fully_worked(cands) and not _fr:" in src)
ck("it commands nothing",
   not re.search(r"(?i)(you should|go back|cross again|try the)",
                 " ".join(re.findall(r'"([^"]*)"', blk))))

# the sides come from the shim's own footprint field
lua = Path("harness/shim.lua").read_text()
ck("sides_unseen is published by the footprint",
   "m.sides_unseen = unseen_sides" in lua)
ck("...and the ledger drops any side that HAS been seen",
   "_unseen_sides = [x for x in _unseen_sides if x not in sides]" in src)

import ast
try:
    ast.parse(src); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
