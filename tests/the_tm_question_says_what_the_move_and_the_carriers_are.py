#!/usr/bin/env python3
"""The TM question states the move's type and power and each ABLE
Pokemon's types and moves as the summary screen shows them.

Dig went to Charmeleon as "valuable STAB" and Body Slam to Pikachu as "a
powerful STAB move for Pikachu": good teaches, wrong reasons, neither
move is its carrier's type (2026-09-14, user: "its wrong about STAB
neither DIG nor BODYSLAM are stab moves for the mons taught to"). The
question named the move and the species and nothing about the type of
either, so the model filled the gap from memory. Facts only: what a type
match is worth stays the model's to weigh, and the question recommends
nothing.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

OBS = {"machines": {"TM_DIG": {"move": "DIG", "type": "GROUND", "power": 100,
                               "able": ["CHARMELEON"], "not_able": ["PIKACHU", "NIDORINO"]},
                    "HM_CUT": {"move": "CUT", "type": "NORMAL", "power": 50,
                               "able": ["CHARMELEON", "FARFETCHD"], "not_able": ["PIKACHU", "NIDORINO"]}},
       "party": [{"species": "PIKACHU", "level": 20, "types": ["ELECTRIC"],
                  "moves": [{"id": "THUNDERSHOCK", "type": "ELECTRIC", "power": 40},
                            {"id": "GROWL", "type": "NORMAL", "power": 0},
                            {"id": "THUNDER_WAVE", "type": "ELECTRIC", "power": 0},
                            {"id": "QUICK_ATTACK", "type": "NORMAL", "power": 40}]},
                 {"species": "CHARMELEON", "level": 29, "types": ["FIRE"],
                  "moves": [{"id": "RAGE", "type": "NORMAL", "power": 20},
                            {"id": "EMBER", "type": "FIRE", "power": 40},
                            {"id": "LEER", "type": "NORMAL", "power": 0}]},
                 {"species": "NIDORINO", "level": 19, "types": ["POISON"], "moves": ["LEER", "TACKLE"]},
                 {"species": "FARFETCHD", "level": 10, "types": ["NORMAL", "FLYING"],
                  "moves": [{"id": "PECK", "type": "FLYING", "power": 35}]}]}
o = types.SimpleNamespace(_disp_item=lambda it: it)
q = types.MethodType(E.Executor._teach_question, o)
SG = {"id": "travel_to_route_5", "goal_text": "Walk north to Route 5."}

who = [(2, "CHARMELEON", ["RAGE", "EMBER", "LEER"])]
t = q(OBS, "TM_DIG", "DIG", who, SG)
ck("the machine's move carries its type and power", "teaches DIG (GROUND, power 100)." in t, t)
ck("the carrier carries its type", "slot 2: CHARMELEON (FIRE) L29" in t, t)
ck("...and each move it knows carries its type and power",
   "EMBER (FIRE, power 40)" in t and "RAGE (NORMAL, power 20)" in t, t)
ck("a move with no power shows its type alone", "LEER (NORMAL)" in t, t)
ck("a TM is said to be used up", "A TM IS USED UP" in t)
ck("the question recommends nothing and names no verdict",
   not any(w in t.lower() for w in ("stab", "should", "recommend", "better to")), t)
ck("...and still says no round is spent", "No round is spent either way" in t)

who2 = [(2, "CHARMELEON", ["RAGE", "EMBER", "LEER"]), (4, "FARFETCHD", ["PECK"])]
t2 = q(OBS, "HM_CUT", "CUT", who2, SG)
ck("two types are shown both", "FARFETCHD (NORMAL/FLYING) L10" in t2, t2)
ck("an HM is said to be kept", "An HM is NOT used up" in t2)
ck("the machine's move: CUT (NORMAL, power 50)", "teaches CUT (NORMAL, power 50)." in t2)

# a party whose moves are bare names (older observations) still reads
who3 = [(3, "NIDORINO", ["LEER", "TACKLE"])]
t3 = q(OBS, "TM_DIG", "DIG", who3, SG)
ck("bare move names are shown as they are", "NIDORINO (POISON) L19 — knows LEER, TACKLE" in t3, t3)
# a ledger without type/power (older shim) still reads
t4 = q({"machines": {"TM_X": {"move": "MEGA_PUNCH"}}, "party": OBS["party"]}, "TM_X", "MEGA_PUNCH", who, SG)
ck("a ledger without types falls back to the bare move", "teaches MEGA_PUNCH." in t4, t4)

src = (ROOT / "planner" / "executor.py").read_text()
ck("the TM question is built from this", "user = self._teach_question(obs, item, move, who, sg)" in src)
sh = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim's machines ledger carries the move's type and power",
   "type = mdef and mdef.type, power = mdef and mdef.power" in sh)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:500].replace("\n", " | "))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
