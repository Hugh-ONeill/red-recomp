#!/usr/bin/env python3
"""An attempt that crashes saves the game before it dies.

The memory file is written as the run goes; the game is saved only when an
attempt ends. An exception inside a round used to end the process between
the two: run 16 (2026-09-08) died in _goods_delta upstairs in the Route 12
gate, TM39 in hand after a 25-minute walk from Celadon, and the next attempt
booted the game from the leg's opening save — back in Celadon, TM39 gone —
while the memory still said the girl upstairs had been pressed and had handed
it over. Same remedy a stop signal gets between ops: save the game, take the
checkpoint marked incomplete, then die.

Source-anchored, like the other tests of main(): main() needs the game.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


tree = ast.parse(SRC)
main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
handlers = []
for node in ast.walk(main_fn):
    if isinstance(node, ast.Try):
        body_src = ast.get_source_segment(SRC, node)
        if "ex.run_plan(plan)" in ast.get_source_segment(SRC, node.body[0]) if node.body else False:
            handlers.append(node)
ck("run_plan is called inside a try in main()", bool(handlers))
if handlers:
    h = handlers[0]
    hs = "\n".join(ast.get_source_segment(SRC, x) for x in h.handlers)
    ck("the handler saves the game", '_send_safe("save_game")' in hs)
    ck("the handler takes a checkpoint marked incomplete",
       "checkpoint_leg(plan_path, complete=False" in hs)
    ck("the handler writes the crash to the journal", '"attempt_crashed"' in hs)
    ck("the crash still ends the attempt (re-raised)",
       any(isinstance(x, ast.Raise) and x.exc is None
           for hh in h.handlers for x in ast.walk(hh)))
    ck("only ordinary exceptions are caught (a stop signal's SystemExit passes through)",
       all(getattr(hh.type, "id", None) == "Exception" for hh in h.handlers))

sys.exit(1 if fails else 0)
