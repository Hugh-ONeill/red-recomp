#!/usr/bin/env python3
"""Thinking is worth what it costs only at a wall it can actually climb.

RUN 16, MEASURED (2026-09-11/12). Threshold 3, in play:

    normal round   n=1675   median 34.9s   0.36 new clean ops   23% added nothing
    thinking round n=  37   median 114.8s  1.16 new clean ops    8% added nothing

43 minutes of an 18.9-hour play budget for roughly three times the clean
ops on the rounds that were going worst. It stays on.

But it fired on ten legs and on eight of them went once or twice and the
leg moved on, while on defeat_blaine it went ELEVEN times across two
attempts with the stall deepening under it — stale 3, 4, 5, then 3, 4, 5
again — the model re-arguing "I must deliver the Dome Fossil to open the
Gym" from inside the Pokemon Mansion at 115 seconds a go. Deliberation
does not repair a false premise; it dresses one. So the budget is per DRY
STRETCH and refills the moment the world moves: a leg that keeps getting
somewhere keeps thinking, a leg at a wall stops paying for it.

AND THE AUTHOR, which had never thought at all and whose A/B file was
empty. Measured on the real leg-author prompt, 5,659 tokens: 38.6s off,
290.8s on. That is 7.5x, WORSE than play's 3.3x, because the thinking
trace is a roughly fixed ~2000 generated tokens and the executor's
17,800-token page dilutes it with prefill. Every author pass would have
added 18.5 hours to run 16's four hours of authoring. The third plan for
a leg is where the cheap answers are already spent, and only one of the
three drafts deliberates — best-of-N buys variety, and three slow answers
to one question is not variety.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import brock_probe as B                                    # noqa: E402
import executor as E                                       # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


class Gate:
    """The gate as escalate() runs it, with nothing else of the executor."""
    def __init__(self, cap=3, thresh=3):
        self.stale = 0
        self.dry = 0
        self.cap = cap
        self.thresh = thresh
        self.fired = []

    def round(self, moved):
        # the two lines from escalate(), in order
        think = (self.thresh > 0 and self.stale >= self.thresh
                 and (self.cap <= 0 or self.dry < self.cap))
        if think:
            self.dry += 1
        self.fired.append(think)
        # ...and the accounting at the end of the round
        if moved:
            self.stale = 0
            self.dry = 0
        else:
            self.stale += 1
        return think


# ---- the wall: it thinks three times and then stops paying -------------
g = Gate()
for _ in range(12):
    g.round(moved=False)
ck("a leg that never moves thinks exactly the cap, not once more",
   sum(g.fired) == 3)
ck("...and nothing fires before the threshold",
   not any(g.fired[:3]))

# ---- the leg that keeps getting somewhere keeps its budget ------------
g = Gate()
seq = [False]*4 + [True] + [False]*4 + [True] + [False]*4
fired = [g.round(moved=m) for m in seq]
ck("a dry stretch that ends pays the budget back", sum(fired) > 3)
ck("...and each stretch is still capped",
   all(s <= 3 for s in (sum(fired[0:5]), sum(fired[5:10]), sum(fired[10:]))))

# ---- run 16's own two shapes, replayed ---------------------------------
blaine = Gate()
for _ in range(7):            # defeat_blaine's second attempt, all dry
    blaine.round(moved=False)
ck("defeat_blaine's eleven firings would now be three",
   sum(blaine.fired) == 3)
# the shape of the other eight: three dry rounds, the fourth thinks,
# and THAT round is the one that gets somewhere. One firing, and the
# budget is whole again afterwards.
eight = Gate()
for m in (False, False, False, True):
    eight.round(moved=m)
ck("...while a leg that thinks once and moves on spends one",
   sum(eight.fired) == 1 and eight.dry == 0 and eight.stale == 0)

# ---- the cap can be lifted, and lifting it restores the old behaviour --
g = Gate(cap=0)
for _ in range(12):
    g.round(moved=False)
ck("a cap of 0 is no cap, which is what run 16 ran", sum(g.fired) == 9)
g = Gate(thresh=0)
for _ in range(12):
    g.round(moved=False)
ck("threshold 0 is thinking off entirely", not any(g.fired))

# ---- the knobs exist and default to what was measured ------------------
ck("the cap is a knob with a default of 3", B.THINK_DRY_CAP == 3)
ck("...read from the environment like its sibling",
   "RED_THINK_DRY_CAP" in (ROOT / "planner" / "brock_probe.py").read_text())

SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the executor spends the budget and resets it where staleness resets",
   "self._thought_dry += 1" in SRC
   and re.search(r"self\._stale_rounds = 0\n\s+#.*\n\s+#.*\n\s+self\._thought_dry = 0",
                 SRC))
ck("the cap biting is written down, not silent",
   'self.log("think_capped"' in SRC)

# ---- the author gate ---------------------------------------------------
ASRC = (ROOT / "planner" / "author.py").read_text()
ck("the author can be told to think, and never decides it itself",
   'ap.add_argument("--think"' in ASRC
   and "think: bool = False" in ASRC)
ck("only ONE of the drafts deliberates",
   "think=bool(think) and i == 0" in ASRC)
ck("...and only its FIRST round, not the validator's corrections",
   "think=bool(think) and rnd == 1" in ASRC)

CSRC = (ROOT / "campaign.sh").read_text()
ck("campaign.sh spends it from the third plan for a leg",
   'RED_AUTHOR_THINK_FROM:-3' in CSRC
   and '"$((attempt + 1))" -ge "$_tf"' in CSRC)
ck("...and it can be turned off without editing the script",
   '"$_tf" -gt 0' in CSRC)
ck("campaign.sh is still valid shell",
   subprocess.run(["bash", "-n", str(ROOT / "campaign.sh")]).returncode == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
