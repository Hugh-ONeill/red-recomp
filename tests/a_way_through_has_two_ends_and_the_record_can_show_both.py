#!/usr/bin/env python3
"""A through-objective is settled by the record either way: one mouth used
refuses a "done", two mouths used IS the done, and a plan written after
both mouths are known cannot come out onto a map neither of them reaches.

"Travel through Rock Tunnel", run 17 (2026-09-14): walked in from
ROUTE_10|0,4, out by another door onto ROUTE_10|14,52, on into Lavender
Town — and the leg's last step read {"map": "ROUTE_11"}, from the belief
that the tunnel comes out there. Standing on the far side it wrote "my
goal is to reach Route 11 by exiting the Rock Tunnel" and walked back in.
The refusal from earlier that day (_not_through_yet) had no counterpart:
nothing recognized a true through. Same definition, both halves now: a
way through has two ends. Nothing here says where a place comes out.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def record(**kw):
    d = {"explored": {}, "visits": {}}
    d.update(kw)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, f); f.close()
    return f.name

TWO = record(explored={
    "ROUTE_10|0,4": {"8,17": {"to": "ROCK_TUNNEL_1F|14,2", "n": 2}},
    "ROCK_TUNNEL_1F|14,2": {"15,3": {"to": "ROUTE_10|0,4", "n": 1},
                            "37,3": {"to": "ROCK_TUNNEL_B1F|26,2", "n": 4}},
    "ROCK_TUNNEL_B1F|26,2": {"27,3": {"to": "ROCK_TUNNEL_1F|4,2", "n": 4}},
    "ROCK_TUNNEL_1F|24,16": {"15,33": {"to": "ROUTE_10|14,52", "n": 1}},
    "ROUTE_10|14,52": {"south": {"to": "LAVENDER_TOWN|6,0", "n": 1}},
}, visits={"ROUTE_10|0,4": 3, "ROCK_TUNNEL_1F|14,2": 2, "ROUTE_10|14,52": 1, "LAVENDER_TOWN|6,0": 1})
ONE = record(explored={
    "ROUTE_10|0,4": {"8,17": {"to": "ROCK_TUNNEL_1F|14,2", "n": 2}},
    "ROCK_TUNNEL_1F|14,2": {"15,3": {"to": "ROUTE_10|0,4", "n": 1},
                            "37,3": {"to": "ROCK_TUNNEL_B1F|26,2", "n": 1}},
}, visits={"ROUTE_10|0,4": 2, "ROCK_TUNNEL_1F|14,2": 1})
GOAL = "Travel through Rock Tunnel"

# ---- the record's two verdicts ----------------------------------------------
ck("two mouths used: the record says through, naming both",
   A._through_by_record(GOAL, TWO) == "ROCK_TUNNEL: ROUTE_10|0,4, ROUTE_10|14,52", A._through_by_record(GOAL, TWO))
ck("...and the one-mouth refusal stands down", A._not_through_yet(GOAL, TWO) is None)
ck("one mouth used: the refusal names it", A._not_through_yet(GOAL, ONE) == "ROCK_TUNNEL (ROUTE_10|0,4)", A._not_through_yet(GOAL, ONE))
ck("...and the record does not say through", A._through_by_record(GOAL, ONE) is None)
ck("an objective that does not say through is nobody's business here",
   A._through_by_record("Reach Lavender Town", TWO) is None and A._not_through_yet("Reach Lavender Town", ONE) is None)
ck("a place never walked has no mouths", A._through_by_record("Travel through Victory Road", TWO) is None)
ck("no record at all: no verdict", A._through_by_record(GOAL, None) is None and A._through_by_record(GOAL, "/nonexistent.json") is None)
ck("floors of one place are one place",
   A._through_place_mouths(GOAL, TWO)[0] == "ROCK_TUNNEL" and A._through_place_mouths(GOAL, TWO)[1] == {"ROUTE_10|0,4", "ROUTE_10|14,52"})

# ---- the plan guard, once both mouths are on record -----------------------------
def plan(last_map, last_id="traverse_rock_tunnel"):
    return {"goal": GOAL, "subgoals": [
        {"id": "reach_route_10", "done_when": {"map": "ROUTE_10"}},
        {"id": "enter_rock_tunnel", "done_when": {"map": "ROCK_TUNNEL_1F"}},
        {"id": last_id, "done_when": {"map": last_map}},
    ]}
probs = A.through_a_place_problems(plan("ROUTE_11"), observed=TWO)
ck("a step after the place naming a map no walked way out lands on is refused",
   len(probs) == 1 and "ROUTE_11" in probs[0] and "ROUTE_10|0,4, ROUTE_10|14,52" in probs[0], probs)
ck("...naming the step and both mouths", "traverse_rock_tunnel" in probs[0] and "both of its mouths" in probs[0])
ck("...and saying what a checkable step looks like, without saying where the place comes out",
   'not_area' in probs[0] and "comes out on" not in probs[0].lower().replace("comes out onto", ""))
ck("a step that comes out onto a walked mouth is fine", A.through_a_place_problems(plan("ROUTE_10"), observed=TWO) == [])
ck("a step that goes on to ground you have stood on is fine", A.through_a_place_problems(plan("LAVENDER_TOWN"), observed=TWO) == [])
ck("with one mouth on record the far side may be named freely", A.through_a_place_problems(plan("ROUTE_11"), observed=ONE) == [])
ck("only the step right after the place is held to it",
   A.through_a_place_problems({"goal": GOAL, "subgoals": plan("ROUTE_10")["subgoals"]
                               + [{"id": "reach_route_11", "done_when": {"map": "ROUTE_11"}}]}, observed=TWO) == [])
ck("a plan with no step inside the place is still refused for that",
   "no step of this plan ends anywhere in ROCK_TUNNEL" in A.through_a_place_problems(
       {"goal": GOAL, "subgoals": [{"id": "x", "done_when": {"map": "ROUTE_11"}}]}, observed=TWO)[0])
ck("a plan that is not about going through is left alone",
   A.through_a_place_problems({"goal": "Reach Lavender Town", "subgoals": [{"id": "x", "done_when": {"map": "ROUTE_11"}}]}, observed=TWO) == [])

# ---- both rungs use it, after their refusals ------------------------------------
src = (ROOT / "planner" / "author.py").read_text()
cd = src[src.index("def check_done("):]
i_ref = cd.index("_not_through_yet(goal, observed)"); i_acc = cd.index("_through_by_record(goal, observed)")
i_gone = cd.index("_never_held(goal, start)"); i_model = cd.index("brock_probe.chat(")
ck("check-done accepts on two mouths after every refusal and before asking the model",
   i_ref < i_gone < i_acc < i_model and '[check-done] done: this objective says to go THROUGH' in cd)
ad = src[src.index("def check_already_done("):src.index("def check_done(")]
ck("...and so does the already-done rung",
   "_through_by_record(deed, observed)" in ad and ad.index("_never_held(deed, start)") < ad.index("_through_by_record(deed, observed)") < ad.index("brock_probe.chat("))
camp = (ROOT / "campaign.sh").read_text()
ck("the campaign's between-attempts check reads the record before the plan's last predicate",
   '_through_by_record(str(plan.get("goal") or ""), "run/explored.json")' in camp
   and camp.index('_through_by_record(str(plan.get("goal")') < camp.index('pred_holds(last, obs)'))
ck("one definition, shared by refusal and acceptance",
   src.count("def _through_place_mouths") == 1 and "got = _through_place_mouths(goal, observed)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
