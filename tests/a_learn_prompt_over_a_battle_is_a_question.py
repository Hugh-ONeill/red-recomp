#!/usr/bin/env python3
"""A level-up move prompt over a battle is reported as a question.

At the end of a fight a Pokemon that gained a level can be "trying to
learn" a move; the yes/no and the forget list sit on the stack ABOVE the
battle frame, which has not been popped yet. battle_frame() found that
frame, observe() said mode=battle, the executor ran its battle policy
against "foe None", battle_move failed "not in battle" eight times a
round, and nobody answered "Abandon learning MIST?" until the user did
(2026-08-28, a benched LAPRAS levelling on shared exp). A learn anywhere
on the stack is the model's choice to make: it is reported as ui, and
the battle loop leaves at once on "not in battle".
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
lua = (ROOT / "harness/shim.lua").read_text()
ck("the shim can see a learn anywhere on the stack", "local function learn_on_stack(G)" in lua)
h = lua[lua.index("local function learn_on_stack(G)"):][:600]
ck("...by newMoveId on any frame", "s.newMoveId ~= nil" in h)
ck("...or a MoveLearnMenu on top", 'screenId == "MoveLearnMenu"' in h)
ck("it is declared before observe uses it",
   lua.index("local function learn_on_stack(G)") < lua.index("elseif battle_frame(G) and not learn_on_stack(G) then"))
ck("observe reports a battle only when no learn is on the stack",
   "elseif battle_frame(G) and not learn_on_stack(G) then" in lua)
i = lua.index("elseif battle_frame(G) and not learn_on_stack(G) then")
ck("...so a learn prompt falls through to the ui branch, where is_choice and the learner are read",
   "elseif top then" in lua[i:i + 900] and 'top.screenId == "MoveLearnMenu" and top.mon' in lua[i:i + 3600])
src = (ROOT / "planner/executor.py").read_text()
j = src.index('log("battle_move_failed"')
ck("the battle loop leaves at once on 'not in battle'",
   '"not in battle" in str(r.get("detail") or "").lower()' in src[j:j + 800]
   and 'log("battle_loop_left"' in src[j:j + 800])
ck("...before the eight-failure cap", src[j:j + 800].index("battle_loop_left") < src[j:j + 800].index("op_fails >= 8"))
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
