#!/usr/bin/env python3
"""A grind that fled its encounters says how many it met and why it fled.

2026-08-29, user watching: grind(intent=train) on Route 1 with the lead at
5/27hp met nine wilds, fled every one on the low-HP guard, and the round
read "earned 0 exp: ran but had NO visible effect (nothing changed) — fled";
the model concluded "no encounters". The low-HP reason existed but was
gated on the step's PREDICATE policy (traversal for a flag step), not the
policy actually running (the op's intent=train). Now the effective policy
decides, the encounter count is on the note, and "nothing changed" is
never said about a round that met wilds.
"""
import sys
from pathlib import Path
ex = (Path(__file__).resolve().parents[1] / "planner" / "executor.py").read_text()
checks = [
    ("the low-HP flee reason keys on the policy that actually runs, intent included",
     '_eff = choose_battle_policy(sg)[0]' in ex and 'and _eff != "traversal"):' in ex),
    ("encounters this op are counted from battle_start",
     'self._op_battles = getattr(self, "_op_battles", 0) + 1' in ex
     and "self._op_battles = 0        # wild encounters this op met" in ex),
    ("the grind note says how many wilds it met", 'note += f" over {_nb} wild encounter(s)"' in ex),
    ("a round that met wilds is never 'nothing changed'",
     'wild encounter(s) met and ' in ex and '_nb0 = getattr(self, "_op_battles", 0)' in ex),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
