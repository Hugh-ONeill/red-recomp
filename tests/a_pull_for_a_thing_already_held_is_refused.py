#!/usr/bin/env python3
"""A pull is refused when what it "provides" is already in the bag or
known by the party, or when the leg names an HM this game does not have.

Victory Road, 2026-08-28: "Navigate the Victory Road" was pulled behind
"Retrieve the HM08 from the Victory Road warden", "provides 'HM08': the HM
for the move that allows boulder pushing" — with CHARIZARD knowing
STRENGTH and HM_STRENGTH in the bag on the state line the rung read, and
no HM08 in the game. The phantom leg then failed authoring twice.
"""
from __future__ import annotations
import sys, io, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

HELD = {"moves": {"STRENGTH": "CHARIZARD", "SURF": "LAPRAS", "CUT": "GLOOM"},
        "items": {"HM_STRENGTH", "HM_CUT", "HM_SURF", "POKE_FLUTE"}}
calls = []
def make_chat(pull, provides):
    def chat(msgs, model):
        sysm = msgs[0]["content"]
        calls.append(sysm[:30])
        if sysm.startswith("A Pokemon Red playthrough leg is STUCK"):
            return '{"why": "it needs it", "pull_forward": %d}' % pull
        if sysm.startswith("You have proposed moving"):
            return '{"why": "it hands it over", "provides": "%s"}' % provides
        return '{"why": "not yet", "done": false}'
    return chat

def run(ahead, pull, provides):
    calls.clear()
    A.brock_probe.chat = make_chat(pull, provides)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = A.check_blocker("Navigate the Victory Road", ahead, "start", "", "m",
                              leg=45, held=HELD)
    return out, err.getvalue()

ahead = [(46, "every party member is at least level 55"),
         (47, "Retrieve the HM08 from the Victory Road warden"),
         (48, "Reach the Indigo Plateau")]
out, err = run(ahead, 47, "HM08")
ck("a leg naming HM08 is refused before the confirm is asked",
   out is None and "there is no HM08 in this game" in err and "HM_STRENGTH" in err
   and not any(c.startswith("You have proposed") for c in calls))

ahead2 = [(46, "every party member is at least level 55"),
          (47, "Obtain the HM for Strength from the Safari Zone warden"),
          (48, "Reach the Indigo Plateau")]
out, err = run(ahead2, 47, "the Strength HM")
ck("a pull that provides a move the party knows is refused",
   out is None and "STRENGTH is a move CHARIZARD already knows" in err)
out, err = run(ahead2, 47, "HM_STRENGTH")
ck("...or an item id already in the bag", out is None and "HM_STRENGTH is in the bag already" in err)
out, err = run(ahead2, 47, "HM04 Strength")
ck("...or the HM named by its move", out is None and "already" in err)

ahead3 = [(46, "every party member is at least level 55"),
          (47, "Obtain the HM for Fly from the house on Route 16"),
          (48, "Reach the Indigo Plateau")]
out, err = run(ahead3, 47, "HM_FLY")
ck("a pull that provides a thing NOT held goes through", out == 47 and "pull provides 'HM_FLY'" in err)

ck("_phantom_item: TM29 is a thing, TM77 is not",
   A._phantom_item("Get TM29") == "" and "no TM77" in A._phantom_item("Get TM77"))
ck("_phantom_item: HM_STRENGTH (an id) is not a number", A._phantom_item("HM_STRENGTH") == "")
ck("_held_things reads a save shape",
   A._held_things({"party": [{"species": "GLOOM", "moves": [{"id": "CUT"}, "MEGA_DRAIN"]}],
                   "bag": {"HM_CUT": 1}}) == {"moves": {"CUT": "GLOOM", "MEGA_DRAIN": "GLOOM"}, "items": {"HM_CUT"}})

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
