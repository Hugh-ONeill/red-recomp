"""TMs were mentioned only when the bag was full.

The bag-pressure note lists using a TM as a way to FREE A SLOT, and that was
the only place the page ever mentioned one — so TMs sat unread until the run
was out of room and were then spent to make space, which is the moment a TM
is least likely to be the right move (user, 2026-08-30: "we might want a more
intense item-usage policy that encourages the usage of tms when we get them
and/or when we get new pokemon, so we use the tms at some point other than
just when the bag is full").

THIS TEST WAS ITSELF WRONG, and that is the more useful half of its record.
It asserted "it does NOT claim to know compatibility — the harness does not
know it", and by the time anyone read that line back the harness DID: the
shim publishes obs.machines off the party screen a machine opens, which marks
every member ABLE or NOT ABLE at once, and the TOSS guard was already
printing that list at the moment of DESTRUCTION. So the facts were being
withheld where they would have helped and shown where they could not, and a
passing test said that was correct. A test pins a decision, and a decision
outlives its reason — when the reason goes, the test goes with it.

What is pinned here now is the PAGE's standing list: what you carry that
nobody knows, who the game marks able, and what you already answered. The
arrival QUESTION that replaced the old note's job, and the measurements that
moved it, are in a_machine_is_a_question_when_it_arrives.py.
"""
import sys
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
src = (ROOT / "planner" / "executor.py").read_text()

i = src.find("A TM IS ONLY MENTIONED WHEN THE BAG IS FULL")
ck("the note exists", i > 0)
blk = src[i:i + 6000]
flat = re.sub(r'"\s*\n\s*f?"', "", blk)

ck("it reads the machines out of the bag, the shim's list not a name test",
   '((start or {}).get("machines") or {}).get(_it)' in blk)
ck("...and drops any whose move somebody already knows",
   "if _mv and _mv not in _kn" in blk
   and "_mach = self._teachable_now(start)" in blk)
ck("it names who the game marks ABLE, by slot",
   "ABLE: " in flat and "(slot {i})" in blk)
ck("...and separately what NOBODY in this party can take",
   "NOBODY IN THIS PARTY CAN TAKE" in flat)
ck("...saying an evolution can change that",
   "CHANGES WHEN IT EVOLVES" in flat)
ck("it says where ABLE comes from, so it is not read as a guess",
   "the machine's own party screen" in flat)
ck("it gives the op, and the forget clause for a full moveset",
   "use_item" in flat and "forget" in flat and "already knows four" in flat)
ck("it says the move written over is gone", "THAT MOVE IS THEN GONE" in flat)
ck("it says a TM is spent and an HM is not",
   "A TM is spent when it works; an HM never is" in flat)
ck("it shows back the answer already given, so it can be changed",
   "asked already, and you said no" in blk)
ck("...and says the choice can be made here at any time",
   "any time you change your mind" in flat)

# THE CLAIM THAT WAS FALSE, pinned inverted so it cannot come back
ck("it never again says compatibility is unknowable",
   "not something this harness knows" not in src)

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
