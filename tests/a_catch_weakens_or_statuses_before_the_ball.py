#!/usr/bin/env python3
"""The catch policy puts a status on the foe or weakens it before the ball,
and throws at full health only when nothing safe is left.

Run 16 (2026-09-08), Route 16, a Flying type wanted for HM02: the policy
threw five Poke Balls at a Doduo at 100% HP — with a target named it cleared
every weakening move ("a wasted ball is recoverable and a corpse is not") —
none landed, and the Spearows after it met an empty bag (user: "i would be
suprised if it weakened before throwing"). The corpse worry stands: only a
move whose damage has been SEEN and is under half the foe's current HP may
weaken it; a sleep or paralysis move comes first when the foe has no status;
low enough, or nothing safe, the ball goes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import battle_policy as P   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


SPEC = {"catch": {"ball": "POKE_BALL", "max_balls": 5, "throw_at_hp_frac": 0.7}}
TACKLE = {"id": "TACKLE", "index": 1, "pp": 35, "power": 35, "type": "NORMAL", "category": "physical", "accuracy": 95}
ACID = {"id": "ACID", "index": 1, "pp": 30, "power": 40, "type": "POISON", "category": "special", "accuracy": 100}
SPORE = {"id": "STUN_SPORE", "index": 2, "pp": 30, "power": 0, "type": "GRASS", "category": "status", "accuracy": 75}


def obs(me, moves, foe_hp=49, foe_status=None):
    return {"battle": {"kind": "wild",
                       "me": {"species": me, "level": 35, "hp": 107, "max_hp": 107, "types": ["POISON"], "moves": moves},
                       "foe": {"species": "DODUO", "level": 20, "hp": foe_hp, "max_hp": 49,
                               "types": ["NORMAL", "FLYING"], "status": foe_status}},
            "bag": {"POKE_BALL": 5}, "party": []}


WANT = {"intent": "catch", "want": {"types": {"FLYING"}}}

r = P.choose(obs("NIDORINA", [TACKLE]), SPEC, dict(WANT))
ck("no status move, damage never seen: the ball goes, and says why",
   r["op"] == "throw_ball" and "nothing safe" in r["_why"], r)

seen = {P.journal_key("ACID", "DODUO", 35): [15]}
ctx = dict(WANT, journal=seen)
r = P.choose(obs("GLOOM", [ACID, SPORE]), SPEC, ctx)
ck("a paralysis move comes first on a foe with no status", r["op"] == "battle_move" and r["index"] == 2, r)
r = P.choose(obs("GLOOM", [ACID, SPORE], foe_status="PAR"), SPEC, ctx)
ck("...then a move seen to do under half its HP weakens it", r["op"] == "battle_move" and r["index"] == 1, r)
r = P.choose(obs("GLOOM", [ACID, SPORE], foe_hp=18, foe_status="PAR"), SPEC, ctx)
ck("low enough (under 40% with a target named), the ball goes", r["op"] == "throw_ball", r)

heavy = {P.journal_key("ACID", "DODUO", 35): [30]}
r = P.choose(obs("GLOOM", [ACID], foe_status="PAR"), SPEC, dict(WANT, journal=heavy))
ck("a move seen to take more than half its HP is not trusted near the one you want",
   r["op"] == "throw_ball", r)

r = P.choose(obs("GLOOM", [ACID]), SPEC, {"intent": "catch", "journal": seen})
ck("with no target named the old 70% threshold still weakens first", r["op"] == "battle_move", r)

sys.exit(1 if fails else 0)
