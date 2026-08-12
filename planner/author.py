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
    "player_at": "standing within radius R of a tile, e.g. "
                 "{\"player_at\":{\"x\":27,\"y\":3,\"radius\":4}}. Combine it "
                 "with map when a map predicate alone cannot say WHERE",
    "area": "a SPECIFIC ENCLOSED AREA rather than a whole map, written "
        "\"MAP|region\" (e.g. {\"area\":\"MT_MOON_B2F|20,5\"}). A floor can "
        "be several rooms that cannot walk to each other, so {\"map\":...} "
        "is satisfied by landing in ANY of them — use this when the thing "
        "you need is in one particular room. Only use area codes that appear "
        "in the observed evidence below; do not invent one",
    "party_min_level": "EVERY party member is at least VALUE "
        "(e.g. {\"party_min_level\":15}). Use this to TRAIN A BACKUP: "
        "lead_level only looks at slot 1, so it is already true when your "
        "lead is strong and trains nothing. NOTE a Pokemon only gains "
        "experience while it is the LEAD, so a subgoal like this needs a "
        "pick_party op to put the weak one in front first",
    "slot_level": "a particular party slot reaches a level "
        "(e.g. {\"slot_level\":{\"slot\":2,\"min\":15}}), 1-based",
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
# EXACT item ids, for the same reason the map/flag lists exist: the model
# knows Poke Balls and Potions are things, it cannot know the engine spells
# them POKE_BALL (underscore) and PARLYZ_HEAL. Left to guess it wrote
# "POKEBALL", which has_item can never match, so the subgoal was
# unsatisfiable from the moment it was written.
KEY_ITEMS = {
    "POKE_BALL": "a Poke Ball (NOTE the underscore) — needed to catch",
    "POTION": "heals 20 HP out of battle or in it",
    "ANTIDOTE": "cures poison",
    "PARLYZ_HEAL": "cures paralysis",
    "BURN_HEAL": "cures a burn",
    "ESCAPE_ROPE": "warps you out of a cave",
    "REPEL": "keeps weak wild encounters away for a while",
}
# What each shop actually stocks. A has_item goal placed at a counter that
# does not sell the item is unsatisfiable no matter how well it is played:
# shop_for_potions at the VIRIDIAN mart failed every single run.
SHOP_STOCK = {
    "VIRIDIAN_MART": "POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL "
                     "(NO Potions — do not put a POTION goal here)",
    "PEWTER_MART": "POKE_BALL, POTION, ESCAPE_ROPE, ANTIDOTE, BURN_HEAL, "
                   "AWAKENING",
}

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

AMBIGUOUS MAPS: a {"map": X} done_when is satisfied ANYWHERE on that map,
and some maps are split into disconnected areas you cannot walk between
(caves with separate wings, routes divided by a mountain or a ledge). So
whenever a subgoal RETURNS to a map an earlier subgoal already reached —
you will see the same map id twice in your list — {"map": X} cannot tell
the two arrivals apart and the second subgoal is already "done" the moment
it starts. In that case add "player_at" alongside it to pin down WHICH part
of the map (a small radius; proximity across a wall does not count as
arrival). Prefer a landmark you can name: the far ladder, the east exit.

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
        + "\n\nITEM IDs (use exact strings in has_item):\n"
        + "\n".join(f"  {k}: {v}" for k, v in KEY_ITEMS.items())
        + "\n\nWHAT EACH SHOP SELLS — a has_item goal at a counter that "
          "does not stock the item can never be satisfied:\n"
        + "\n".join(f"  {k}: {v}" for k, v in SHOP_STOCK.items())
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
            elif k == "has_item" and isinstance(v, dict):
                for item in v:
                    if item not in KEY_ITEMS:
                        probs.append(f"{sg.get('id')}: unknown item {item!r} "
                                     f"(valid: {', '.join(KEY_ITEMS)})")
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


REVIEW_SYS = (
    "You are reviewing a Pokemon Red subgoal plan you just wrote, looking "
    "for subgoals that CANNOT do their job. Reply with the corrected plan "
    "as a JSON object in the same schema, and nothing else."
)


def observed_text(path: Path) -> str:
    """What earlier runs actually WALKED, as evidence for the audit.

    The model's own idea of the map can be wrong in ways no amount of
    self-review will catch: it believed Mt Moon was entered from ROUTE_3 and
    left to ROUTE_4, so {map:ROUTE_4} looked like a proper far-side
    condition. In this recomp ROUTE_4 is on BOTH sides, so that subgoal was
    satisfied by stepping back out the entrance. This is not route knowledge
    handed to the model — it is the model's own play, read back to it.
    """
    try:
        d = json.loads(Path(path).read_text() or "{}")
    except Exception:
        return ""
    exp = d.get("explored") or {}
    if not exp:
        return ""
    lines = []
    for region in sorted(exp):
        for key, e in sorted((exp[region] or {}).items()):
            lines.append(f"  {region}  --{key}-->  {e.get('to')}")
    seen = []
    for region, names in sorted((d.get("sightings") or {}).items()):
        if names:
            seen.append(f"  {region}: {', '.join(names[:8])}")
    dead = []
    for tgt, regions in (d.get("dead_ends") or {}).items():
        for region, n in regions.items():
            dead.append(f"  {tgt} was NOT reachable from {region} ({n}x)")
    areas = sorted({r for r in exp} | {t for v in exp.values()
                                       for t in [e.get("to") for e in v.values()] if t})
    out = ("\n\nAREA CODES you may use with the \"area\" predicate (these are "
           "the enclosed areas actually walked):\n  " + ", ".join(areas[:40])
           + "\n\nWHAT PREVIOUS RUNS ACTUALLY WALKED (evidence — trust this "
           "over your memory of the game; MAP|region means one connected "
           "area, so the SAME map id appearing with DIFFERENT regions is a "
           "map split into parts that cannot walk to each other):\n"
           + "\n".join(lines))
    if seen:
        out += ("\n\nWHAT WAS SEEN IN EACH AREA (so you can aim a subgoal "
                "at the RIGHT part of a map — the same map id can have "
                "several unconnected parts, and only one of them holds the "
                "thing you need):\n" + "\n".join(seen))
    if dead:
        out += "\n\nPROVEN UNREACHABLE:\n" + "\n".join(dead)
    return out


def journal_text(path: Path, limit: int = 60) -> str:
    """A chronological account of what HAPPENED, not just where it went.

    Connectivity says which doors exist; it cannot say the run reached the
    gym with 83 money and a 300-Potion to buy, or that it wiped twice and
    halved its wallet each time. Those are plan-ordering mistakes — buy
    before you spend, train before you fight — and the model can only fix
    what it is shown. Assembled from the executor log, so nothing extra has
    to be written during play.
    """
    try:
        recs = []
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        # NOT segmented to the last plan_start: each campaign attempt
        # restarts the executor, and the mistake worth fixing (spent the
        # wallet on balls, then could not buy a Potion) usually happened an
        # attempt or two earlier. The tail of the whole log is the story.
        seg = recs
    except Exception:
        return ""
    events = []
    # PP exhaustion detector: a battle whose every chosen move scored 0 was
    # fought with ONLY status moves usable — the attacking moves were out of
    # PP (that fact is on the move menu the whole time). The wipes in Mt
    # Moon were this: the trek drained Ember and Scratch, a wild Zubat was
    # "fought" with 31 turns of GROWL, and connectivity can never say why.
    # The tell is the TAIL: the scorer only picks a 0-score move when
    # nothing that deals damage has PP left, so a run of them ending the
    # battle means the attacking moves ran dry (PP may run out MID-fight —
    # the wipe battle opened with the last two Scratches).
    bt_tail = 0
    for r in seg:
        k = r.get("kind")
        if k == "battle_start":
            bt_tail = 0
        elif k == "battle_turn" and r.get("op") == "battle_move":
            bt_tail = (bt_tail + 1 if "score=0.0" in (r.get("why") or "")
                       else 0)
        elif k == "battle_done":
            if bt_tail >= 8:
                events.append(
                    f"  NO PP   a {r.get('turns')}-turn battle ended with "
                    f"{bt_tail} straight 0-damage moves — every ATTACKING "
                    f"move was out of PP. Long stretches of wild battles "
                    f"drain PP and only a Pokemon Center restores it")
            bt_tail = 0
        if k == "subgoal_done" or k == "escalate_success":
            events.append(f"  OK      {r.get('subgoal')}")
        elif k == "subgoal_failed":
            events.append(f"  FAILED  {r.get('subgoal')}")
        elif k == "blackout":
            events.append(f"  WIPED   during {r.get('subgoal')} — sent to "
                          f"{r.get('respawn')}, and a blackout costs you "
                          f"HALF YOUR MONEY")
        elif k == "rerouted":
            events.append(f"  walked back to {r.get('to')} looking for a way on")
        for t in (r.get("trace") or []):
            if "cannot afford" in t:
                events.append(f"  MONEY   {t.split('FAILED — ')[-1][:90]}")
            elif "is not sold here" in t:
                events.append(f"  SHOP    {t.split('FAILED — ')[-1][:90]}")
            # A WALL the run kept hitting is exactly what a rewrite must
            # know. "cross(east) FAILED — the east seam of ROUTE_4 (to
            # CERULEAN_CITY) cannot be crossed" lived only in transient
            # escalation feedback, so three rewrites in a row re-authored
            # the same west-side loop that dies on it.
            elif "seam of" in t and "FAILED" in t:
                wall = f"  WALL    {t.split('FAILED — ')[-1][:120]}"
                if not events or events[-1] != wall:
                    events.append(wall)
            elif "party FAINTED" in t:
                pass
    if not events:
        return ""
    # keep the tail: the end of the run is where it went wrong
    shown = events[-limit:]
    return ("\n\nWHAT HAPPENED ON THE LAST RUN, in order (this is the "
            "causal story — if it ran out of money, or wiped, or failed the "
            "same step repeatedly, fix the PLAN's ordering and amounts so "
            "that cannot happen again):\n" + "\n".join(shown))


def build_review(goal: str, plan: dict, start: str | None) -> str:
    """Ask the model to audit its own plan for conditions that cannot work.

    Every check here came from a condition that actually failed a run, and
    each is about the CONDITION, not the route — the model supplies the game
    knowledge, this only tells it what kinds of mistake to look for.
    """
    return (
        f"GOAL: {goal}\n"
        f"START: {start or 'a brand new game'}\n\n"
        f"THE PLAN YOU WROTE:\n{json.dumps(plan, indent=1)}\n\n"
        "Audit every subgoal against these failure modes and fix the ones "
        "that are broken:\n"
        "1. SATISFIED BY GOING BACKWARDS. A done_when that is already true "
        "next to where the subgoal starts, or that becomes true by walking "
        "back the way you came, marks itself done without progress. This is "
        "the worst one: a {map:X} goal where X is the map you ENTERED from "
        "is satisfied by simply stepping back outside, so a whole dungeon "
        "gets skipped and every later subgoal fails. If a subgoal means "
        "'come out the FAR side', its condition must be something only true "
        "on the far side — an event flag for something in there, an item you "
        "can only pick up inside, or player_at coordinates on the far side.\n"
        "2. IMPOSSIBLE WHERE IT IS PLACED. A has_item goal at a shop that "
        "does not stock that item, or a flag that fires somewhere the "
        "subgoal never goes, can never be satisfied no matter how well it "
        "is played.\n"
        "3. MORE THAN ONE LEG. One map transition or one interaction per "
        "subgoal. A subgoal needing two warps, or a walk AND a warp, cannot "
        "be authored as a single macro — split it.\n"
        "4. A GAP. Two consecutive subgoals with something unstated in "
        "between (a gate, a door, a required event) that nothing achieves.\n"
        "5. NAMES. Only the map ids, flags, items and predicates from the "
        "vocabulary above, spelled exactly.\n\n"
        "Keep what is right — do not rewrite the plan for style. Return the "
        "full corrected plan."
    )


def merge_plans(orig: dict, revised: dict) -> tuple:
    """Let a revision ADD and UPDATE subgoals, never DELETE one.

    An audit run against thin evidence talks itself out of conditions that
    are load-bearing: one dropped defeat_mt_moon_nerd — the only condition
    in the mountain leg that RETREATING cannot satisfy — leaving a chain of
    map hops that all mark themselves done by walking back out. Deleting is
    the one edit with no safe failure mode, so it is not allowed; a subgoal
    the revision considers wrong can still be re-pointed by updating its
    done_when.
    """
    rev_ids = {x["id"] for x in revised["subgoals"]}
    out = list(revised["subgoals"])
    restored = []
    for i, sg in enumerate(orig["subgoals"]):
        if sg["id"] in rev_ids:
            continue
        restored.append(sg["id"])
        pos = len(out)
        if i > 0:                       # keep it behind the step it followed
            prev = orig["subgoals"][i - 1]["id"]
            for j, t in enumerate(out):
                if t["id"] == prev:
                    pos = j + 1
                    break
        else:
            pos = 0
        out.insert(pos, sg)
    merged = dict(revised)
    merged["subgoals"] = out
    return merged, restored


def review(goal: str, plan: dict, model: str, start: str | None = None,
           rounds: int = 2, observed: Path | None = None,
           journal: Path | None = None) -> dict:
    """Second model pass over its own plan. Returns the revision only if it
    still validates; a broken revision is discarded in favour of the
    original, so review can improve a plan but never corrupt it."""
    base = (build_prompt(goal, start)
            + (observed_text(observed) if observed else "")
            + (journal_text(journal) if journal else ""))
    for rnd in range(1, rounds + 1):
        reply = brock_probe.chat(
            [{"role": "system", "content": REVIEW_SYS},
             {"role": "user", "content": base + "\n\n" +
              build_review(goal, plan, start)}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            continue
        try:
            revised = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        probs = validate(revised)
        if probs:
            print(f"[review] round {rnd} produced an invalid plan, keeping "
                  f"the previous one: {probs[0]}")
            continue
        revised, restored = merge_plans(plan, revised)
        if restored:
            print(f"[review] refused to DELETE {len(restored)} subgoal(s), "
                  f"put back: {', '.join(restored)}")
        probs = validate(revised)
        if probs:
            print(f"[review] merged plan invalid, keeping the previous one: "
                  f"{probs[0]}")
            continue
        for s in revised["subgoals"]:
            s.setdefault("escalation_rounds", 4)
        before = [x["id"] for x in plan["subgoals"]]
        after = [x["id"] for x in revised["subgoals"]]
        print(f"[review] round {rnd}: {len(before)} -> {len(after)} subgoals")
        for sid in after:
            if sid not in before:
                print(f"[review]   + {sid}")
        for sid in before:
            if sid not in after:
                print(f"[review]   - {sid}")
        for a in revised["subgoals"]:
            b = next((x for x in plan["subgoals"] if x["id"] == a["id"]), None)
            if b and b.get("done_when") != a.get("done_when"):
                print(f"[review]   ~ {a['id']}: "
                      f"{json.dumps(b.get('done_when'))} -> "
                      f"{json.dumps(a.get('done_when'))}")
        return revised
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="gemma4:26b-a4b-it-q4_K_M")
    ap.add_argument("--start", default=None,
                    help="starting-state description (default: new game)")
    ap.add_argument("--no-review", action="store_true",
                    help="skip the model's self-audit pass")
    ap.add_argument("--observed", type=Path, default=None,
                    help="explored.json from earlier runs: real connectivity "
                         "evidence for the audit pass")
    ap.add_argument("--journal", type=Path, default=None,
                    help="executor_log.jsonl: what actually happened last "
                         "run (money, wipes, failed steps) for the audit")
    args = ap.parse_args()
    plan = author(args.goal, args.model, start=args.start)
    if not plan:
        sys.exit("author failed to produce a valid plan")
    if not args.no_review:
        plan = review(args.goal, plan, args.model, start=args.start,
                      observed=args.observed, journal=args.journal)
    plan.setdefault("goal", args.goal)
    plan["authored_by"] = args.model
    args.out.write_text(json.dumps(plan, indent=2))
    print(f"wrote {args.out}")
    for s in plan["subgoals"]:
        print(f"  {s['id']}: done_when={json.dumps(s['done_when'])}")


if __name__ == "__main__":
    main()
