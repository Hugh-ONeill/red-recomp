#!/usr/bin/env python3
"""A bag that changes during a round is reported, not crashed on.

Run 16 (2026-09-08, Route 12 gate): the run took TM39 from the man
upstairs, the goods line went to say so, and the attempt died instead:

    File "planner/executor.py", line 13244, in _goods_delta
        parts.append(f"{self._disp_item(k)} {d:+d} (now {b1.get(k) or 0})")
    NameError: name 'self' is not defined

_goods_delta had been a @staticmethod since the day it was written to
make a shop bill legible; the TM-by-number change made it read the run's
own record of who handed an item over (self._item_from) and nobody gave it
a self. Every bag change inside an escalation round from then on was a
crash, and the chain read each as a failed attempt and re-authored the leg.

Two checks: the method reports a TM gained mid-round by its number, on a
bare instance; and no method of the executor that is declared without a
self reads one. Synthetic only.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ex = E.Executor.__new__(E.Executor)
pre = {"bag": {"POTION": 3}, "money": 11798}
post = {"bag": {"POTION": 3, "TM_SWIFT": 1}, "money": 11798}
got = ex._goods_delta(pre, post)
ck("a TM gained mid-round is reported by number", "TM39 +1" in got)
ex._item_from = {"TM_SWIFT": "ROUTE12GATE2F_MAN"}
got = ex._goods_delta(pre, post)
ck("a gift TM is reported by the move its giver named", "TM_SWIFT +1" in got)

tree = ast.parse((ROOT / "planner" / "executor.py").read_text())
bad = []
for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decos = {getattr(d, "id", None) for d in node.decorator_list}
        args = [a.arg for a in node.args.args]
        selfless = "staticmethod" in decos or not args or args[0] != "self"
        if selfless and "classmethod" not in decos:
            names = {n.id for n in ast.walk(node)
                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            if "self" in names:
                bad.append(f"{cls.name}.{node.name}:{node.lineno}")
ck("no selfless method of the executor reads self" + (f" ({', '.join(bad)})" if bad else ""), not bad)

sys.exit(1 if fails else 0)
