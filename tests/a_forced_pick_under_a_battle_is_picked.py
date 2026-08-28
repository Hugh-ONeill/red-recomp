#!/usr/bin/env python3
"""The forced party pick after a faint is taken even though the menu over
the battle frame reports mode=battle.

battle_under_a_menu (2026-08-26) made a menu over a fight report the
fight, so "Use next POKeMON?" -> party menu arrives as mode=battle with
me None and PartyMenu on top. The replacement branch of _run_policy was
keyed on mode=ui and never ran: the policy took a turn, battle_move said
"not in battle", and Victory Road spun eight empty fights a round with
KABUTO and CHARIZARD both at 0 (2026-08-28).
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
party = [{"species": "KABUTO", "hp": 0, "max_hp": 65, "level": 30, "moves": []},
         {"species": "CHARIZARD", "hp": 0, "max_hp": 160, "level": 49, "moves": []},
         {"species": "DUGTRIO", "hp": 126, "max_hp": 126, "level": 51, "moves": [{"id": "SLASH"}]},
         {"species": "LAPRAS", "hp": 204, "max_hp": 204, "level": 49, "moves": [{"id": "SURF"}]}]
forced = {"mode": "battle", "party": party,
          "battle": {"kind": "trainer", "behind_a_menu": "PartyMenu", "me": None, "foe": None}}
sent = []
class Bridge:
    def send(self, op, **kw):
        sent.append((op, kw))
        if op == "pick_party":
            return {"result": {"ok": True}, "mode": "overworld", "party": party}
        return {"result": {"ok": False, "detail": "not in battle"}, "mode": "battle",
                "battle": forced["battle"], "party": party}
logged = []
E._run_policy(E.ACTIVE_SPEC, Bridge(), dict(forced), lambda k, **kw: logged.append((k, kw)), 10, intent="fight")
picks = [kw for op, kw in sent if op == "pick_party"]
ck("a PartyMenu over the battle with no active Pokemon is answered with a party pick", len(picks) == 1)
ck("...of a Pokemon that can still fight", bool(picks) and picks[0].get("slot") in (3, 4))
ck("...and no battle_move is sent into the menu", not any(op == "battle_move" for op, _ in sent))
src = (ROOT / "planner/executor.py").read_text()
ck("the branch keys on the menu over the fight, not only on mode=ui",
   'str(_bb.get("behind_a_menu") or "") == "PartyMenu"' in src and 'if obs.get("mode") != "battle" or _forced:' in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
