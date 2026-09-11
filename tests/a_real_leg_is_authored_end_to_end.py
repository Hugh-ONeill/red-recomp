#!/usr/bin/env python3
"""A real leg goes through the whole authoring path: prompt, reply, freeze,
validate — and the right plan survives while the known-bad shapes do not.

Every other test of this machinery is a unit: does new_part freeze, does the
far-side rule fire, does a screen condition get refused. None of them runs
the PATH, so a plan could pass every rule and still never reach validate,
or reach it in a shape the freezer had already rewritten. This drives
author.author() itself with the model replaced by a canned reply, so the
prompt is the real one built from the live world, the parse is the real
one, freeze_new_parts and validate are the real ones, and only the model's
judgement is fixed. The replies are plans this run actually produced.

Not a model test: it asserts nothing about what gemma writes. It asserts
that what the harness does with a plan is what the rules say.

  tests/a_real_leg_is_authored_end_to_end.py            canned, no GPU
  tests/a_real_leg_is_authored_end_to_end.py --live     call the model
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402
import brock_probe as B                                       # noqa: E402

LIVE = "--live" in sys.argv
fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


GOAL = "Retrieve the Secret Key from the Pokemon Mansion"

# a shape this run really authored for this leg: places it can reach, and a
# deed at the end that only holding the thing makes true
GOOD = {"goal": GOAL, "subgoals": [
    {"id": "travel_to_cinnabar", "goal_text": "Travel to Cinnabar Island.",
     "done_when": {"map": "CINNABAR_ISLAND"}},
    {"id": "enter_pokemon_mansion", "goal_text": "Enter the Pokemon Mansion.",
     "done_when": {"map": "POKEMON_MANSION_1F"}},
    {"id": "take_secret_key", "goal_text": "Pick up the Secret Key.",
     "done_when": {"has_item": {"SECRET_KEY": 1}}}]}

# the shapes the rules exist to refuse, each one drawn from a real refusal
BAD = {
    "a screen no op leaves open":
        [{"id": "open_pc", "goal_text": "Open the PC storage.",
          "done_when": {"screen": "BoxMenu"}}],
    "a deed leg that ends on a place":
        [{"id": "reach_mansion", "goal_text": "Reach the Pokemon Mansion.",
          "done_when": {"map": "POKEMON_MANSION_1F"}}],
    "an event this game does not define":
        [{"id": "take_key", "goal_text": "Take the key.",
          "done_when": {"flag": "EVENT_GOT_SECRET_KEY_FROM_MANSION"}}],
}


# THE WORLD IS PINNED, NOT BORROWED. This authored against run/obs.json,
# so the day the run picked the SECRET KEY up the sound plan started being
# refused for ending on something already true (2026-09-10). A synthetic
# test must not depend on how far the live run has got.
PINNED = {"map": {"id": "CINNABAR_ISLAND", "region": "10,0"},
          "player": {"x": 10, "y": 0}, "mode": "overworld",
          "bag": {"POKE_BALL": 5}, "key_items": [], "badges": [],
          "flags": [], "party": [{"species": "CHARIZARD", "level": 56,
                                  "types": ["FIRE", "FLYING"],
                                  "hp": 190, "max_hp": 190}]}
A._obs_now = lambda path="run/obs.json": dict(PINNED)


def run_author(reply_plan) -> tuple:
    """author() with the model stubbed. Returns (plan, prompts seen)."""
    seen = []
    real = B.chat

    def fake(msgs, model, retries=2, think=False):
        seen.append(msgs[-1]["content"])
        return json.dumps(reply_plan)

    B.chat = fake
    try:
        return A.author(GOAL, "stub-model", rounds=1), seen
    finally:
        B.chat = real


plan, prompts = run_author(GOOD)
ck("the real prompt is built and carries the goal", prompts and GOAL in prompts[0])
ck("...and the world the run is actually in", prompts and "STARTING STATE" in prompts[0])
ck("...and the predicate vocabulary it may use", prompts and "has_item" in prompts[0] and "new_part" in prompts[0])
ck("a sound plan survives the whole path", plan is not None, plan)
if plan:
    ck("...with its steps intact", [s["id"] for s in plan["subgoals"]] == [s["id"] for s in GOOD["subgoals"]])
    ck("...and every step given a round budget", all(s.get("escalation_rounds") for s in plan["subgoals"]))
    ck("...and stamped with who wrote it", all(s.get("subgoal_provenance") for s in plan["subgoals"]))

for why, subs in BAD.items():
    bad = {"goal": GOAL, "subgoals": subs}
    got, _ = run_author(bad)
    ck(f"refused: {why}", got is None)

# new_part goes in as a key and comes out frozen, on the real ledger
np = {"goal": "Travel through the Seafoam Islands from their east entrance to their west exit",
      "subgoals": [{"id": "exit_west", "goal_text": "Come out on the far side.",
                    "done_when": {"new_part": "ROUTE_20"}}]}
A.freeze_new_parts(np)
dw = np["subgoals"][0]["done_when"]
ck("new_part freezes into the map it names", dw.get("map") == "ROUTE_20" and "new_part" not in dw)
ck("...carving off parts from the run's own record, not the model's memory",
   isinstance(dw.get("not_area"), list)
   and all(str(p).startswith("ROUTE_20|") for p in dw["not_area"]))

if LIVE:
    print("\n--- live: the model actually writes it ---")
    real_plan = A.author(GOAL, "gemma4:31b-it-q4_K_M", rounds=3)
    ck("the model produces a plan the validator accepts", real_plan is not None)
    if real_plan:
        print("   " + " -> ".join(s["id"] for s in real_plan["subgoals"]))

sys.exit(1 if fails else 0)
