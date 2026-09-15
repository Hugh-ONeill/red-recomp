#!/usr/bin/env python3
"""A plan for going THROUGH a place must have a step that ends inside it.

"Travel through Rock Tunnel" was authored as a single subgoal,
exit_rock_tunnel ending on {"map": "ROUTE_11"}, because the model believes
the tunnel comes out there. The plan never entered the tunnel at all and
was satisfiable by walking east out of Vermilion; an earlier draft of the
same leg did the same thing with three steps and finished without going
near it (2026-09-14).

To go through a place you have to be in it, which needs no knowledge of
this game. Nothing here says where the place is, what it connects to, or
where it comes out: only that a plan for crossing somewhere should have a
step that ends there.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                        # noqa: E402

# RECORD-FREE, on purpose: these are claims about the SHAPE of a plan. What the
# record of the place's mouths adds (once both are walked, the step after the
# place cannot name a map neither reaches) is pinned in
# a_way_through_has_two_ends_and_the_record_can_show_both.py.
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def P(goal, *dws):
    return {"goal": goal, "subgoals": [{"id": f"s{i}", "done_when": d}
                                       for i, d in enumerate(dws)]}

p = A.through_a_place_problems(observed=None, plan=P("Travel through Rock Tunnel", {"map": "ROUTE_11"}))
ck("a through-plan with no step inside the place is refused", len(p) == 1, p)
ck("...naming the place", "THROUGH ROCK_TUNNEL" in (p[0] if p else ""))
ck("...and saying what it could finish without doing",
   "without the party ever being in it" in (p[0] if p else ""))
ck("...and asking for the one thing missing",
   "Give it a step that ends there." in (p[0] if p else ""))
ck("...and naming no route, no exit and no destination",
   not any(w in (p[0] if p else "") for w in ("ROUTE_10", "ROUTE_11", "Lavender", "south", "north")))

ck("a floor of the place counts as the place",
   A.through_a_place_problems(observed=None, plan=P("Travel through Rock Tunnel",
                                {"map": "ROCK_TUNNEL_B1F"}, {"map": "ROUTE_11"})) == [])
ck("...as does a new_part of it",
   A.through_a_place_problems(observed=None, plan=P("Traverse Mt Moon", {"new_part": "MT_MOON_B2F"})) == [])
ck("...and an area inside it",
   A.through_a_place_problems(observed=None, plan=P("Travel across Rock Tunnel",
                                {"area": "ROCK_TUNNEL_1F|14,2"})) == [])
ck("an objective with no through-word is not judged",
   A.through_a_place_problems(observed=None, plan=P("Reach Lavender Town", {"map": "ROUTE_11"})) == []
   and A.through_a_place_problems(observed=None, plan=P("Exit Rock Tunnel", {"map": "ROUTE_11"})) == [])
ck("a through-objective naming no map this game has is not judged",
   A.through_a_place_problems(observed=None, plan=P("Travel through the tall grass", {"map": "ROUTE_11"})) == [])
ck("a plan with no subgoals at all is left to the other checks",
   len(A.through_a_place_problems(observed=None, plan={"goal": "Travel through Rock Tunnel", "subgoals": []})) == 1)

src = (ROOT / "planner" / "author.py").read_text()
ck("the author's rounds ask it", "or through_a_place_problems(plan))" in src)
ck("the review asks it", "or through_a_place_problems(revised))" in src)
ck("the draws filter asks it", "or through_a_place_problems(p2))]" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
