"""A route whose whole payoff is already touched is not offered (2026-08-26).

On SILPH_CO_11F|1,1 four things were unreachable — PC, SILPHCO11F_BEAUTY,
SILPHCO11F_SILPH_PRESIDENT, SILPHCO11F_ROCKET2 — and of those only ROCKET2 had
ever been sighted anywhere the run had walked (SILPH_CO_11F|9,0), where it had
ALREADY been fought. The page still printed "so this is not finished ground,
it is ground you HAVE stood in before: SILPHCO11F_ROCKET2 are in
SILPH_CO_11F|9,0 ... {"op":"go","to":"SILPH_CO_11F|9,0"} walks the whole walked
route for you", and the run took that route twice, to a room that cannot reach
the president, while entry 1 — explore, toward ground never on screen seven
steps away — went unread (user: "its been here twice and used the go command to
go to the other part of 11F which CANT reach the door").

Two faults: a spent payoff offered as a remedy, and "it is ground you HAVE
stood in before" said of a list of four when it was true of one."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/ledger.py").read_text()
i = src.find("A THING ALREADY PRESSED OVER THERE IS NOT A REASON TO WALK BACK")
ck("the spent-payoff filter exists", i > 0)
blk = src[i:i + 5200]

ck("a thing already touched over there is skipped",
   "_nm not in (_tried.get(_reg) or set())" in blk
   and '_tried = getattr(ex, "_tried_objs", {}) or {}' in blk)
ck("...so an offer with nothing left falls through to 'not found the way into'",
   "_seen_in.setdefault(_reg, []).append(_nm)" in blk)

ck("the things no walked ground has reached are counted",
   "_nowhere = [c.key for c in _stuck if c.key not in _named]" in blk
   and "_named = {n for ns in _seen_in.values() for n in ns}" in blk)
ck("...and named, with the route disclaimed for them",
   "never been reachable from any ground you have " in blk
   and "that route does not answer for" in blk)
ck("singular and plural are both handled",
   '"has" if len(_nowhere) == 1 else "have"' in blk
   and '"it" if len(_nowhere) == 1 else "them"' in blk)
ck("the clause is omitted when every stuck thing is accounted for",
   'if _nowhere else ""' in blk)

# never points: no destination is recommended, nothing says where the goal is
_said = " ".join(re.findall(r'"([^"]*)"',
                            "\n".join(l for l in blk.splitlines()
                                      if not l.lstrip().startswith("#"))))
ck("no place is recommended and no goal located",
   not re.search(r"(?i)(you should|go to|president is|the way in is|instead)",
                 _said))

import ast
try:
    ast.parse(src); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
