#!/usr/bin/env python3
"""The draft picker is shown which line is the final condition, and told
when the drafts disagree about it.

Three drafts for "Travel through Rock Tunnel": two ended on ROUTE_10 past
the part the run entered from, which is the far side of the tunnel, and
one added a sixth step ending on ROUTE_9, the near side it had come from.
The pick took the ROUTE_9 one and gave its whole reason as "Plan 1 is the
most comprehensive as it includes buying Repels, which are practically
essential for traveling through Rock Tunnel in Pokemon Red" -- a true
thing about a step in the middle, weighed against nothing. The leg then
spent its attempt walking backwards to Route 9 (2026-09-14, user: "im
wondering how it got there in the first place so we can prevent this from
happening again").

The system prompt had said "judge them on ... whether the final condition
is really the goal" all along; the drafts arrived as a flat list with
nothing showing which line that was. Same lesson as the statue rows: say
it where the thing is, not only in a paragraph above it. And where the
drafts end differently, name that as the choice being made -- counting is
the harness's half, which ending is right is the model's.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                        # noqa: E402
import brock_probe                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

seen = []
def stub(pick=1):
    seen.clear()
    brock_probe.chat = lambda msgs, model, **kw: (
        seen.append(msgs[-1]["content"]) or ('{"why":"r","pick":%d}' % pick))

def plan(*steps):
    return {"subgoals": [{"id": i, "done_when": d} for i, d in steps]}

FAR = plan(("reach_route_10", {"map": "ROUTE_10"}),
           ("enter", {"map": "ROCK_TUNNEL_1F"}),
           ("exit_rock_tunnel", {"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4"]}))
NEAR = plan(("reach_route_10", {"map": "ROUTE_10"}),
            ("enter", {"map": "ROCK_TUNNEL_1F"}),
            ("exit_rock_tunnel", {"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4"]}),
            ("reach_route_9_east", {"map": "ROUTE_9", "not_area": ["ROUTE_9|0,8"]}))

stub(2)
got = A.pick_plan("Travel through Rock Tunnel", [NEAR, FAR], "stub", start="on ROUTE_10")
body = seen[0]
ck("the draft it picked is returned whole and unedited", got is FAR)
ck("the last step of every draft is marked as the ending",
   body.count("<- THE LAST STEP") == 2, body)
ck("...saying the plan finishes there and the leg is judged on it",
   "this plan is finished when this holds, and the leg is judged on it" in body)
ck("...and only the last step is marked",
   "reach_route_10" in body and "reach_route_10: {\"map\": \"ROUTE_10\"}   <-" not in body, body)
ck("the disagreement about the ending is named",
   "THESE DRAFTS DO NOT AGREE ABOUT WHAT FINISHES THIS LEG" in body, body)
ck("...listing each draft's ending, numbered to match",
   '1. {"map": "ROUTE_9", "not_area": ["ROUTE_9|0,8"]}' in body
   and '2. {"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4"]}' in body, body)
ck("...and calls that the choice", "That is the choice" in body)
ck("the harness does not say which ending is right",
   not any(w in body.lower() for w in ("should pick", "better", "correct one", "recommend")))

# drafts that agree about the ending are not told they disagree
stub(1)
A.pick_plan("g", [FAR, FAR], "stub")
ck("agreeing endings raise nothing", "DO NOT AGREE" not in seen[0], seen[0])
ck("...but the ending is still marked", seen[0].count("<- THE LAST STEP") == 2)

# the system prompt carries the consequence
ck("the prompt says the last step is what the plan is finished on",
   "A plan is finished when its\nLAST condition holds" in A.PLAN_PICK_SYS)
ck("...and that the steps before it are the route to it",
   "the steps before it are only the route to it" in A.PLAN_PICK_SYS)
ck("...and to settle the disagreement first",
   "decide it first, and let the rest follow" in A.PLAN_PICK_SYS)

# one draft is still returned without asking anyone
ck("a single draft is not put to a vote", A.pick_plan("g", [FAR], "stub") is FAR)
# an unusable reply still keeps a plan
brock_probe.chat = lambda msgs, model, **kw: "no json"
ck("an unreadable pick keeps the first draft", A.pick_plan("g", [NEAR, FAR], "stub") is NEAR)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400].replace("\n", " | "))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
