#!/usr/bin/env python3
"""The fly list is shown only when a party member knows FLY.

The list is the fly picker's own screen, which exists only through a
Pokemon that knows the move; printed to a party with no FLY and no HM02,
it had the run trying FLY on every long walk (user, 2026-08-28: "we
shouldn't display the fly list until someone actually knows fly").
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
lua = (ROOT / "harness/shim.lua").read_text()
i = lua.index("if #fly > 0 then o.fly_towns = fly end")
head = lua[i - 1600:i]
ck("the shim builds the list only when a party member knows FLY",
   'if tostring(type(mv) == "table" and mv.id or mv) == "FLY" then' in head and "if _knows_fly then" in head)
src = (ROOT / "planner/executor.py").read_text()
j = src.index("FLY GOES ONLY TO THESE")
ck("the page prints it only when a party member knows FLY", 'self._knows_move(obs, "FLY")' in src[j:j + 700])
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
