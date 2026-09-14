#!/usr/bin/env python3
"""The author's retry prompt shows the attempt it is asking the model to fix.

Every authoring round is a fresh two-message chat. The retry said "FIX
THESE PROBLEMS from your last attempt ... Change nothing else about your
plan" with the last attempt nowhere in the prompt, so the model rewrote
from scratch each round with only the error list -- and fixed the mistake
it was told about while putting the other one back. The parcel leg went
flag / item / flag / item / flag for fifteen rounds across three draws on
2026-09-14, on a leg it had authored correctly eight times before, and the
chain pushed the leg later (user: "it went up to v7 without seeing the
mart"). "Change nothing else" is a thing you can only do to a plan you
can see.

Also here, because they were found in the same fifteen rounds: the
no-such-event problem said "the game keeps NO event for this" of a deed
the engine keeps two events for; it now says only what is true, that no
event begins the way the guess did, and still names no other event (the
no-leak rule of 2026-08-18 stands). And the menu of visible finishes now
names lacks_item, the shape a GIVING leaves behind.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                       # noqa: E402
import brock_probe                                       # noqa: E402
from pinned_world import pinned                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

BAD = {"goal": "Collect the OAKS_PARCEL and deliver it to Professor Oak",
       "subgoals": [
           {"id": "collect_parcel", "goal_text": "Get the parcel from the clerk",
            "done_when": {"has_item": {"OAKS_PARCEL": 1}}},
           {"id": "deliver_parcel", "goal_text": "Hand it to Oak",
            "done_when": {"flag": "EVENT_OAKS_PARCEL"}}]}
GOOD = {"goal": BAD["goal"],
        "subgoals": [BAD["subgoals"][0],
                     {"id": "deliver_parcel", "goal_text": "Hand it to Oak",
                      "done_when": {"lacks_item": ["OAKS_PARCEL"]}}]}

calls = []
def chat(msgs, model, **kw):
    calls.append(msgs)
    return json.dumps(BAD if len(calls) == 1 else GOOD)
brock_probe.chat = chat
brock_probe.log_thinking = lambda *a, **k: None

START = ("standing in PALLET_TOWN with CHARMANDER L5 (FIRE) 20/20hp, no "
         "badges, 3000 money")
with pinned(obs={"map": {"id": "PALLET_TOWN", "region": "1,1"},
                 "flags": ["EVENT_GOT_STARTER"], "items": {}}):
    plan = A.author(BAD["goal"], "stub", rounds=3, start=START)

ck("the first attempt is refused and the second accepted",
   len(calls) == 2 and plan is not None, (len(calls), plan is not None))
u1 = calls[0][-1]["content"]
u2 = calls[1][-1]["content"] if len(calls) > 1 else ""
ck("round one carries no attempt to fix", "YOUR LAST ATTEMPT" not in u1)
ck("round two shows the attempt it is asking to fix",
   "YOUR LAST ATTEMPT" in u2 and '"id":"deliver_parcel"' in u2
   and '"EVENT_OAKS_PARCEL"' in u2, u2[-900:])
ck("...whole, so 'change nothing else' can be obeyed",
   '"id":"collect_parcel"' in u2 and '"OAKS_PARCEL":1' in u2)
ck("...and the problems with it", "FIX THESE PROBLEMS in that attempt" in u2
   and "EVENT_OAKS_PARCEL" in u2.split("FIX THESE PROBLEMS", 1)[1])
ck("the attempt comes before the problems",
   u2.index("YOUR LAST ATTEMPT") < u2.index("FIX THESE PROBLEMS"))

# ---- the no-such-event problem tells the truth and leaks nothing ---------
with pinned(obs={"map": {"id": "PALLET_TOWN", "region": "1,1"},
                 "flags": ["EVENT_GOT_STARTER"], "items": {}}):
    probs = A.validate(json.loads(json.dumps(BAD)))
txt = "\n".join(probs)
ck("the guessed flag is refused", "EVENT_OAKS_PARCEL' is not an event" in txt, txt)
ck("...saying only what is true: nothing BEGINS WITH the guess",
   "No event in this game's list begins with EVENT_OAKS_PARCEL" in txt
   and "keeps NO event" not in txt, txt)
ck("...and that another name is not the model's to look up",
   "not yours to look up" in txt)
ck("...without naming the event it could have", "EVENT_GOT_OAKS_PARCEL" not in txt
   and "EVENT_OAK_GOT_PARCEL" not in txt)
ck("the visible finishes it offers include the thing GONE",
   "takes from you (lacks_item)" in txt, txt)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:600].replace("\n", " | "))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
