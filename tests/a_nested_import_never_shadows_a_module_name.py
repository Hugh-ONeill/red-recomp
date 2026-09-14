#!/usr/bin/env python3
"""A function-local import must not shadow a module-level name.

`import re as _re` inside one branch of _run_traced made `_re` a LOCAL of
the whole 2,000-line function, so the module-level `_re` was unreachable
from every other line of it -- and the heard-lines code added at 20:01 on
2026-09-13 crashed with UnboundLocalError the first time any step produced
a spoken line. That is the first sweep of every attempt. 134 crashes in
five hours, leg 2 rewritten to v8 and the outline reworded around the
failures, before anyone saw a Poke Mart (user, 2026-09-14: "it went up to
v7 without seeing the mart, somethings definitely wrong with the harness
still"). The suite was green throughout: nothing drives that path.

Python's scoping makes the crash invisible at the line that binds and
fatal at every line that does not. So the rule is checked as a shape:
no import statement inside a function may bind a name the module already
binds at top level. Import at the top, or pick another name.
"""
from __future__ import annotations
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bad = []
n_files = 0
for f in sorted((ROOT / "planner").glob("*.py")) + sorted((ROOT / "tools").glob("*.py")):
    n_files += 1
    tree = ast.parse(f.read_text(), filename=str(f))
    top = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                top.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                if isinstance(tg, ast.Name):
                    top.add(tg.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(node.name)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    nm = (a.asname or a.name).split(".")[0]
                    if nm in top:
                        bad.append(f"{f.relative_to(ROOT)}:{node.lineno} in "
                                   f"{fn.name}(): binds {nm}, which the module "
                                   f"already binds at top level")

for b in bad:
    print("FAIL", b)
print(f"{'FAIL %d' % len(bad) if bad else 'ok'}: {n_files} files, no "
      f"function-local import shadows a module-level name" if not bad
      else f"FAIL {len(bad)}/{n_files} files")
sys.exit(1 if bad else 0)
