"""Three floors, sorted by distance, and no word that there were more.

FLOORS YOU HAVE WALKED THAT ARE NOT FINISHED named `_rows[:3]`. From
Vermilion every house in the city outranks ROCK_TUNNEL_1F — nine legs away,
holding the untaken ladder that leads on — so the page listed three doors in
the city the run was already standing in, and the run ping-ponged
Cerulean/Vermilion hunting a way onward (user, 2026-08-30: "its pingponging
again ... ignoring the way through lavender").

The sibling list right below it learned this on 2026-08-25 and its comment
says so in as many words: "AND THE CUT WAS THE LIE ... Every floor is named,
in a shorter form; only a very long tail is counted." Same rule here."""
import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

i = src.find("FLOORS YOU HAVE WALKED THAT ARE NOT FINISHED")
ck("the list exists", i > 0)
blk = src[max(0, i - 2200):i + 900]
ck("the bare cut at three is gone",
   'NOT FINISHED: "\n                          + "; ".join(' not in blk
   and "+ _full + _tail" in blk)
ck("the nearest few are still named in full",
   "_full = " in blk and "_rows[:3]" in blk)
ck("...and the rest are named, not dropped",
   "_rest = _rows[3:30]" in blk and "also " in blk)
ck("...each with how many of its doorways are untaken and how far",
   "never taken, " in blk and "leg(s))" in blk)
ck("...saying so when there is no walked route to one",
   "no walked route)" in blk)
ck("a tail beyond that is COUNTED, never silently dropped",
   "_more = len(_rows) - 3 - len(_rest)" in blk
   and "more floor(s) not named" in blk)

# the sibling list is the precedent; if it regresses, this rule has no anchor
ck("the sibling list still names every floor it has",
   "_shown = _urows[:30]" in src and "AND THE CUT WAS THE LIE" in src)

# ...and the record of the page must not cut it off where it gets interesting
ck("our own journal keeps the whole page",
   "memory=memory[:24000]" in src and "memory=txt[:24000]" in src
   and "memory=memory[:6000]" not in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
