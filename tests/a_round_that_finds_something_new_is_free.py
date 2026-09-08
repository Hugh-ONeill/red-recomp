#!/usr/bin/env python3
"""An escalation round that finds something new does not spend the step's
budget, and moves the hard cap out by one.

Only a new MAP was free; a sweep that brought forty cells on screen, a first
press, a door never taken — all on the same map — were charged like a round
spent bumping a wall. Exploration burned the budget, the step failed, and the
re-run redid the steps before it (the gate's second floor again; run 16,
2026-09-08; user: "escalations are meant to spur on that behavior in the
first place so why force it to go back and redo things it already did"). A
find is free and moves the cap out by one, up to the step's own budget.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


ex = E.Executor.__new__(E.Executor)
ex.explored = {"A|0,0": {"north": {"to": "B|0,0"}}}
ex._tried_objs = {"A|0,0": {"SIGN"}}
o0 = {"map": {"id": "A", "seen": {"n": 40}}}
before = ex._news_snapshot(o0)
ck("a round that changed nothing is not news", ex._round_news(before, o0) == "")
ck("cells newly on screen are news", ex._round_news(before, {"map": {"id": "A", "seen": {"n": 76}}}) == "36 cell(s) newly on screen")
ex._tried_objs["A|0,0"].add("GIRL")
ck("a first press is news", "1 thing(s) pressed for the first time" in ex._round_news(before, o0))
ex.explored["A|0,0"]["7,5"] = {"to": "H|0,0"}
ck("a way taken for the first time is news", "1 way(s) taken for the first time" in ex._round_news(before, o0))
ck("cells on another map are not compared (the map change is its own rule)",
   "cell" not in ex._round_news(before, {"map": {"id": "B", "seen": {"n": 900}}}))

src = (ROOT / "planner" / "executor.py").read_text()
ck("the round loop snapshots the start of every round", "_news0 = self._news_snapshot(start)" in src)
ck("the cap moves out for news", "rnd < rounds * 3 + _fresh_bonus + _news_bonus" in src)
ck("a same-map round with news is not charged", 'if _news and _news_bonus < rounds:\n                    _news_bonus += 1' in src)
ck("...nor a circling round with news", "if visits[sig1[0]] >= 2 and _news_c and _news_bonus < rounds:" in src)
ck("the bonus is bounded by the step's own budget", src.count("_news_bonus < rounds") >= 2)
ck("the journal records it", '"round_for_news"' in src)
sys.exit(1 if fails else 0)
