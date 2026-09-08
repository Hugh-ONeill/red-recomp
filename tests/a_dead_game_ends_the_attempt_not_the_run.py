#!/usr/bin/env python3
"""A game that dies mid-attempt ends the attempt as no result, and the
campaign boots it again for the same attempt.

2026-09-08, 16:27:28: the headed love window closed with no traceback, no
core and no kernel line, and the executor ran on for seventy minutes — every
op timed out after two minutes, every round asked the model again, and the
page filled with empty FAILEDs (user: "im not sure whats going on ... i
havent seen the game screen in a bit"). The shim writes run/heartbeat every
frame, so a heartbeat older than a minute at the moment an op times out is
the game gone. The executor now exits 67 there, after saving its memory, and
campaign.sh re-runs the SAME attempt up to three boots before it counts.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
from executor import Executor                                  # noqa: E402

ex = (ROOT / "planner" / "executor.py").read_text()
camp = (ROOT / "campaign.sh").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


class _B:
    def __init__(self, run):
        self.run = run


class _E(Executor):
    def __init__(self, run):                      # no bridge, no game
        self.b = _B(run)


import tempfile                                                # noqa: E402
with tempfile.TemporaryDirectory() as d:
    e = _E(Path(d))
    ck("no heartbeat file reads as unknown, not as dead", e._game_heartbeat_age() is None)
    hb = Path(d) / "heartbeat"
    hb.write_text("x")
    ck("a fresh heartbeat reads as young", (e._game_heartbeat_age() or 99) < 5)
    old = time.time() - 300
    import os
    os.utime(hb, (old, old))
    ck("a stale heartbeat reads its age", (e._game_heartbeat_age() or 0) > 250)

ck("the executor exits with its own code when an op times out on a stale heartbeat", "if age is not None and age > 60:" in ex and 'self.log("game_dead", op=op, heartbeat_age=round(age, 1))' in ex and "sys.exit(self.GAME_DEAD_EXIT)" in ex)
ck("...after saving what it walked", ex.index("self._save_memory()", ex.index('self.log("game_dead"')) < ex.index("sys.exit(self.GAME_DEAD_EXIT)"))
ck("the code is 67, distinct from 66 (never came up)", "GAME_DEAD_EXIT = 67" in ex)
ck("the campaign boots the same attempt again on 67", 'if [ "$rc" -eq 67 ] && [ "$_boot" -lt 3 ]; then' in camp and "for _boot in 1 2 3; do" in camp)
ck("...continuing from the save", 'cont=(--continue)\n      continue' in camp)
sys.exit(1 if fails else 0)
