#!/usr/bin/env python3
"""Explore never presses the PC, the nurse or the gym's leader on its own.

A sweep presses things to see what they say, and most things can be
untried. Three cannot, or are decisions rather than things: the PC (a
menu; what to do in it is the model's -- it went to one itself for the
Potion before the Brock rematch), the Center's nurse (the heal, the
model's call by rule since 2026-09-14), and the gym's leader (a badge
fight). The room sweep has skipped leaders since 2026-09-13; explore's own
press lists, local and remote, never skipped anything of the kind, and
explore had just walked the party into the Cerulean Center for its "4
thing(s) never pressed" (user, 2026-09-14: "explore harness shouldnt force
the bot to click the pc, similar issue with the gym leaders i think").

One predicate, three sites. The ledger still lists all three; the model
presses them when it means to.
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

o = types.SimpleNamespace(_is_gym_leader=E.Executor._is_gym_leader)
held = types.MethodType(E.Executor._not_for_explore_to_press, o)

ck("the PC is held back, anywhere", held("PC", "fixture", "PEWTER_POKECENTER|2,3")
   and held("PC", "fixture", "REDS_HOUSE_2F|1,1"))
ck("...with the reason that it is a menu and the model's",
   "menu" in held("PC", "fixture", "PEWTER_POKECENTER|2,3"))
ck("the nurse is held back", held("CERULEANPOKECENTER_NURSE", "npc", "CERULEAN_POKECENTER|0,3"))
ck("...as the heal decision", "heal" in held("MTMOONPOKECENTER_NURSE", "npc", "MT_MOON_POKECENTER|0,3"))
ck("this gym's leader is held back", held("CERULEANGYM_MISTY", "trainer", "CERULEAN_GYM|1,1"))
ck("...as a badge fight", "LEADER" in held("PEWTERGYM_BROCK", "trainer", "PEWTER_GYM|1,1"))
ck("the gym's other trainers are not", held("CERULEANGYM_JR_TRAINER_F", "trainer", "CERULEAN_GYM|1,1") == "")
ck("a person in the Center who is not the nurse is not",
   held("CERULEANPOKECENTER_GENTLEMAN", "npc", "CERULEAN_POKECENTER|0,3") == "")
ck("a sign, an item, a clerk: pressable as ever",
   held("TEXT_ROUTE4_MT_MOON_SIGN", "sign", "ROUTE_4|4,4") == ""
   and held("ITEM_MT_MOON_1F_2_20", "item", "MT_MOON_1F|3,2") == ""
   and held("VIRIDIANMART_CLERK", "npc", "VIRIDIAN_MART|0,2") == "")
ck("the leader test is the gym table's, not a name shape: a leader's name in another map is nothing",
   held("CERULEANGYM_MISTY", "trainer", "ROUTE_24|1,1") == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("explore's local press list asks it",
   "and not self._not_for_explore_to_press(\n                             c.key, c.kind, self._where(obs)))" in src)
ck("explore's remote press list asks it",
   "and not self._not_for_explore_to_press(\n                              c.key, c.kind, region))" in src)
ck("the room sweep asks it",
   "if not self._not_for_explore_to_press(\n                             n, kinds.get(n), here_s)]" in src)
ck("the room sweep still names the leader it skipped, so the model knows the fight is there",
    "_skipped_boss.append(_n)" in src and "that is this gym's " in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
