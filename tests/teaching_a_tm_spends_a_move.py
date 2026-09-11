#!/usr/bin/env python3
"""A TM taught to free a bag slot spends a move, and the page said so nowhere.

The full-bag paragraph ranks the ways out and puts teaching under "USING
spends one and KEEPS ITS VALUE".  The forget argument appeared in the op
form as a parameter, never as a price.

Run 16 cleared slots that way and came out of it with a CHARIZARD holding
FISSURE, MEGA_PUNCH, STRENGTH and DOUBLE_EDGE -- no fire move at all, on
the strongest member of the party, heading for the Elite Four (user,
2026-09-11: "it had actually used fissures tm on char ... at some point it
lost flamethrower").

The game itself asks which move to drop and the answer is final, so saying
it is on-screen tier.  WHICH move is worth keeping stays the model's.
Source-anchored: the paragraph is built inside the bag reader.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "executor.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

blk = SRC.split("WAYS TO FREE A SLOT", 1)[1][:1800]
# the paragraph is built from adjacent string literals, so a sentence can
# straddle a boundary in the SOURCE while reading as one line to the model.
# Normalise the quoting and whitespace away before looking for a sentence.
import re as _re                                        # noqa: E402
flat = _re.sub(r'\s+', " ", blk.replace('"', "").replace("\\", ""))

ck("teaching a TM is still offered as a way to free a slot",
   "a TM teaches its move to a party member that can learn" in blk)
ck("...with the op that does it", '\\"forget\\":\\"MOVE\\"' in blk)
ck("...and now says the named move is gone",
   "that named move is GONE" in flat)
ck("...why it is gone: four slots and the game asks",
   "carries four" in flat and "asks which" in flat)
ck("...and what could ever bring it back",
   "another machine or a level-up" in flat)
ck("...and that the trade can lose more than it gains",
   "can cost a better move than it gives" in flat)
ck("it does not pick a move for the model",
   "FLAMETHROWER" not in blk and "FISSURE" not in blk)

# the rest of the paragraph is untouched
for frag in ("STORING at a ", "a RARE_CANDY ", "an evolution STONE evolves",
             "SELLING at a mart", "TOSSING destroys the thing for good"):
    ck(f"still says: {frag.strip()}", frag in blk)
ck("storing is still offered first, as the reversible one",
   blk.index("STORING at a ") < blk.index("a TM teaches its move"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
