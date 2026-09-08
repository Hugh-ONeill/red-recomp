#!/usr/bin/env python3
"""A plan whose objective is true before its first step is refused by the
author on the snapshot's bag whatever its mode, and run anyway by the
executor rather than declared met.

Run 16, 2026-09-07, "Give a FRESH WATER ... to the thirsty guard": the plan
ended on {"lacks_item": ["FRESH_WATER"]}, true before any water was bought.
The author's already-true check trusts the bag only when the snapshot's
mode is overworld, and run/obs.json had been written with a menu open, so
it went silent; the executor's objective-met-early rule then fired before
step one, twice, and the chain crossed the leg off on two runs that gained
nothing. Neither reader may treat a witness true at the start as the deed.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
ex_src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

snap = {"bag": {"POTION": 3, "HM_CUT": 1}, "mode": "menu", "flags": [], "badges": []}
ck("the snapshot's bag is read whatever its mode when the author asks",
   A.witness_holds_now({"lacks_item": ["FRESH_WATER"]}, snap, trust_bag=True) is True
   and A.witness_holds_now({"lacks_item": ["FRESH_WATER"]}, snap) is None)
plan = {"goal": "Give a FRESH WATER to the guard", "subgoals": [
    {"id": "buy", "goal_text": "Buy a FRESH WATER", "done_when": {"has_item": {"FRESH_WATER": 1}}},
    {"id": "give", "goal_text": "Give it to the guard", "done_when": {"lacks_item": ["FRESH_WATER"]}}]}
A._obs_now = lambda *a, **k: snap
p = A.witness_already_true_problems(plan)
ck("the author refuses the plan and says why lacks_item failed here",
   len(p) == 1 and "ALREADY HOLDS" in p[0] and "a thing GONE that you hold NOW" in p[0], p)
ck("the executor never declares the objective met before the first step",
   "if idx > 0 and idx < len(subgoals) - 1 and _fin" in ex_src
   and 'self.log("plan_objective_true_at_start", objective=_fin)' in ex_src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
