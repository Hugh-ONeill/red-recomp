#!/usr/bin/env python3
"""A catch with no balls cannot happen, and the round says so.

User, 2026-08-29, watching: "its trying battle (catch policy) with no
pokeballs". grind(intent=catch) with an empty ball pocket ran the fights
and reported "earned 0 exp, fled"; the predicate-chosen catch policy did
the same silently. Now: an op with intent=catch and no ball of any kind
is NOT RUN, with the fact and where balls are sold; a catch policy chosen
from the predicate keeps fighting (it already fell through to moves) but
the grind note says nothing could be caught.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("any ball of any kind counts", E._balls_in({"bag": {"GREAT_BALL": 2}}) and E._balls_in({"bag": {"POKE_BALL": 1, "POTION": 3}}))
ck("none means none", not E._balls_in({"bag": {"POTION": 3, "POKE_BALL": 0}}) and not E._balls_in({}) and not E._balls_in({"bag": None}))
ck("grind intent=catch with no balls is NOT RUN, with the fact and the counter",
   'if _int == "catch" and not _balls_in(obs):' in src and "NOT RUN — the bag holds no " in src
   and "a POKé MART sells them" in src)
ck("a predicate-chosen catch policy with no balls is said in the grind note",
   'if name == "catch" and not _balls_in(obs):' in src and "self._no_balls_note = True" in src
   and "NO POKé BALLS of any kind in the bag, so " in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
