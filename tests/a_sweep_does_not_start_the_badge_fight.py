#!/usr/bin/env python3
"""A sweep tries things to see what they say. A gym leader cannot be tried.

Run 17, Cerulean Gym (2026-09-13). Three rounds running the plan said it
was leaving to catch a Grass type for Misty. Round 4's macro was
walk_to(30,19) then cross north — the city's north edge, toward Route 24,
exactly what it had written. The cross was refused ("CERULEAN_GYM has no
north edge — it is indoors"), and the sweep that followed pressed A on
every reachable object in the room. One of them was CERULEANGYM_MISTY.
Third blackout, money halved again, and nothing the model wrote asked for
that fight (user: "said this then fought misty again").

A press is a free look at a sign or a shopkeeper. At a leader it is the
badge fight, the one press in the building that cannot be taken back. The
gym's OTHER trainers stay in the sweep: they are the road to the leader,
they are meant to be fought, and the model can still press the leader
itself the moment it means to.

THE FIRST ATTEMPT AT THIS WAS WRONG and the way it was wrong is the
lesson. It told staff from leader by the SUFFIX of the object name, on the
theory that a class is a kind of trainer and a leader is a person. Checked
against every gym's real objects it called CELADONGYM_BEAUTY1,
CINNABARGYM_SUPER_NERD3, SAFFRONGYM_CHANNELER1 and FUCHSIAGYM_ROCKER2
leaders as well — numbered staff defeat any class list written by hand.
The game has a gym table with the leaders' names in it. Ask it.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))
L = E.Executor._is_gym_leader

# ---- every gym's real objects, from gen1recomp's own map data ----------
REAL = {
 "CERULEAN_GYM": (["CERULEANGYM_MISTY"],
                  ["CERULEANGYM_SWIMMER", "CERULEANGYM_COOLTRAINER_F",
                   "CERULEANGYM_GYM_GUIDE"]),
 "PEWTER_GYM": (["PEWTERGYM_BROCK"],
                ["PEWTERGYM_JR_TRAINER_M", "PEWTERGYM_GYM_GUIDE"]),
 "CELADON_GYM": (["CELADONGYM_ERIKA"],
                 ["CELADONGYM_BEAUTY1", "CELADONGYM_BEAUTY2",
                  "CELADONGYM_BEAUTY3", "CELADONGYM_COOLTRAINER_F1",
                  "CELADONGYM_COOLTRAINER_F4"]),
 "CINNABAR_GYM": (["CINNABARGYM_BLAINE"],
                  ["CINNABARGYM_SUPER_NERD1", "CINNABARGYM_SUPER_NERD3",
                   "CINNABARGYM_SUPER_NERD7"]),
 "FUCHSIA_GYM": (["FUCHSIAGYM_KOGA"],
                 ["FUCHSIAGYM_ROCKER1", "FUCHSIAGYM_ROCKER2",
                  "FUCHSIAGYM_ROCKER6"]),
 "SAFFRON_GYM": (["SAFFRONGYM_SABRINA"],
                 ["SAFFRONGYM_CHANNELER1", "SAFFRONGYM_CHANNELER3",
                  "SAFFRONGYM_YOUNGSTER1", "SAFFRONGYM_YOUNGSTER4"]),
 "VERMILION_GYM": (["VERMILIONGYM_LT_SURGE"],
                   ["VERMILIONGYM_GENTLEMAN", "VERMILIONGYM_ROCKER"]),
 "VIRIDIAN_GYM": (["VIRIDIANGYM_GIOVANNI"],
                  ["VIRIDIANGYM_COOLTRAINER_M1", "VIRIDIANGYM_HIKER1",
                   "VIRIDIANGYM_HIKER3", "VIRIDIANGYM_ROCKER2",
                   "VIRIDIANGYM_REVIVE"]),
}
for gym, (leaders, staff) in REAL.items():
    ck(f"{gym}'s leader is known", all(L(n, gym) for n in leaders))
    ck(f"...and none of its {len(staff)} staff are",
       not any(L(n, gym) for n in staff))

ck("every gym in the badge list has a leader named",
   set(E.GYM_LEADERS) == set(E.BADGE_GYMS.values()))
ck("a leader is only a leader in their OWN gym",
   not L("CERULEANGYM_MISTY", "PEWTER_GYM"))
ck("nothing outside a gym is a leader",
   not L("OAKSLAB_OAK1", "OAKS_LAB")
   and not L("BILLSHOUSE_BILL", "BILLS_HOUSE"))
ck("a name that merely starts the same is not one",
   not L("CERULEANGYM_MISTYS_FRIEND", "CERULEAN_GYM"))

# ---- the sweep leaves that one alone, and says so ----------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the sweep filters the leader out of what it presses",
   "_skipped_boss.append(_n)" in SRC and "loose = _kept" in SRC)
ck("...only inside a gym", "_gym_here in _leaders" in SRC)
ck("...and only one it has not already beaten", "_n not in touched" in SRC)
ck("it says what it did not press, and why",
   "the sweep did NOT press" in SRC and "starts the badge" in SRC)
ck("...and names the op to send when the fight IS wanted",
   'Send ' in SRC and '{{\\"op\\":\\"interact\\",\\"name\\":' in SRC)
ck("the gym's other trainers are still swept",
   "_kept.append(_n)" in SRC)
ck("the leader table comes from the engine's gym data, not a guess",
   "gen1recomp data/scripts/gyms.lua" in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
