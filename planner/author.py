#!/usr/bin/env python3
"""SPD plan authoring: the model writes the subgoal DECOMPOSITION.

This is the last hand-seeded piece of SPD. Given a goal, the local model
authors an ordered list of subgoals (id + goal_text + done_when predicate).
The executor then runs the plan with --escalate, and the model AUTHORS each
subgoal's macro by playing (escalation), distilling it back — so the whole
route becomes model-authored, decomposition and macros alike.

The model gets the "API" (its intelligence is the decomposition itself):
  - the predicate DSL it may use for done_when
  - the map ids and milestone event-flags it may reference (it knows Red but
    not the exact strings)
  - the granularity rule learned in step 3: ONE map-transition or ONE
    event/interaction per subgoal (the executor authors macros from the
    current map's visible warps/objects, so coarse subgoals aren't authorable)

Usage:
  author.py --goal "Get the Boulder Badge from Brock" --out plans/brock.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import brock_probe   # reuse chat()

# The vocabulary the decomposition may reference. Predicates come from the
# executor's DSL; maps/flags are the executor's instrumentation, exposed here
# so the model can name done_when conditions exactly.
PREDICATES = {
    "map": "current map id equals VALUE (e.g. {\"map\":\"PEWTER_CITY\"})",
    "mode": "obs mode equals VALUE (usually \"overworld\")",
    "party_nonempty": "true = have at least one Pokemon",
    "party_alive": "true = at least one Pokemon with HP > 0",
    "badge": "VALUE badge earned (e.g. {\"badge\":\"BOULDERBADGE\"})",
    "flag": "a save event flag is set (e.g. {\"flag\":\"EVENT_GOT_POKEDEX\"})",
    "no_battle": "true = not currently in a battle",
    "party_healthy": "true = every party Pokemon at full HP with no status "
                     "(use for Pokemon Center heal stops)",
    "lead_level": "lead Pokemon is at least level N (e.g. {\"lead_level\":12} "
                  "— use for training subgoals on a grassy route)",
    "has_item": "bag holds at least N of each listed item (e.g. "
                "{\"has_item\":{\"POTION\":4}} — use for shopping subgoals "
                "at a mart)",
    "party_size": "party has at least N Pokemon (e.g. {\"party_size\":2} — "
                  "use for catch subgoals; set battle_policy \"catch\" on "
                  "them)",
}
ROUTE_MAPS = ["REDS_HOUSE_2F", "REDS_HOUSE_1F", "PALLET_TOWN", "OAKS_LAB",
              "ROUTE_1", "VIRIDIAN_CITY", "VIRIDIAN_MART",
              "VIRIDIAN_POKECENTER", "ROUTE_22", "ROUTE_2",
              "VIRIDIAN_FOREST", "PEWTER_CITY", "PEWTER_MART",
              "PEWTER_POKECENTER", "PEWTER_GYM",
              "ROUTE_3", "MT_MOON_POKECENTER", "ROUTE_4",
              "MT_MOON_1F", "MT_MOON_B1F", "MT_MOON_B2F", "CERULEAN_CITY"]
KEY_FLAGS = {
    "EVENT_OAK_ASKED_TO_CHOOSE_MON": "Oak finished his intro and the starter "
        "Poke Balls are now active to choose from (use this to mark 'reached "
        "the lab AND it's ready' — a plain {map:OAKS_LAB} fires too early, "
        "before Oak's speech arms the balls)",
    "EVENT_GOT_STARTER": "obtained a starter Pokemon",
    "EVENT_BATTLED_RIVAL_IN_OAKS_LAB": "fought the rival in Oak's lab",
    "EVENT_GOT_OAKS_PARCEL": "picked up Oak's Parcel at the Viridian mart",
    "EVENT_GOT_POKEDEX": "delivered the parcel to Oak and got the Pokedex "
                         "(this unlocks the north exit of Viridian City)",
    "EVENT_BEAT_BROCK": "defeated Brock at Pewter Gym",
    "EVENT_BEAT_MT_MOON_3_SUPER_NERD": "beat the Super Nerd guarding the "
        "fossils on Mt Moon's bottom floor (B2F) — the fossil pick follows",
}
BADGES = ["BOULDERBADGE"]

SYS = """You author a PLAN to accomplish a Pokemon Red goal: an ordered list
of SUBGOALS. You write the decomposition and the success condition of each
step; a separate system will later figure out the exact button/op sequence
for each subgoal by playing. So you do NOT give coordinates or ops here — you
give the milestones and how to know each is done.

ATTRITION: battles chip your party's HP and there is no auto-healing —
insert a Pokemon Center heal stop (done_when {"party_healthy": true}) before
long wild-encounter stretches like Viridian Forest. If upcoming trainers
outlevel your party, add TRAINING subgoals on a grassy route
(done_when {"lead_level": N}) — and STAGE long grinds: a few levels per
subgoal with a Pokemon Center heal stop between stages. Fainting sends
you home and HALVES YOUR MONEY, so wipes during long unhealed grinds
bankrupt later shopping.
Marts sell healing items (a POTION heals 20 HP, ~300 money; you start with
3000): add a SHOPPING subgoal (done_when {"has_item": {...}}) before a
trainer gauntlet with no Center inside it. Know your marts: VIRIDIAN_MART
sells NO potions (Poke Balls, Antidotes, Parlyz Heals only); PEWTER_MART
is the first that sells POTION.
A LONE Pokemon that faints means a blackout (money halved): CATCH A BACKUP
early (a shopping stop for Poke Balls, then a catch subgoal with
{"party_size": 2} on a grassy route) so a lead faint becomes a switch
instead.

Hard rule on GRANULARITY: each subgoal must be ONE map transition, OR one
event/interaction that happens within a single map. Do not bundle multiple
map changes into one subgoal. (e.g. leaving the house is TWO subgoals: go
downstairs, then out the front door. Getting the starter is TWO: trigger
Oak's escort to the lab, then take a Poke Ball.)

Each subgoal is an object:
  {"id":"snake_case_name",
   "goal_text":"one or two sentences telling the player exactly what to do",
   "done_when":{<one predicate>}}

Reply with ONLY a JSON object: {"goal":"...","subgoals":[ ... ]}."""


NEW_GAME_START = (
    "a brand-new game — the player begins UPSTAIRS in their own bedroom "
    "(map REDS_HOUSE_2F) with no Pokemon. Your FIRST subgoals must get "
    "them out of the house (downstairs, then out the front door) before "
    "anything else.")


def build_prompt(goal: str, start: str | None = None) -> str:
    return (
        f"GOAL: {goal}\n\n"
        f"STARTING STATE: {start or NEW_GAME_START}\n\n"
        f"PREDICATES you may use in done_when (pick the ONE that best marks "
        f"the subgoal complete):\n"
        + "\n".join(f"  {k}: {v}" for k, v in PREDICATES.items())
        + "\n\nMAP IDs on this route (use exact strings):\n  "
        + ", ".join(ROUTE_MAPS)
        + "\n\nKEY EVENT FLAGS (use exact strings; prefer a map/party/badge "
        "predicate when one fits, but these mark events that are not just a "
        "map change):\n"
        + "\n".join(f"  {k}: {v}" for k, v in KEY_FLAGS.items())
        + f"\n\nBADGES: {', '.join(BADGES)}\n\n"
        "Author the ordered subgoal list now. Remember the granularity rule.")


VALID_KEYS = set(PREDICATES)


def validate(plan: dict) -> list:
    """Return a list of problems (empty = ok)."""
    probs = []
    subs = plan.get("subgoals")
    if not isinstance(subs, list) or not subs:
        return ["no subgoals"]
    seen = set()
    for i, s in enumerate(subs):
        tag = f"subgoal[{i}]"
        if not isinstance(s, dict):
            probs.append(f"{tag} not an object"); continue
        sid = s.get("id")
        if not sid:
            probs.append(f"{tag} missing id")
        elif sid in seen:
            probs.append(f"{tag} duplicate id {sid}")
        seen.add(sid)
        if not s.get("goal_text"):
            probs.append(f"{tag} missing goal_text")
        dw = s.get("done_when")
        if not isinstance(dw, dict) or not dw:
            probs.append(f"{tag} ({sid}) missing/empty done_when")
            continue
        for k, v in dw.items():
            if k not in VALID_KEYS:
                probs.append(f"{tag} ({sid}) unknown predicate '{k}'")
            elif k == "map" and v not in ROUTE_MAPS:
                probs.append(f"{tag} ({sid}) map '{v}' not in the route list")
            elif k == "flag" and v not in KEY_FLAGS:
                probs.append(f"{tag} ({sid}) flag '{v}' not in the vocabulary")
            elif k == "badge" and v not in BADGES:
                probs.append(f"{tag} ({sid}) badge '{v}' unknown")
    return probs


def author(goal: str, model: str, rounds: int = 3,
           start: str | None = None) -> dict | None:
    fb = ""
    for rnd in range(1, rounds + 1):
        user = build_prompt(goal, start) + (f"\n\nFIX THESE PROBLEMS from your last "
                                     f"attempt:\n{fb}" if fb else "")
        reply = brock_probe.chat(
            [{"role": "system", "content": SYS},
             {"role": "user", "content": user}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            fb = "your reply was not a JSON object"; continue
        try:
            plan = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            fb = f"invalid JSON: {e}"; continue
        probs = validate(plan)
        if not probs:
            # tag each subgoal so escalation/distillation runs it macro-less
            for s in plan["subgoals"]:
                s.setdefault("escalation_rounds", 4)
            print(f"[author] valid plan in round {rnd}: "
                  f"{len(plan['subgoals'])} subgoals")
            return plan
        fb = "\n".join(f"- {p}" for p in probs)
        print(f"[author] round {rnd} invalid:\n{fb}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="gemma4:26b-a4b-it-q4_K_M")
    ap.add_argument("--start", default=None,
                    help="starting-state description (default: new game)")
    args = ap.parse_args()
    plan = author(args.goal, args.model, start=args.start)
    if not plan:
        sys.exit("author failed to produce a valid plan")
    plan.setdefault("goal", args.goal)
    plan["authored_by"] = args.model
    args.out.write_text(json.dumps(plan, indent=2))
    print(f"wrote {args.out}")
    for s in plan["subgoals"]:
        print(f"  {s['id']}: done_when={json.dumps(s['done_when'])}")


if __name__ == "__main__":
    main()
