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
def _engine_flags() -> set:
    try:
        p = Path(__file__).with_name("engine_flags.txt")
        return {l.strip() for l in p.read_text().splitlines() if l.strip()}
    except OSError:
        return set()


ENGINE_FLAGS = _engine_flags()

BADGES = ["BOULDERBADGE", "CASCADEBADGE", "THUNDERBADGE",
          "RAINBOWBADGE", "SOULBADGE", "MARSHBADGE", "VOLCANOBADGE",
          "EARTHBADGE"]

SYS = """You author a PLAN to accomplish a Pokemon Red goal: an ordered list
of SUBGOALS. You write the decomposition and the success condition of each
step; a separate system will later figure out the exact button/op sequence
for each subgoal by playing. So you do NOT give coordinates or ops here — you
give the milestones and how to know each is done.

ATTRITION: battles chip your party's HP and there is no auto-healing —
insert a Pokemon Center heal stop (done_when {"party_healthy": true}) before
long wild-encounter stretches. If upcoming trainers
outlevel your party — or the SAME fight keeps wiping you even at a level
advantage, which means the damage race is what you are losing, not the
levels — add TRAINING subgoals on a grassy route
(done_when {"lead_level": N}) — and STAGE long grinds: a few levels per
subgoal with a Pokemon Center heal stop between stages. Fainting sends
you home and HALVES YOUR MONEY, so wipes during long unhealed grinds
bankrupt later shopping.
Marts sell healing items: add a SHOPPING subgoal
(done_when {"has_item": {...}}) before a trainer gauntlet with no Center
inside it. Not every mart stocks every item, and a counter that does not
sell what you asked for says so — read the journal below for what previous
attempts actually found on the shelves.
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
it starts. The fix is {"area": "MAP|region"} — an area code names ONE
walkable room of that map, so it can tell the two arrivals apart. The
observed evidence below lists the area codes already walked, with the
doors between them; pick the code for the part you actually mean (the far
side of the mountain, the room with the exit east). Use "player_at" only
when no area code covers the spot you need — a coordinate you have never
stood on is a guess, while an area code is a place you have been.

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
        + "\n\nEVENT FLAGS: you may use {\"flag\": \"EVENT_...\"} for a "
          "milestone that is not just a map change, spelled the way this "
          "game spells it. Which events matter is YOUR call — the evidence "
          "below lists the ones this run has actually watched fire, and "
          "your own knowledge of the game covers the rest. A flag name that "
          "the game does not define will be rejected."
        + "\n\nITEM IDs (use exact strings in has_item):\n"
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
                    if item not in KEY_ITEMS:
                        probs.append(f"{sg.get('id')}: unknown item {item!r} "
                                     f"(valid: {', '.join(KEY_ITEMS)})")
            elif k == "flag" and ENGINE_FLAGS and v not in ENGINE_FLAGS:
                probs.append(f"{tag} ({sid}) flag '{v}' is not an event this "
                             f"game defines")
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
REVIEW_SYS = (
    SYS
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
    for i, sg in enumerate(orig["subgoals"]):
        if sg["id"] in rev_ids:
            continue
        dw = sg.get("done_when") or {}
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
