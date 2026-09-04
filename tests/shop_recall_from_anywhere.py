"""What a walked shop sells is recalled from anywhere, not one hop (2026-08-26).

The shelf store was complete and its RECALL was one hop deep: a shelf renders
on the floor underfoot, and on a door whose destination is that shop. So from
CELADON_MART_1F the page said "CELADON_MART_2F sells: GREAT_BALL, ..." on the
door to 2F and nothing about the ROOF two legs up, whose machines this run has
pressed and which hold the only FRESH_WATER in the world. Carrying "reach
Saffron", blocked by a guard who wants a drink, it asked both 2F counters for
water twice and left the building (user: "whats it getting on 2F of the celadon
mart" — nothing).

Same shape as WILD GROUND ELSEWHERE: the run's own record, ordered by walked
legs, never by what looks useful."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("SHOPS YOU HAVE WALKED INTO AND WHAT THEY WERE SELLING")
ck("the page recalls every walked shop", i > 0)
blk = src[max(0, i - 1800):i + 3600]

ck("...on the general page, beside the PC-storage line",
   "_rs_line = self._respawn_line(obs)" in src[max(0, i - 3200):i]
   and "_boxed = [m for m in ((obs or {}).get(\"pc_mons\")" in src[i:i + 5600])
ck("ordered by walked legs, and it says how far",
   "_shops.sort()" in blk and "walked leg(s) away" in blk)
ck("a shop with no walked route says so rather than being dropped",
   "no walked route from here" in blk)
ck("a machine is distinguished from a counter",
   "VENDING MACHINES — no clerk: press one" in blk
   and '_shelf_machine' in blk)
ck("it says which op each kind takes",
   '{\\"op\\":\\"buy\\"}' in blk and "a row picked" in blk)
ck("it does not claim to know shops never walked into",
   "walked into are not listed" in blk)
ck("the judgement is left with the model",
   "yours to judge" in blk)
ck("it fires only when something is recorded", "if _shops:" in blk)
ck("a page never dies of it", "shop_recall_error" in blk)

# never points: no item is tied to a purpose, no shop recommended
_said = "\n".join(l for l in blk.splitlines()
                  if not l.lstrip().startswith("#"))
ck("no shop is recommended and no item given a purpose",
   not re.search(r"(?i)(guard|thirst|saffron|you should|you need|go to the|"
                 r"best|cheapest|buy the)", _said))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
