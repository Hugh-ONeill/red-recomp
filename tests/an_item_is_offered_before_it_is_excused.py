#!/usr/bin/env python3
"""An item you cannot walk to leads with the press, not with the excuse.

Silph 5F's Card Key ball sits behind a warp pad: no walk reaches it, but a
press rides a pad the run has already used and tries again from where it
lands. The line said all of that — and said "not walkable-to right now"
FIRST, with the offer behind a semicolon. Through six failed subgoals the
run hunted a walking route to a ball two pad-rides away (2026-09-09; user:
"move the invitation first"). Now the order is: press it, it is free, it is
worth sending anyway because a press re-rides a pad you know. The bag-full
case still leads with the refusal, because there the press really does take
nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lg = (ROOT / "planner" / "ledger.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = lg.index("if c.kind == \"item\" and c.status == \"untouched\":")
blk = lg[i:i + 3000]
ck("the press comes first", '"PRESS IT: pressing A takes it and it costs nothing"' in blk)
ck("...and the unreachable clause hangs off it, not before it", blk.index("PRESS IT:") < blk.index("WORTH SENDING"))
ck("...saying no walk reaches it as the reason it needs saying", "even though no walk " in blk and "reaches it right now" in blk)
ck("...and still naming the mechanic that gets there", "press rides it again and tries from where it" in blk)
ck("the bag-full case still leads with the refusal, which is the true one", blk.index("the BAG IS FULL") < blk.index("PRESS IT:"))
ck("a reachable item says none of it", '("" if c.reachable else' in blk)
ck("the reason is written where the next reader will look", "THE INVITATION COMES FIRST." in blk)
sys.exit(1 if fails else 0)
