#!/usr/bin/env python3
"""No local in the planner is read on a line before its first assignment.

Twice on 2026-09-08 a line I inserted read a name the function had not bound
yet: `self._disp_item` inside a staticmethod, and `_news_snapshot(obs)` at the
top of a loop whose body assigns `obs` later — each an exception on the
first round, each killing the attempt. Neither has a unit test that could
have caught it (both need the game). This is the cheap guard: for every
function, a name that is assigned somewhere in it and loaded on an earlier
line, and is not a parameter, global, module name or builtin, is a read
before its binding. Inner functions are scanned on their own; a nested def's
name counts as a binding. Static, over planner/*.py.
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = []


def scan(path: Path, src: str | None = None):
    src = path.read_text() if src is None else src
    tree = ast.parse(src)
    modnames = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            modnames.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            modnames |= {(a.asname or a.name).split(".")[0] for a in n.names}
    # module-level names: assignments directly in the module body (and in
    # its top-level try/if blocks) — never inside a function or class, or
    # every local in the file would pass as a module name
    def top_assigns(stmts):
        for st in stmts:
            if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = st.targets if isinstance(st, ast.Assign) else [st.target]
                for t in targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            modnames.add(x.id)
            elif isinstance(st, ast.Try):
                top_assigns(st.body)
                for h in st.handlers:
                    top_assigns(h.body)
                top_assigns(st.orelse)
                top_assigns(st.finalbody)
            elif isinstance(st, (ast.If, ast.With, ast.For, ast.While)):
                top_assigns(st.body)
                top_assigns(getattr(st, "orelse", []) or [])
    top_assigns(tree.body)
    hits = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
        if fn.args.vararg:
            params.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            params.add(fn.args.kwarg.arg)
        inner_ids = set()
        for f2 in ast.walk(fn):
            if f2 is not fn and isinstance(f2, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for x in ast.walk(f2):
                    inner_ids.add(id(x))
        declared, first_store, loads = set(), {}, {}
        # a comprehension's loop variable binds for the whole expression,
        # however the lines fall ([f(x)\n for x in xs] reads x "before" it)
        comp_ids = set()
        for comp in ast.walk(fn):
            if isinstance(comp, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                targets = {t.id for g in comp.generators for t in ast.walk(g.target) if isinstance(t, ast.Name)}
                for x in ast.walk(comp):
                    if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id in targets:
                        comp_ids.add(id(x))

        def store(name, line):
            first_store[name] = min(first_store.get(name, 10 ** 9), line)

        for node in ast.walk(fn):
            if id(node) in inner_ids and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                declared |= set(node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
                store(node.name, node.lineno)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    store(node.id, node.lineno)
                elif isinstance(node.ctx, ast.Load) and id(node) not in comp_ids:
                    loads.setdefault(node.id, []).append(node.lineno)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                store(node.name, node.lineno)
        for name, lines in loads.items():
            if name in params or name in declared or name in modnames or name not in first_store:
                continue
            early = [l for l in lines if l < first_store[name]]
            if early:
                hits.append(f"{path.name}:{early[0]} {fn.name}(): '{name}' read before its first binding at {first_store[name]}")
    return hits


# the scan must see the bug class it exists for
_probe = scan(Path("probe.py"), "def f(xs):\n    while xs:\n        n0 = g(obs)\n        obs = xs.pop()\n    return [y\n            for y in xs]\n")
print(("ok   " if len(_probe) == 1 and "'obs' read before" in _probe[0] else "FAIL ")
      + f"the scan catches a loop-head read of a name the body binds later, and not a comprehension ({_probe})")
if not (len(_probe) == 1 and "'obs' read before" in _probe[0]):
    fails.append("probe")
for p in sorted((ROOT / "planner").glob("*.py")):
    for h in scan(p):
        print("FAIL " + h)
        fails.append(h)
print(("ok   " if not fails else "FAIL ") + f"no local read before its binding in planner/*.py ({len(fails)} found)")
sys.exit(1 if fails else 0)
