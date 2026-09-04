#!/usr/bin/env python3
"""A person on the doorstep is a way that turned you back (2026-09-04).

Four Saffron doors — the Gym, Silph Co, Copycat's, the Pidgey house — each have
a Rocket posted one tile below the door. use_warp said "somebody is standing by
it ... interact with them to hear why", the run did ("Get out of the way!"),
and nothing wrote the door down: WAYS THAT TURNED YOU BACK listed fences, seams
and the ghost door, the page went on offering all four as plain untried ways,
and the run circled them for a whole step (user: "its just going all around
saf mostly fruitlessly"). Now a poster who does not move once spoken to is a
blocker row in their own words; a wanderer is not. A gate guard's script that
interrupts a CROSS is recorded too (the thirsty guard had no row either).

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "SAFFRON_CITY|12,0"
def fresh():
    e = object.__new__(E.Executor)
    e.blockers = {}; e._outcomes = {}; e._cur_target = "flag:EVENT_RESCUED_MR_FUJI"
    e._where = lambda o: HERE
    e.hints = {HERE: ["SAFFRONCITY_ROCKET7: With SILPH under control, we can exploit POKéMON around the world!",
                      "SAFFRONCITY_ROCKET3: Get out of the way!"]}
    e.touched = {HERE: ["SAFFRONCITY_ROCKET3", "SAFFRONCITY_ROCKET7"]}
    e.log = lambda *a, **k: None
    return e

NOTE = ("use_warp(x=34,y=3): FAILED — couldn't reach the warp tile — somebody is standing by it: "
        "SAFFRONCITY_ROCKET3 at (34,4). People who stand in front of doors in this game usually say why; "
        "interact with them to hear it.")
e = fresh()
e._record_outcome({"map": {"id": "SAFFRON_CITY"}}, "use_warp", {"x": 34, "y": 3}, NOTE)
b = e.blockers.get(f"{HERE}|34,3")
ck("the held door is a blocker row", b is not None and b.get("kind") == "door", e.blockers)
ck("...naming who holds it and where they stand", b and "SAFFRONCITY_ROCKET3 stands on its doorstep at (34,4)" in b["what"], b)
ck("...in their own words", b and 'said: "Get out of the way!"' in b["what"], b)
ck("...and that talking did not move them", b and "spoken to, and did not move" in b["what"], b)
e._record_outcome({}, "use_warp", {"x": 34, "y": 3}, NOTE)
ck("a second refusal bumps the count", e.blockers[f"{HERE}|34,3"]["n"] == 2)
e._record_outcome({}, "use_warp", {"x": 34, "y": 3}, "use_warp(x=34,y=3): ok (map->SAFFRON_GYM, moved, warped)")
ck("...and the door opening clears it", e.blockers[f"{HERE}|34,3"].get("cleared") is True)

e2 = fresh()
NOTE8 = NOTE.replace("SAFFRONCITY_ROCKET3 at (34,4)", "SAFFRONCITY_ROCKET8 at (18,22)").replace("x=34,y=3", "x=18,y=21")
e2._record_outcome({}, "use_warp", {"x": 18, "y": 21}, NOTE8)
b8 = e2.blockers.get(f"{HERE}|18,21")
ck("a poster not yet spoken to says so, with no words", b8 and "not yet spoken to" in b8["what"] and "said:" not in b8["what"], b8)

e3 = fresh()
WANDER = ("use_warp(x=7,y=5): FAILED — couldn't reach the warp tile — somebody is standing by it: "
          "SAFFRONCITY_ROCKER at (7,6) (who wanders). Someone marked (who wanders) walks a patch of ground and is not posted there")
e3._record_outcome({}, "use_warp", {"x": 7, "y": 5}, WANDER)
ck("a wanderer makes no row", not e3.blockers)

e4 = fresh()
e4._record_outcome({}, "cross", {"dir": "east"},
                   'cross(dir=east): FAILED — couldn\'t reach east edge (interrupted (battle or script)) — it said: "Gee, I\'m thirsty, though! Oh wait there, the road\'s closed."')
b4 = e4.blockers.get(f"{HERE}|east")
ck("a guard's script that interrupts a cross is a seam row in the guard's words",
   b4 and b4.get("kind") == "seam" and "a script turned you back" in b4["what"] and "thirsty" in b4["what"], b4)
e5 = object.__new__(E.Executor); e5.blockers = {}; e5._outcomes = {}; e5._cur_target = ""; e5._where = lambda o: HERE; e5.log = lambda *a, **k: None
e5._record_outcome({}, "use_warp", {"x": 34, "y": 3}, NOTE)
ck("an executor from before hints/touched existed does not die of it", f"{HERE}|34,3" in e5.blockers)

bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
