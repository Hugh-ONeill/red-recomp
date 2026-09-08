#!/usr/bin/env python3
"""A grind says how many balls it threw, and a field move interrupted on
its approach is sent once more.

Run 16 (2026-09-08), Route 16. Five Poke Balls went at a Doduo inside one
catch grind and the summary said only "NO POKé BALLS of any kind in the bag,
so nothing could be caught" — true at the end, read as "I never had any", and
the model went shopping instead of asking why five had missed. The same
attempt saw `field_move CUT` twice answer "the walk to the tile beside it did
not arrive" with the bush's neighbour plainly walkable: a wild fight had
started on the way. Source-anchored on the op runner (it needs the game).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = src.index('if op == "grind":\n                def _pexp(_o):')
g = src[i:i + 4000]
ck("the grind summary counts the balls the bag lost", "_thrown = sum(max(0, int(_b0.get(k) or 0) - int(_b1.get(k) or 0))" in g)
ck("...over every kind of ball", '"POKE_BALL", "GREAT_BALL", "ULTRA_BALL",' in g and '"SAFARI_BALL", "MASTER_BALL"' in g)
ck("...and says whether one landed", '"one of them landed" if _caught else "none of them landed"' in g)
ck("an empty bag AFTER throwing is said as after", "after that the bag held NO POKé BALLS" in g)
ck("an empty bag from the start keeps the old sentence", "NO POKé BALLS of any kind in the bag, so \"\n                              \"nothing could be caught" in g)

j = src.index('if op == "field_move" and step.get("x") is not None:')
f = src[j:j + 9000]
ck("a field move whose approach did not arrive is tried once more", 'if "did not arrive" in _d0:' in f and "field_move_retried" in f)
ck("...after fighting whatever interrupted it", 'while _o2 and _o2.get("mode") == "battle":' in f[f.index('if "did not arrive" in _d0:'):])
ck("...and the trace says it was the second try", "done on the second try" in f)
ck("...or that both tries failed", "(tried twice; a wild fight came between)" in f)
sys.exit(1 if fails else 0)
