#!/usr/bin/env python3
"""A push resumed after a battle reports the shim's own answer, not None.

bridge.send() returns the observation; the op's verdict is under its
"result". The resume loop took the envelope for the verdict and the
feedback read "push(...) — resumed 1x and it is still not on (9,16):
FAILED — None" while the shim had said "no sequence of shoves puts it on
(9,16)" (Victory Road 2F, 2026-08-28).
"""
from __future__ import annotations
import ast, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
ck("the resumed push unwraps the result envelope",
   'r = (_ro or {}).get("result") or {}' in src and '_ro = self.b.send("push", **step)' in src)
ck("no bare send is taken for a verdict on the resume path",
   'r = self.b.send("push", **step)' not in src)
# the bridge contract this rests on: send() returns the observation
bsrc = (ROOT / "planner" / "bridge.py").read_text()
ck("bridge.send is documented to answer with the observation",
   "def send(self, op: str, **kw) -> dict:" in bsrc)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
