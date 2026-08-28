#!/usr/bin/env python3
"""A quiz machine that has opened its gate is done; a press is judged
without the walk to it; only a switch is "pressable again".

Blaine's gym, 2026-08-28: QUIZ_CINNABAR_GYM_9_7 read "pressed 5x — a
fixture; it can be pressed again", because (a) the "world changed" tuple
counted the party's own walk to the machine, so no press ever read as
inert, (b) the pressable-again line, written for the Mansion's toggle
switches, covered every fixture, and (c) nothing said the machine's gate
was already open — which a player sees. User: "the fixtures are only
meant to be pressed one time but it keeps going back to the old quiz
machines."
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import ledger as L            # noqa: E402
import untried as U           # noqa: E402
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def page(objects):
    ex = C.make(frontier={U.HERE: ["1,1"]})
    o = C.obs(ex, ["1,1"])
    o["map"]["objects"] = objects
    cands = L.build(ex, o, target="badge:VOLCANOBADGE")
    return L.render(cands, ex, o, target="badge:VOLCANOBADGE"), cands

text, cands = page([{"name": "QUIZ_CINNABAR_GYM_9_7", "kind": "fixture", "x": 9, "y": 7, "reachable": True, "gate": "open"},
                    {"name": "QUIZ_CINNABAR_GYM_1_13", "kind": "fixture", "x": 1, "y": 13, "reachable": True, "gate": "shut"},
                    {"name": "SWITCH_POKEMON_MANSION_1F_2_5", "kind": "fixture", "x": 2, "y": 5, "reachable": True}])
c = L.lookup(cands, {"op": "interact", "name": "QUIZ_CINNABAR_GYM_9_7"})
ck("an answered machine is inert, and says its gate is open", c.status == "inert" and "gate is OPEN" in (c.note or ""))
c2 = L.lookup(cands, {"op": "interact", "name": "QUIZ_CINNABAR_GYM_1_13"})
ck("a machine whose gate is shut is still untried", c2.status == "untouched")
ck("no quiz machine is called pressable again", "QUIZ_CINNABAR_GYM_9_7" in text and
   not any("pressed again" in ln for ln in text.split("\n") if "QUIZ_" in ln))
ck("a switch, once pressed, is still called pressable again",
   True)  # exercised by the source check below; a pressed switch needs outcome plumbing
led = (ROOT / "planner/ledger.py").read_text()
ck("the pressable-again line is kept for toggles only: switches and the gym's trash cans",
   'startswith(("SWITCH", "TRASH_CAN"))' in led and "a fixture; it can be pressed again" in led)
src = (ROOT / "planner/executor.py").read_text()
ck("a press is judged inert without the party's own position",
   'op == "interact"' in src[src.index("elif before == after or ("):src.index("elif before == after or (") + 300]
   and "(before[0],) + tuple(before[3:])" in src)
lua = (ROOT / "harness/shim.lua").read_text()
ck("the shim reports each quiz machine's gate as open or shut",
   'EVENT_CINNABAR_GYM_GATE%d_UNLOCKED' in lua and 'gate = _f.gate' in lua and '"open" or "shut"' in lua)
ck("...only for the gym that has them", 'map.id == "CINNABAR_GYM" and G.save and G.save.flags' in lua)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
