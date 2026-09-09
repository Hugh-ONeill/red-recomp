#!/usr/bin/env python3
"""A target behind a warp pad is retired only when every arrival has been
spent on it, not after the first sweep.

Silph 5F's Card Key ball is reachable only by riding a pad and walking off
its far side. _pad_recross_for_target tries up to three arrivals per press,
and it used to mark the target done the moment any ride happened. So the
first sweep — 3F, 6F and 7F, none of which landed on the ball's side — spent
that target for the whole run: every later press hit the guard at the top
and returned None, sending no op at all. The bot stood on 5F naming the item
and never reaching for it, which reads as refusing to try (2026-09-09).
The arrival the function's own docstring calls the valuable one, 9F's pad
taken once, was never among the three. Now the arrivals spent on a target
are remembered, the next press skips them and tries the rest, and the target
retires when the list runs out.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = ex.index("def _pad_recross_for_target")
blk = ex[i:i + 9000]
ck("the arrivals already spent on this target are read", '_spent = {tuple(x) for x in' in blk and '(getattr(self, "_pad_spent", {}) or {}).get(key0, ())}' in blk)
ck("...and skipped when the candidates are gathered", 'if (str(c[1]), str(c[2])) not in _spent]' in blk)
ck("the target retires only when nothing is left to try", "every arrival this map has, has now been spent on this target" in blk and blk.index("if not cands:") < blk.index("self._recrossing = True"))
ck("each ride is recorded as it is attempted", "tried = []" in blk and "tried.append((reg, k))" in blk)
ck("...and written back on the way out", "_sp[key0] = sorted(" in blk and "for r0, k0 in tried}" in blk)
ck("the old burn-on-any-ride retirement is gone", "one shot per target per attempt" not in blk)
ck("the three-arrivals-per-press budget stays", "if rode >= 3:" in blk)
ck("the reason is written where the next reader will look", "so the next press RESUMES instead of" in blk)
sys.exit(1 if fails else 0)
