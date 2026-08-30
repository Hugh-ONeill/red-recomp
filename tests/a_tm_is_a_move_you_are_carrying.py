"""TMs were mentioned only when the bag was full.

The bag-pressure note lists using a TM as a way to FREE A SLOT, and that was
the only place the page ever mentioned one — so TMs sat unread until the run
was out of room and were then spent to make space, which is the moment a TM
is least likely to be the right move (user, 2026-08-30: "we might want a more
intense item-usage policy that encourages the usage of tms when we get them
and/or when we get new pokemon, so we use the tms at some point other than
just when the bag is full").

The two moments a TM is worth a thought are when it ARRIVES and when the
PARTY CHANGES, and this process can see both.

Everything the note says is on the item's own label or in the party: the move
is IN the TM's name (TM_THUNDERBOLT), and whether anyone knows it already is
in obs.party. Compatibility is NOT said — the harness does not know it, and
the game states it plainly when a TM will not take. Which Pokemon, what it
would forget, and whether to bother stay the model's.
"""
import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
src = (ROOT / "planner" / "executor.py").read_text()

i = src.find("A TM IS ONLY MENTIONED WHEN THE BAG IS FULL")
ck("the note exists", i > 0)
blk = src[i:i + 4200]
flat = re.sub(r'"\s*\n\s*f?"', "", blk)

ck("it reads the TMs out of the bag",
   'if str(k).startswith("TM_")' in blk)
ck("...and drops any whose move the party already knows",
   "_unused = [t for t in _tms if t[3:].upper() not in _knows]" in blk)
ck("it fires when a TM arrives",
   "set(_tms) - set(_prev_tms or ())" in blk)
ck("...and when the party roster changes",
   "_roster != _prev_roster" in blk)
ck("...and not on every page otherwise",
   "if _unused and _fresh:" in blk)
ck("it says which of those two it is",
   "a new TM is in the bag" in blk and "your party has changed" in blk)

ck("the move is read off the TM's own name",
   "A TM's NAME IS THE MOVE IT TEACHES" in flat)
ck("it gives the op, and the forget clause for a full moveset",
   "use_item" in flat and "forget" in flat and "already knows four" in flat)
ck("it says a TM is spent when used",
   "A TM IS SPENT WHEN IT IS USED" in flat)
ck("it does NOT claim to know compatibility",
   "not something this harness knows" in flat
   and "compatible with" not in flat and "can learn it" not in flat)
ck("...and leaves the choice",
   "is yours to judge" in flat)
ck("it is recorded, like every other thing the model is told",
   'self.log("tm_note"' in blk)

# the bag-pressure note is untouched: it is right about what it says
ck("the full-bag note still offers a TM as a way to free a slot",
   "a TM teaches its " in src and "SELLING " in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
