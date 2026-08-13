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
import difflib
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
    "lead_level": "the LEAD Pokemon (slot 1) is at least level N "
                  "(e.g. {\"lead_level\":12})",
    "has_item": "bag holds at least N of each listed item (e.g. "
                "{\"has_item\":{\"POTION\":4}})",
    "player_at": "standing within radius R of a tile, e.g. "
                 "{\"player_at\":{\"x\":27,\"y\":3,\"radius\":4}}. Combine it "
                 "with map when a map predicate alone cannot say WHERE",
    "area": "a SPECIFIC ENCLOSED AREA rather than a whole map, written "
        "\"MAP|region\" (e.g. {\"area\":\"MT_MOON_B2F|20,5\"}). A floor can "
        "be several rooms that cannot walk to each other, so {\"map\":...} "
        "is satisfied by landing in ANY of them — use this when the thing "
        "you need is in one particular room. Only use area codes that appear "
        "in the observed evidence below; do not invent one",
    "party_min_level": "EVERY party member is at least VALUE (e.g. "
        "{\"party_min_level\":15}). Note lead_level only reads slot 1, so it "
        "is already true whenever the lead alone is strong enough",
    "slot_level": "a particular party slot reaches a level (e.g. "
        "{\"slot_level\":{\"slot\":2,\"min\":15}}), 1-based. While such a "
        "subgoal runs the harness sends THAT slot into each battle, so the "
        "one you name is the one that earns",
    "party_size": "party has at least N Pokemon (e.g. {\"party_size\":2}); "
                  "set battle_policy \"catch\" on such a subgoal so wild "
                  "battles throw balls instead of knocking the target out",
}
# EVERY map id the engine defines, ALPHABETICAL. Two deliberate choices.
# WHICH names appear is not curated: a hand-picked subset is a hint about
# where to go next, and adding exactly the Cerulean maps the night the
# Cerulean leg started was one. ORDER is not the route: this list used to
# read bedroom -> Pallet -> Oak's lab -> Route 1 -> Viridian -> Forest ->
# Pewter -> Mt Moon -> Cerulean, which is a walkthrough wearing a
# vocabulary's clothes. Alphabetical carries no itinerary. What survives is
# the pamphlet-tier fact the model cannot get from its own knowledge of the
# game: how THIS engine spells the places (VERMILION with one L,
# CASCADEBADGE as one word) so a plan can name them and validate.
ROUTE_MAPS = [
    "AGATHAS_ROOM", "BIKE_SHOP", "BILLS_HOUSE", "BLUES_HOUSE",
    "BRUNOS_ROOM", "CELADON_CHIEF_HOUSE", "CELADON_CITY", "CELADON_DINER",
    "CELADON_GYM", "CELADON_HOTEL", "CELADON_MANSION_1F",
    "CELADON_MANSION_2F", "CELADON_MANSION_3F", "CELADON_MANSION_ROOF",
    "CELADON_MANSION_ROOF_HOUSE", "CELADON_MART_1F", "CELADON_MART_2F",
    "CELADON_MART_3F", "CELADON_MART_4F", "CELADON_MART_5F",
    "CELADON_MART_ELEVATOR", "CELADON_MART_ROOF", "CELADON_POKECENTER",
    "CERULEAN_BADGE_HOUSE", "CERULEAN_CAVE_1F", "CERULEAN_CAVE_2F",
    "CERULEAN_CAVE_B1F", "CERULEAN_CITY", "CERULEAN_GYM", "CERULEAN_MART",
    "CERULEAN_POKECENTER", "CERULEAN_TRADE_HOUSE",
    "CERULEAN_TRASHED_HOUSE", "CHAMPIONS_ROOM", "CINNABAR_GYM",
    "CINNABAR_ISLAND", "CINNABAR_LAB", "CINNABAR_LAB_FOSSIL_ROOM",
    "CINNABAR_LAB_METRONOME_ROOM", "CINNABAR_LAB_TRADE_ROOM",
    "CINNABAR_MART", "CINNABAR_POKECENTER", "COLOSSEUM",
    "COPYCATS_HOUSE_1F", "COPYCATS_HOUSE_2F", "DAYCARE", "DIGLETTS_CAVE",
    "DIGLETTS_CAVE_ROUTE_11", "DIGLETTS_CAVE_ROUTE_2", "FIGHTING_DOJO",
    "FUCHSIA_BILLS_GRANDPAS_HOUSE", "FUCHSIA_CITY",
    "FUCHSIA_GOOD_ROD_HOUSE", "FUCHSIA_GYM", "FUCHSIA_MART",
    "FUCHSIA_MEETING_ROOM", "FUCHSIA_POKECENTER", "GAME_CORNER",
    "GAME_CORNER_PRIZE_ROOM", "HALL_OF_FAME", "INDIGO_PLATEAU",
    "INDIGO_PLATEAU_LOBBY", "LANCES_ROOM", "LAVENDER_CUBONE_HOUSE",
    "LAVENDER_MART", "LAVENDER_POKECENTER", "LAVENDER_TOWN",
    "LORELEIS_ROOM", "MR_FUJIS_HOUSE", "MR_PSYCHICS_HOUSE", "MT_MOON_1F",
    "MT_MOON_B1F", "MT_MOON_B2F", "MT_MOON_POKECENTER", "MUSEUM_1F",
    "MUSEUM_2F", "NAME_RATERS_HOUSE", "OAKS_LAB", "PALLET_TOWN",
    "PEWTER_CITY", "PEWTER_GYM", "PEWTER_MART", "PEWTER_NIDORAN_HOUSE",
    "PEWTER_POKECENTER", "PEWTER_SPEECH_HOUSE", "POKEMON_FAN_CLUB",
    "POKEMON_MANSION_1F", "POKEMON_MANSION_2F", "POKEMON_MANSION_3F",
    "POKEMON_MANSION_B1F", "POKEMON_TOWER_1F", "POKEMON_TOWER_2F",
    "POKEMON_TOWER_3F", "POKEMON_TOWER_4F", "POKEMON_TOWER_5F",
    "POKEMON_TOWER_6F", "POKEMON_TOWER_7F", "POWER_PLANT",
    "REDS_HOUSE_1F", "REDS_HOUSE_2F", "ROCKET_HIDEOUT_B1F",
    "ROCKET_HIDEOUT_B2F", "ROCKET_HIDEOUT_B3F", "ROCKET_HIDEOUT_B4F",
    "ROCKET_HIDEOUT_ELEVATOR", "ROCK_TUNNEL_1F", "ROCK_TUNNEL_B1F",
    "ROCK_TUNNEL_POKECENTER", "ROUTE_1", "ROUTE_10", "ROUTE_11",
    "ROUTE_11_GATE_1F", "ROUTE_11_GATE_2F", "ROUTE_12",
    "ROUTE_12_GATE_1F", "ROUTE_12_GATE_2F", "ROUTE_12_SUPER_ROD_HOUSE",
    "ROUTE_13", "ROUTE_14", "ROUTE_15", "ROUTE_15_GATE_1F",
    "ROUTE_15_GATE_2F", "ROUTE_16", "ROUTE_16_FLY_HOUSE",
    "ROUTE_16_GATE_1F", "ROUTE_16_GATE_2F", "ROUTE_17", "ROUTE_18",
    "ROUTE_18_GATE_1F", "ROUTE_18_GATE_2F", "ROUTE_19", "ROUTE_2",
    "ROUTE_20", "ROUTE_21", "ROUTE_22", "ROUTE_22_GATE", "ROUTE_23",
    "ROUTE_24", "ROUTE_25", "ROUTE_2_GATE", "ROUTE_2_TRADE_HOUSE",
    "ROUTE_3", "ROUTE_4", "ROUTE_5", "ROUTE_5_GATE", "ROUTE_6",
    "ROUTE_6_GATE", "ROUTE_7", "ROUTE_7_GATE", "ROUTE_8", "ROUTE_8_GATE",
    "ROUTE_9", "SAFARI_ZONE_CENTER", "SAFARI_ZONE_CENTER_REST_HOUSE",
    "SAFARI_ZONE_EAST", "SAFARI_ZONE_EAST_REST_HOUSE", "SAFARI_ZONE_GATE",
    "SAFARI_ZONE_NORTH", "SAFARI_ZONE_NORTH_REST_HOUSE",
    "SAFARI_ZONE_SECRET_HOUSE", "SAFARI_ZONE_WEST",
    "SAFARI_ZONE_WEST_REST_HOUSE", "SAFFRON_CITY", "SAFFRON_GYM",
    "SAFFRON_MART", "SAFFRON_PIDGEY_HOUSE", "SAFFRON_POKECENTER",
    "SEAFOAM_ISLANDS_1F", "SEAFOAM_ISLANDS_B1F", "SEAFOAM_ISLANDS_B2F",
    "SEAFOAM_ISLANDS_B3F", "SEAFOAM_ISLANDS_B4F", "SILPH_CO_10F",
    "SILPH_CO_11F", "SILPH_CO_1F", "SILPH_CO_2F", "SILPH_CO_3F",
    "SILPH_CO_4F", "SILPH_CO_5F", "SILPH_CO_6F", "SILPH_CO_7F",
    "SILPH_CO_8F", "SILPH_CO_9F", "SILPH_CO_ELEVATOR", "SS_ANNE_1F",
    "SS_ANNE_1F_ROOMS", "SS_ANNE_2F", "SS_ANNE_2F_ROOMS", "SS_ANNE_3F",
    "SS_ANNE_B1F", "SS_ANNE_B1F_ROOMS", "SS_ANNE_BOW",
    "SS_ANNE_CAPTAINS_ROOM", "SS_ANNE_KITCHEN", "TRADE_CENTER",
    "UNDERGROUND_PATH_NORTH_SOUTH", "UNDERGROUND_PATH_ROUTE_5",
    "UNDERGROUND_PATH_ROUTE_6", "UNDERGROUND_PATH_ROUTE_7",
    "UNDERGROUND_PATH_ROUTE_8", "UNDERGROUND_PATH_WEST_EAST",
    "VERMILION_CITY", "VERMILION_DOCK", "VERMILION_GYM", "VERMILION_MART",
    "VERMILION_OLD_ROD_HOUSE", "VERMILION_PIDGEY_HOUSE",
    "VERMILION_POKECENTER", "VERMILION_TRADE_HOUSE", "VICTORY_ROAD_1F",
    "VICTORY_ROAD_2F", "VICTORY_ROAD_3F", "VIRIDIAN_CITY",
    "VIRIDIAN_FOREST", "VIRIDIAN_FOREST_NORTH_GATE",
    "VIRIDIAN_FOREST_SOUTH_GATE", "VIRIDIAN_GYM", "VIRIDIAN_MART",
    "VIRIDIAN_NICKNAME_HOUSE", "VIRIDIAN_POKECENTER",
    "VIRIDIAN_SCHOOL_HOUSE", "WARDENS_HOUSE"]
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
# NO SHOP_STOCK TABLE. Which mart sells what is a fact about the WORLD, not
# about how to spell things, and the run now learns it the honest way: the
# journal reports "is not sold here" and "cannot afford POTION: it costs 300
# and you have 83" from real counters it walked to. The table existed because
# unsatisfiable shopping goals used to burn whole attempts; that evidence
# channel replaced it.

# NO CURATED MILESTONE LIST. Which events "matter" is exactly the judgement
# this project leaves to the model, and a hand-picked seven said the Super
# Nerd counts while Nugget Bridge and Bill do not — a claim we had no right
# to make, and one we only knew to make because an earlier run discovered
# it. So: the model may name ANY flag the engine defines (its own knowledge
# of Red picks which), validation only checks the string is real, and the
# only flags the PROMPT volunteers are the ones this run has watched fire,
# which observed_text already reports under WHERE EVENTS ACTUALLY FIRED.
def _engine_names(fname: str) -> set:
    try:
        p = Path(__file__).with_name(fname)
        return {l.strip() for l in p.read_text().splitlines() if l.strip()}
    except OSError:
        return set()


ENGINE_FLAGS = _engine_names("engine_flags.txt")
# Every item id the engine defines (data/generated/items.lua), for the same
# reason ENGINE_FLAGS exists: KEY_ITEMS is a seven-entry spelling aid, and
# using it as the whole has_item universe made "I have the fossil" — the
# RIGHT condition for a fossil leg — unwritable in any spelling. The model
# may name any real item; validation only checks the string is real.
ENGINE_ITEMS = _engine_names("engine_items.txt")

BADGES = ["BOULDERBADGE", "CASCADEBADGE", "THUNDERBADGE",
          "RAINBOWBADGE", "SOULBADGE", "MARSHBADGE", "VOLCANOBADGE",
          "EARTHBADGE"]

SYS = """You author a PLAN to accomplish a Pokemon Red goal: an ordered list
of SUBGOALS. You write the decomposition and the success condition of each
step; a separate system will later figure out the exact button/op sequence
for each subgoal by playing. So you do NOT give coordinates or ops here — you
give the milestones and how to know each is done.

WHAT GOES IN THE PLAN IS YOURS. Nothing here tells you the route, which
places matter, what to buy, when to heal, when to train, or what order to
do any of it in — you know this game. The evidence below is only what THIS
run has actually walked and what happened when it did. Author the plan you
think wins, and revise it from that evidence when it does not.

AMBIGUOUS MAPS: a {"map": X} done_when is satisfied ANYWHERE on that map,
and some maps are split into disconnected areas you cannot walk between
(caves with separate wings, routes divided by a mountain or a ledge). So
whenever a subgoal RETURNS to a map an earlier subgoal already reached —
you will see the same map id twice in your list — {"map": X} cannot tell
the two arrivals apart and the second subgoal is already "done" the moment
it starts. The fix is {"area": "MAP|region"} — an area code names ONE
walkable room of that map, so it can tell the two arrivals apart. The
observed evidence below lists the area codes already walked, with the
doors between them; pick the code for the part you actually mean (the far
side of the mountain, the room with the exit east). Use "player_at" only
when no area code covers the spot you need — a coordinate you have never
stood on is a guess, while an area code is a place you have been.

Hard rule on GRANULARITY: each subgoal must be ONE map transition, OR one
event/interaction that happens within a single map. Do not bundle multiple
map changes into one subgoal: walking through three maps to reach a town is
three subgoals, and "go to the shop and buy potions" is two — arrive, then
buy.

Each subgoal is an object:
  {"id":"snake_case_name",
   "goal_text":"one or two sentences telling the player exactly what to do",
   "done_when":{<one predicate>}}

Reply with ONLY a JSON object: {"goal":"...","subgoals":[ ... ]}."""


# WHERE the player is, not what to do about it. "Your FIRST subgoals must
# get them out of the house (downstairs, then out the front door)" was the
# opening of a walkthrough — the one part of the route the model was never
# allowed to work out. The map id and the empty party are on screen.
NEW_GAME_START = (
    "a brand-new game — the player is upstairs in a house "
    "(map REDS_HOUSE_2F) with no Pokemon and nothing in the bag.")


def build_prompt(goal: str, start: str | None = None) -> str:
    return (
        f"GOAL: {goal}\n\n"
        f"STARTING STATE: {start or NEW_GAME_START}\n\n"
        f"PREDICATES you may use in done_when (pick the ONE that best marks "
        f"the subgoal complete):\n"
        + "\n".join(f"  {k}: {v}" for k, v in PREDICATES.items())
        + "\n\nMAP IDs on this route (use exact strings):\n  "
        + ", ".join(ROUTE_MAPS)
        + "\n\nEVENT FLAGS: you may use {\"flag\": \"EVENT_...\"} for a "
          "milestone that is not just a map change, spelled the way this "
          "game spells it. Which events matter is YOUR call — the evidence "
          "below lists the ones this run has actually watched fire, and "
          "your own knowledge of the game covers the rest. A flag name that "
          "the game does not define will be rejected."
        + "\n\nITEM IDs: has_item takes ANY item this game defines, spelled "
          "the way it spells it — a wrong spelling is rejected with close "
          "matches to pick from. The spelling traps among the common ones:\n"
        + "\n".join(f"  {k}: {v}" for k, v in KEY_ITEMS.items())
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
                    if ENGINE_ITEMS and item not in ENGINE_ITEMS:
                        # cutoff 0.4: "HM01" rates only 0.4 against
                        # "HM_CUT" and the bare error left the author
                        # guessing three rounds to death
                        near = difflib.get_close_matches(
                            item, ENGINE_ITEMS, n=4, cutoff=0.4)
                        hint = (f" — did you mean {', '.join(near)}?"
                                if near else "")
                        probs.append(f"{tag} ({sid}) '{item}' is not an item "
                                     f"id this game defines{hint}")
            elif k == "flag" and ENGINE_FLAGS and v not in ENGINE_FLAGS:
                near = difflib.get_close_matches(v, ENGINE_FLAGS,
                                                 n=3, cutoff=0.6)
                hint = (f" — did you mean {', '.join(near)}?"
                        if near else "")
                probs.append(f"{tag} ({sid}) flag '{v}' is not an event this "
                             f"game defines{hint}")
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


# THE GUIDANCE AND THE EVIDENCE HAD NEVER MET. author() runs under SYS,
# which explains attrition, training, catching a backup and shopping — but
# its user message is the goal alone, so it cannot see that anything has
# gone wrong. review() is the pass handed the walked graph and the journal
# (the wipe counts, the damage race, the money) and it ran under a
# 192-character brief about structurally invalid subgoals. So the half that
# knew training was expressible was blind to the losing, and the half
# reading "WIPED OUT 19x, your hits dealt ~8/turn while theirs took ~15" had
# never been told training was an option. Same knowledge, both passes: this
# adds nothing the model was not already given elsewhere.
# ONE PARAGRAPH, FOR THE REVIEWER ONLY. Measured across two worlds: the
# AUTHOR invents training unprompted when planning forward (the clean-room
# run wrote train_in_forest {lead_level:12} with no coaching at all, and
# that is what beat Brock). The REVIEWER, revising after defeat, does not —
# it re-pins coordinates and re-issues the same approach, four rewrites
# running, against a fight the journal shows being lost six times. The
# missing step is not knowledge of the game; it is noticing that a lost
# fight is a question about what you ARRIVE WITH. This names the option
# space the DSL already gives it and leaves every choice inside it open.
REVISION_NOTE = (
    "\n\nWHEN THE JOURNAL SHOWS THE SAME FIGHT LOST OVER AND OVER, the "
    "plan's problem is not its route. A plan can be perfectly routed and "
    "still fail every time because of what it arrives WITH. The predicates "
    "can express that too: lead_level, slot_level and party_min_level raise "
    "a Pokemon by battling in grass; party_size adds one to the party; "
    "has_item buys supplies from a counter. Whether any of those is the "
    "right answer here is your judgement and the evidence is above — but "
    "re-issuing the same approach into a fight that has already been lost "
    "repeatedly is not a revision of the plan, it is a repeat of it."
    "\n\nWHEN NOTHING WALKS, THE ANSWER IS SOMETHING YOU DO. If the "
    "evidence shows a place whose roads are all proven uncrossable and "
    "whose doors are all either walked or held shut, then NO arrangement of "
    "walking can get out of it, and another route plan will fail exactly "
    "the way the last one did. A place is opened by an ACTION: talking to "
    "somebody, finishing what somebody asked you to do, operating a machine "
    "or a computer, pressing A on scenery that is not in the object list. "
    "The evidence above records what people said and which doors are held "
    "shut, and a subgoal can name an event flag as its condition. When the "
    "walking is exhausted, plan the deed."
)

REVIEW_SYS = (
    SYS
    + REVISION_NOTE
    + "\n\nYou are now REVIEWING a plan you just wrote, with EVIDENCE from "
      "runs that have already been played: the areas walked, and a journal "
      "of what actually happened. Look for subgoals that CANNOT do their "
      "job, and weigh them against that evidence. Reply with the corrected "
      "plan as a JSON object in the same schema, and nothing else."
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
    fired = [f"  {f} fired in {region}"
             for f, region in sorted((d.get("flag_sites") or {}).items())]
    hints = d.get("hints") or {}
    if hints:
        out += ("\n\nWHAT PEOPLE HAVE SAID, and where they said it. This "
                "game explains its own gates out loud, so a sentence here is "
                "often the reason a route did not work:\n"
                + "\n".join(f"  in {r}:\n    " + "\n    ".join(v[-4:])
                             for r, v in sorted(hints.items())))
    shut = d.get("shut_doors") or {}
    if shut:
        out += ("\n\nDOORS SEEN BUT NEVER OPENED (they exist on the map and "
                "somebody was standing in the way — a door does not move, "
                "so the person is what is shutting it, and people step aside "
                "once talked to). On walked ground these are the openings "
                "that can still lead somewhere new:\n"
                + "\n".join(f"  in {r}: {', '.join(v)}"
                             for r, v in sorted(shut.items())))
    if fired:
        out += ("\n\nWHERE EVENTS ACTUALLY FIRED (an event happens in ONE "
                "place, so a subgoal for it must come AFTER the subgoal "
                "that arrives there — and that arrival is best written as "
                "the area code below, not the whole map):\n"
                + "\n".join(fired))
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
    last_fight = ""
    # The damage RACE of the last fight, from the per-turn HP trace. The
    # wipe line alone read "STARYU L18 vs your CHARMELEON L24" — a level
    # ADVANTAGE — so six rewrites re-marched the same plan; that the foe's
    # hits landed twice as hard as ours is the on-screen fact that says
    # what kind of problem this is, and it never reached the author.
    dealt, taken = [], []
    prev_fh = prev_mh = None
    # The executor's own could-not-get-it conclusions, counted over the
    # whole run. These were the single most informative lines in the log —
    # "item:POKE_BALL unreachable in VIRIDIAN_MART, clerk right there,
    # 24 times" — and the tail window of wander lines pushed every one of
    # them out, so three rewrites re-shipped an enter-and-buy plan that
    # from the reviewer's seat had never been tested.
    unreach = {}
    for r in seg:
        k = r.get("kind")
        if k == "battle_turn":
            fh, mh = r.get("foe_hp"), r.get("me_hp")
            if fh is not None:
                if prev_fh is not None and 0 < prev_fh - fh <= 40:
                    dealt.append(prev_fh - fh)
                prev_fh = fh
            if mh is not None:
                if prev_mh is not None and 0 < prev_mh - mh <= 60:
                    taken.append(prev_mh - mh)
                prev_mh = mh
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
        if k == "battle_start" and r.get("foe"):
            last_fight = f" (last fight: {r.get('foe')} vs your {r.get('me')})"
            dealt, taken = [], []
            prev_fh = prev_mh = None
        if k == "subgoal_done" or k == "escalate_success":
            # A stop that was already satisfied DID nothing: the Cerulean
            # heal kept instant-passing on a blackout-healed party, so the
            # Center was never entered and every wipe teleported the run
            # back to a centre several maps west. "OK" alone hid that.
            idle = (r.get("via") == "pre-check"
                    or (k == "escalate_success" and not r.get("distilled")))
            events.append(f"  OK      {r.get('subgoal')}"
                          + (" (already true on arrival — nothing was done,"
                             " no building was entered)" if idle else ""))
        elif k == "subgoal_failed":
            events.append(f"  FAILED  {r.get('subgoal')}")
        elif k == "blackout":
            race = ""
            if dealt and taken:
                race = (f"; your hits dealt ~{round(sum(dealt)/len(dealt))}"
                        f"/turn while theirs took "
                        f"~{round(sum(taken)/len(taken))}/turn from you")
            events.append(f"  WIPED   during {r.get('subgoal')}"
                          f"{last_fight}{race} — sent to "
                          f"{r.get('respawn')}, and a blackout costs you "
                          f"HALF YOUR MONEY")
        elif k == "rerouted":
            events.append(f"  walked back to {r.get('to')} looking for a way on")
        elif k == "target_unreachable":
            key = (r.get("subgoal"), r.get("target"), r.get("region"),
                   tuple(r.get("objects") or []))
            unreach[key] = unreach.get(key, 0) + 1
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
            # A capability lock is a plan-shaped fact: "no party Pokemon
            # knows CUT — teach it first" says exactly what the next plan
            # must arrange, and it lived only in escalation feedback.
            # Once is enough — seven interleaved copies survived the
            # consecutive-collapse and buried the rest of the story.
            elif "no party Pokemon knows" in t:
                lock = f"  LOCKED  {t.split('FAILED — ')[-1][:150]}"
                if lock not in events:
                    events.append(lock)
            elif "party FAINTED" in t:
                pass
    if not events and not unreach:
        return ""
    # Collapse consecutive repeats before taking the tail: 27 identical
    # wander lines told the reviewer nothing 26 times, and cost the window
    # 26 lines of story.
    collapsed = []
    for e in events:
        if collapsed and collapsed[-1][0] == e:
            collapsed[-1][1] += 1
        else:
            collapsed.append([e, 1])
    shown = [e + (f"  (x{n})" if n > 1 else "")
             for e, n in collapsed[-limit:]]
    out = ("\n\nWHAT HAPPENED ON THE LAST RUN, in order (this is the "
           "causal story — if it ran out of money, or wiped, or failed the "
           "same step repeatedly, fix the PLAN's ordering and amounts so "
           "that cannot happen again):\n" + "\n".join(shown))
    if unreach:
        out += ("\n\nWHAT WAS TRIED AND DID NOT WORK, counted over the "
                "whole run. A deed that fails every time in the same place "
                "is a GATE — something else has to happen first, and the "
                "sentences under WHAT PEOPLE HAVE SAID often name it:\n")
        for (sg, tgt, reg, objs), n in sorted(
                unreach.items(), key=lambda kv: -kv[1])[:8]:
            who = f", with {', '.join(objs)} right there" if objs else ""
            out += (f"  during {sg}: could not get {tgt} in {reg} — "
                    f"{n} attempts{who}\n")
    return out


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
        "vocabulary above, spelled exactly.\n"
        "6. AN EVENT BEFORE THE PLACE IT HAPPENS. A flag subgoal fires "
        "somewhere specific — usually the deepest point of the route — so "
        "it must come AFTER the subgoal that arrives there. Asking for a "
        "flag that fires on the bottom floor while the party is still one "
        "floor above is unsatisfiable where it stands, and the run wastes "
        "its rounds hunting for something that is not on that floor. Order "
        "the descent first, then the event.\n"
        "7. A SUPPLY STOP IN THE WRONG PLACE. Healing and shopping happen "
        "in TOWNS and CENTRES, so a heal/buy subgoal placed after the "
        "subgoals that go deep (into a cave, down two floors) can only be "
        "satisfied by climbing all the way back out and then descending "
        "again — a round trip that eats the whole attempt. Put supply "
        "stops BEFORE the descent, next to the last outdoor step.\n"
        "8. A PLAN THAT HAS ALREADY FAILED THIS WAY. The journal above is "
        "what happened on previous attempts. If it shows the same subgoal "
        "failing over and over — the same fight lost, the same purchase "
        "refused — then a plan that reaches that subgoal in the same state "
        "will fail again for the same reason; re-running it is not a "
        "second chance, it is the same attempt. Read what the journal says "
        "went wrong and decide whether anything in the plan should change "
        "before that step. Do NOT change a step the journal shows working.\n"
        "9. ALREADY DONE. A subgoal whose outcome the START state already "
        "shows — an item already in the bag, a badge already worn, a flag "
        "already set — is a detour, not a step. REMOVE it (and any travel "
        "that exists only to serve it). Do not remove flag or badge "
        "subgoals that are still unmet: those are the events later steps "
        "depend on.\n\n"
        "Keep what is right — do not rewrite the plan for style. Return the "
        "full corrected plan."
    )


def merge_plans(orig: dict, revised: dict) -> tuple:
    """Let a revision ADD, UPDATE — and REMOVE all but the event gates.

    The original rule was add/update-never-delete: an audit run against
    thin evidence talked itself out of defeat_mt_moon_nerd — the only
    condition in the mountain leg that RETREATING cannot satisfy — leaving
    a chain of map hops that all mark themselves done by walking back out.
    But never-delete has its own failure mode (user, 2026-08-12): with the
    potions already saved in the bag, every rewrite still marched the
    party back to Pewter to shop. The load-bearing steps are exactly the
    EVENT GATES (flag/badge — things later steps depend on and retreat
    cannot satisfy); only those are restored when a revision drops them.
    Map hops, heals and shopping the audit can justify pruning are its
    call.
    """
    rev_ids = {x["id"] for x in revised["subgoals"]}
    out = list(revised["subgoals"])
    restored = []
    # THE ESCAPE HATCH. Never-delete makes a gate IMMORTAL, and a gate that
    # wandered in from a degenerate rewrite then rides every successor: a
    # leg for one badge inherited `defeat_celadon_gym_leader {RAINBOWBADGE}`
    # and carried it forever, three positions before the plan even reached
    # that city. A badge the leg does not end on is not this leg's gate — it
    # belongs to some other objective and the audit may drop it. The gate
    # the leg DOES end on, and every event flag, keep their protection.
    final = (revised.get("subgoals") or [{}])[-1].get("done_when") or {}
    own_badge = final.get("badge") if isinstance(final, dict) else None
    for i, sg in enumerate(orig["subgoals"]):
        if sg["id"] in rev_ids:
            continue
        dw = sg.get("done_when") or {}
        if (isinstance(dw, dict) and dw.get("badge")
                and own_badge and dw["badge"] != own_badge):
            continue
        if not (isinstance(dw, dict) and ("flag" in dw or "badge" in dw)):
            continue                      # non-gate: the audit may drop it
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
    # EVIDENCE FIRST, VOCABULARY LAST. An oversized prompt loses its FRONT,
    # and the graph and the journal both grow all run, so the cap comes back
    # however high num_ctx is set. Ordering decides what dies when it does:
    # with the predicates, map ids and guidance at the front they were the
    # first casualty, which is how a review reached for a heal and invented
    # `party_hp`. Put the droppable stuff — old walked edges, old journal
    # lines — at the front, and keep the vocabulary next to the audit
    # instructions at the tail where truncation cannot reach either.
    base = ((observed_text(observed) if observed else "")
            + (journal_text(journal) if journal else "")
            + build_prompt(goal, start))
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



OUTLINE_SYS = """You are laying out a PLAYTHROUGH of Pokemon Red as an
ordered list of OBJECTIVES. Each objective becomes its own plan, written
later and played separately, so each one must be a thing that is either done
or not done — a milestone you could tell someone you had reached.

Write them as short phrases in the player's own terms. Do NOT number them,
do not explain them, and do not write the steps inside them — the steps are
authored later, from the objective alone.

What counts as an objective is YOURS to decide. Badges are the obvious ones;
they are not the only ones. Anything the game will not let you past until it
is done, anything you must be given before somewhere opens, and anything you
must do for somebody, are all objectives in their own right — a playthrough
that lists only the badges is missing the reasons you were able to reach
them.

Expect about TWENTY objectives. If you have far fewer, you have folded
several into one and skipped the errands between the badges — unfold them.

Reply with ONLY a JSON array of strings."""


# Doubts the outline passes record about their own product, persisted next
# to outline.txt so the leg author sees them when that leg comes up. The
# note is the model's own words fed back to itself — not our knowledge.
OUTLINE_NOTES = []


def _outline_draw(goal: str, model: str, rounds: int = 3) -> list | None:
    for _ in range(rounds):
        reply = brock_probe.chat(
            [{"role": "system", "content": OUTLINE_SYS},
             {"role": "user", "content": f"THE GOAL: {goal}\n\n"
              f"List the objectives, in the order you would do them."}],
            model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            continue
        try:
            legs = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        legs = [str(x).strip() for x in legs
                if isinstance(x, (str, int, float)) and str(x).strip()]
        if len(legs) >= 3:
            return legs
    return None


def outline(goal: str, model: str, rounds: int = 3,
            draws: int = 3) -> list | None:
    """The MODEL decides what the legs are.

    Handing it "win your first/second/third badge" is our decomposition of
    the game, not its own, and it quietly rules out the objectives that are
    not badges — deliver the parcel, help Bill, get the ticket, learn a
    field move. Those are exactly the ones a run gets stuck behind, and a
    leg it never names is a plan it never writes.

    One draw is high-variance — the same prompt gave nine non-badge
    objectives one day and none the next — so we take several and let the
    model compose the final list from its own drafts (_outline_merge).
    """
    OUTLINE_NOTES.clear()
    drafts = []
    for i in range(draws):
        d = _outline_draw(goal, model, rounds)
        if d:
            print(f"[outline] draft {len(drafts) + 1}: {len(d)} objectives")
            drafts.append(d)
    if not drafts:
        return None
    if len(drafts) == 1:
        legs = drafts[0]
    else:
        legs = _outline_merge(goal, drafts, model)
        if not legs:
            print("[outline] merge unusable, keeping draft 1")
            legs = drafts[0]
    return _outline_review(goal, legs, model) or legs


OUTLINE_MERGE_SYS = """You wrote several drafts of a Pokemon Red
playthrough outline, in separate sittings. Different sittings remembered
different things; no single draft is the whole of what you know.

Below is every objective from every draft, numbered, with how many drafts
it appeared in. Compose the final outline by CHOOSING from that list —
reply with ONLY a JSON array of numbers, in the order the objectives
should be played.

Keep what you believe, whichever draft it came from. Something only one
draft remembered can still be the thing the game will not let you past —
count is how often you said it, not how true it is.

When several entries name the SAME thing in different words, keep exactly
one of them — dropping the whole cluster loses the thing itself. Leave a
thing out only when you no longer believe the thing. Expect to keep about
twenty."""


def _outline_merge(goal: str, drafts: list, model: str) -> list | None:
    """The model composes the final outline from its own drafts.

    Choose-only, same hands-tying as _outline_review: the reply is a list
    of menu numbers, mapped back to verbatim draft text by the harness, so
    the merge can select and order but never invent or reword. The
    review's insertion channel, which runs after this, stays the only way
    anything new enters — and it logs.
    """
    menu, seen = [], {}
    for d in drafts:
        for leg in d:
            k = leg.lower()
            if k in seen:
                seen[k] += 1
            else:
                seen[k] = 1
                menu.append(leg)
    lines = "\n".join(
        f"  {i}. {leg}   (in {seen[leg.lower()]} of {len(drafts)} drafts)"
        for i, leg in enumerate(menu, 1))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": OUTLINE_MERGE_SYS},
             {"role": "user", "content": f"THE GOAL: {goal}\n\n"
              f"EVERY OBJECTIVE YOU WROTE:\n{lines}"}],
            model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            return None
        picks = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return None
    by_text = {leg.lower(): leg for leg in menu}
    out = []
    for p in picks:
        leg = None
        if isinstance(p, str) and p.strip().isdigit():
            p = int(p)
        if isinstance(p, (int, float)) and 1 <= int(p) <= len(menu):
            leg = menu[int(p) - 1]
        elif isinstance(p, str):
            leg = by_text.get(p.strip().lower())
            if leg is None:
                print(f"[outline] merge pick not on the menu, "
                      f"dropped: {p.strip()!r}")
        if leg and leg not in out:
            out.append(leg)
    if len(out) < 3:
        return None
    dropped = [leg for leg in menu if leg not in out]
    print(f"[outline] merged {len(drafts)} drafts: "
          f"{len(menu)} distinct -> kept {len(out)}")
    for leg in dropped:
        print(f"[outline]   left out: {leg!r}")
    majority = len(drafts) // 2 + 1
    doubts = [d for d in dropped if seen[d.lower()] >= majority]
    if doubts:
        out = _merge_confirm(goal, out, doubts, len(drafts), seen,
                             model) or out
    return out


MERGE_CONFIRM_SYS = """You composed a final Pokemon Red playthrough
outline from your own drafts, and in doing so you left out objectives that
MOST of your drafts had included. Leaving them out may be right — a thing
said three ways only needs saying once — but it must be on purpose.

For each left-out objective, either put it back or let it go. Reply with
ONLY a JSON array; each element is {"item": "A", "after": N} to put that
item back after outline position N (0 = before everything). Any item you
do not mention stays out, for good."""


def _merge_confirm(goal: str, out: list, doubts: list, ndrafts: int,
                   seen: dict, model: str) -> list | None:
    """Consensus items can be dropped, but never silently.

    The merge under count pressure dropped "Defeat Erika" whole — an
    objective all three drafts agreed on — while keeping duplicate badge
    entries. Dupes are near-free (an already-done leg completes
    instantly); a lost consensus leg walls the campaign. So the harness
    asks one pointed question and applies the answer verbatim: it never
    restores anything itself.
    """
    letters = [chr(ord("A") + i) for i in range(len(doubts))]
    body = (f"THE GOAL: {goal}\n\nYOUR FINAL OUTLINE:\n"
            + "\n".join(f"  {i}. {leg}" for i, leg in enumerate(out, 1))
            + "\n\nLEFT OUT, though most drafts had them:\n"
            + "\n".join(
                f"  {c}. {d}   (in {seen[d.lower()]} of {ndrafts} drafts)"
                for c, d in zip(letters, doubts)))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": MERGE_CONFIRM_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            return None
        answers = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return None
    if not isinstance(answers, list):
        return None
    result = list(out)
    restored = set()
    for a in answers:
        if not isinstance(a, dict):
            continue
        c = str(a.get("item") or "").strip().upper()
        if c not in letters or c in restored:
            continue
        leg = doubts[letters.index(c)]
        try:
            after = int(a.get("after") or 0)
        except (TypeError, ValueError):
            after = 0
        if after < 1:
            pos, where = 0, "at the start"
        elif after > len(out):
            pos, where = len(result), "at the end"
        else:
            pos = result.index(out[after - 1]) + 1
            where = f"after {out[after - 1]!r}"
        result.insert(pos, leg)
        restored.add(c)
        print(f"[outline] restored {leg!r} {where}")
    for c, d in zip(letters, doubts):
        if c not in restored:
            print(f"[outline] left out on purpose: {d!r}")
            OUTLINE_NOTES.append(
                (d, f"left out on purpose when composing the outline, "
                    f"though {seen[d.lower()]} of {ndrafts} drafts had it"))
    return result


OUTLINE_REVIEW_SYS = """You are checking the ORDER of a Pokemon Red
playthrough outline that you just wrote, before any of it is played.

You cannot rewrite the outline. Objectives in the wrong order you may move,
and objectives you doubt you may flag, and that is all — if the outline is
wrong in a way only playing would reveal, playing is allowed to reveal it.

Reply with ONLY a JSON object:
{"before": [{"first": N, "then": M, "why": "..."}],
 "missing": [{"after": N, "objective": "...", "why": "..."}],
 "suspect": [{"n": N, "why": "..."}]}

"before" lists pairs where objective number N must be FINISHED before
number M can be done — because N hands you the thing, the move, or the
permission that M needs. Only list pairs the current order gets wrong or
leaves to luck; empty means the order stands.

"missing" names objectives the outline skipped: things the game will not
let you past until they are done, that no listed objective covers — a
person who must be helped, a thing that must be fetched, a way that must
be opened. Each is inserted after objective number N (0 = before
everything). Name gates you know are there, not padding.

"suspect" flags objectives you no longer believe: not in this game, the
direction backwards ("give X to Y" when it is Y who gives you X), or the
same thing twice under two names. Flagged objectives are KEPT and tried
anyway — the flag is a note to whoever writes that plan, not a deletion."""


def _outline_review(goal: str, legs: list, model: str) -> list | None:
    """A second pass that can REORDER the outline but never rewrite it.

    The free-rewrite audit was measured net-negative on a cold outline:
    with no play evidence to check against, the rewrite is a second guess
    at recall, and it deleted the one objective (Bill) the badge
    decomposition had been suppressing. So the reviewer's hands are tied
    structurally — it emits ordering claims and doubts, the harness
    applies a stable topological sort, and every objective survives with
    its wording intact. A wrong leg discovered in play is recoverable
    (the campaign rewrites failed legs); a right leg deleted before play
    is just gone.
    """
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": OUTLINE_REVIEW_SYS},
             {"role": "user", "content": f"THE GOAL: {goal}\n\n"
              f"THE OUTLINE YOU WROTE:\n"
              + "\n".join(f"  {i}. {l}" for i, l in enumerate(legs, 1))}],
            model)
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            return None
        verdict = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return None
    if not isinstance(verdict, dict):
        return None
    n = len(legs)
    edges = []

    def _reaches(a: int, b: int) -> bool:
        seen, stack = set(), [a]
        while stack:
            x = stack.pop()
            if x == b:
                return True
            if x in seen:
                continue
            seen.add(x)
            stack.extend(t for f, t in edges if f == x)
        return False

    for c in verdict.get("before") or []:
        try:
            f, t = int(c["first"]) - 1, int(c["then"]) - 1
        except (TypeError, KeyError, ValueError):
            continue
        if not (0 <= f < n and 0 <= t < n) or f == t:
            continue
        if _reaches(t, f):
            print(f"[outline] dropped a constraint that loops: "
                  f"{legs[f]!r} before {legs[t]!r}")
            continue
        edges.append((f, t))
        why = c.get("why") or ""
        print(f"[outline] {legs[f]!r} before {legs[t]!r}"
              + (f" — {why}" if why else ""))
    for s in verdict.get("suspect") or []:
        try:
            i = int(s["n"]) - 1
        except (TypeError, KeyError, ValueError):
            continue
        if 0 <= i < n:
            why = s.get("why") or ""
            print(f"[outline] doubted, kept: {legs[i]!r}"
                  + (f" — {why}" if why else ""))
            OUTLINE_NOTES.append(
                (legs[i], why or "doubted at outline time"))
    order = list(range(n))
    if edges:
        order, remaining = [], list(range(n))
        while remaining:
            i = next(i for i in remaining
                     if not any(f in remaining for f, t in edges if t == i))
            remaining.remove(i)
            order.append(i)
        if order != list(range(n)):
            print("[outline] reordered:")
            for pos, i in enumerate(order):
                print(f"  {'*' if pos != i else ' '} {legs[i]}")
    out = [legs[i] for i in order]
    added, bumped = 0, {}
    for a in verdict.get("missing") or []:
        if not isinstance(a, dict):
            continue
        txt = str(a.get("objective") or "").strip()
        if not txt or any(txt.lower() == x.lower() for x in out):
            continue
        if added >= 6:
            print(f"[outline] insertion cap hit, dropped: {txt!r}")
            continue
        try:
            after = int(a.get("after") or 0)
        except (TypeError, ValueError):
            after = 0
        if 1 <= after <= n:
            pos = out.index(legs[after - 1]) + 1 + bumped.get(after, 0)
            bumped[after] = bumped.get(after, 0) + 1
            where = f"after {legs[after - 1]!r}"
        else:
            pos = 0 if after <= 0 else len(out)
            where = "at the start" if after <= 0 else "at the end"
        out.insert(pos, txt)
        added += 1
        why = a.get("why") or ""
        print(f"[outline] inserted {txt!r} {where}"
              + (f" — {why}" if why else ""))
    return out


BLOCKER_SYS = """A Pokemon Red playthrough leg is STUCK, and the question
is whether it is stuck because a LATER leg of your own outline has to
happen FIRST. Read what the run hit, look at the legs still ahead, and
answer with ONLY {"why": "<one sentence weighing the evidence>",
"pull_forward": N} — the number of the one later leg whose objective the
stuck leg cannot do without — or {"why": "...", "pull_forward": null} if
the stuck leg fails for some other reason. Write the why FIRST: the
bare-verdict schema was tested and it suppressed a one-hop inference the
sentence of reasoning recovered. You are choosing from your own outline,
not writing new legs."""


def check_blocker(goal: str, ahead: list, start: str, journal: str,
                  model: str):
    """The model reorders its own outline when play proves it misordered.

    The Surge leg walled on a bush only CUT clears while the model's own
    outline held "Obtain the HM for Cut" two legs later — four rewrites
    marched back to the gym because a leg cannot reach outside itself.
    The outline is where that knowledge lives, so the outline is what has
    to move, and the model authored it, so the model moves it: the
    harness asks one question and applies a pull-forward, choose-only.
    """
    body = (f"THE STUCK LEG: {goal}\n\n"
            f"WHERE THE RUN STANDS: {start}\n"
            f"{journal}\n\nTHE LEGS STILL AHEAD:\n"
            + "\n".join(f"  {n}. {t}" for n, t in ahead))
    reply = brock_probe.chat(
        [{"role": "system", "content": BLOCKER_SYS},
         {"role": "user", "content": body}], model)
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None
    try:
        n = json.loads(m.group(0)).get("pull_forward")
    except (ValueError, AttributeError):
        return None
    if isinstance(n, (int, float)) and any(int(n) == a for a, _ in ahead):
        return int(n)
    return None


CHECKDONE_SYS = """You are judging whether a Pokemon Red objective is
ALREADY accomplished, going by where the run now stands. Trust what is in
hand and what has happened over what the wording seems to ask for next —
an objective is about its outcome, not about ceremony after the outcome.
Reply with ONLY {"why": "<one sentence>", "done": true} or
{"why": "<one sentence>", "done": false} — the why comes first."""


def check_done(goal: str, start: str, model: str) -> bool:
    """The model judges whether a failed leg's objective is already met.

    A leg can fail on a subgoal long after its aim is achieved: the fossil
    leg walked out of Mt Moon HOLDING the fossil and then failed three
    rewrites trying to condition on reviving it. No mechanical check can
    know that "Retrieve the MT Moon fossil" is satisfied by HELIX_FOSSIL
    x1 in the bag — which fact means which objective is exactly the
    judgment this project leaves to the model. The harness only asks, and
    only applies the answer.
    """
    reply = brock_probe.chat(
        [{"role": "system", "content": CHECKDONE_SYS},
         {"role": "user", "content": f"THE OBJECTIVE: {goal}\n\n"
          f"WHERE THE RUN STANDS: {start}"}], model)
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return False
    try:
        return bool(json.loads(m.group(0)).get("done"))
    except (ValueError, AttributeError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--outline", action="store_true",
                    help="write the model's own list of objectives instead "
                         "of a subgoal plan (one line per leg)")
    ap.add_argument("--check-done", action="store_true",
                    help="ask the model whether --goal is already "
                         "accomplished at --start; exit 0 yes, 3 no")
    ap.add_argument("--check-blocker", action="store_true",
                    help="ask the model whether a later outline leg must "
                         "come before the stuck --goal; prints the leg "
                         "number and exits 0, or exits 3")
    ap.add_argument("--outline-path", type=Path, default=None)
    ap.add_argument("--leg", type=int, default=None,
                    help="1-based outline position of the stuck leg")
    ap.add_argument("--draws", type=int, default=3,
                    help="outline drafts to take before the model composes "
                         "the final list from them (default 3)")
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
    if args.check_done:
        done = check_done(args.goal, args.start or "a brand new game",
                          args.model)
        print("DONE" if done else "NOT_DONE")
        sys.exit(0 if done else 3)
    if args.check_blocker:
        if not (args.outline_path and args.leg):
            ap.error("--check-blocker needs --outline-path and --leg")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        ahead = [(n, lines[n - 1])
                 for n in range(args.leg + 1, len(lines) + 1)]
        if not ahead:
            sys.exit(3)
        jt = journal_text(args.journal) if args.journal else ""
        n = check_blocker(args.goal, ahead, args.start or "", jt,
                          args.model)
        if n:
            print(n)
            sys.exit(0)
        sys.exit(3)
    if args.out is None:
        ap.error("--out is required except with --check-done")
    if args.outline:
        legs = outline(args.goal, args.model, draws=args.draws)
        if not legs:
            sys.exit("author failed to produce an outline")
        args.out.write_text("\n".join(legs) + "\n")
        notes = args.out.with_suffix(".notes")
        if OUTLINE_NOTES:
            notes.write_text("".join(
                f"{leg}\t{' '.join(note.split())}\n"
                for leg, note in OUTLINE_NOTES))
            print(f"wrote {notes} ({len(OUTLINE_NOTES)} notes)")
        else:
            # a stale sidecar must never attach old doubts to a new outline
            notes.unlink(missing_ok=True)
        print(f"wrote {args.out} ({len(legs)} objectives)")
        for i, l in enumerate(legs, 1):
            print(f"  {i}. {l}")
        return
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
