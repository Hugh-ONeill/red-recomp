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
  - the granularity rule: ONE event/interaction per subgoal, but TRAVEL over
    walked ground is a single subgoal naming the destination. The old rule
    ("one map transition each") dates from an executor that could not cross
    maps by itself; it now routes between milestones and prices roads that
    have never opened, so a road-by-road plan only pins it to the shut gate
    the model happened to name

Usage:
  author.py --goal "Get the Boulder Badge from Brock" --out plans/brock.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
import sys
from pathlib import Path

import brock_probe   # reuse chat()

# EVERY MODE THE SHIM CAN ACTUALLY REPORT, read out of the shim so the two
# cannot drift. `mode` was the one predicate whose values were freeform:
# every other vocabulary in this file is enumerated and spell-checked —
# map ids, flags, items, moves, species, types — while the mode
# description said only 'obs mode equals VALUE (usually "overworld")' and
# named none of them.
#
# So run 10 wrote {"mode": "pc"} for "Access the PC for the first time",
# which is the obvious guess and is not one of the five. The plan
# validated, ran four attempts, and every rung of the ladder was spent on
# it — check-done said NOT_DONE, check-wording said "the wording stands",
# check-later said "stays where it is" — and THE CHAIN STOPPED THERE. The
# run had in fact opened the PC: the trace carries its reply, "What? There
# are no POKéMON here!". The deed was done and no predicate on offer could
# say so, because the one the model reached for does not exist.
# A condition that can never be true is the most expensive kind of typo,
# and this is the same rejection every other vocabulary already gets.
def _shim_modes() -> tuple:
    try:
        src = (Path(__file__).parent.parent / "harness" / "shim.lua").read_text()
    except OSError:
        src = ""
    found = tuple(dict.fromkeys(re.findall(r'o\.mode = "([a-z]+)"', src)))
    # never let an unreadable shim silently disable the check
    return found or ("overworld", "battle", "dialog", "ui", "boot")


OBS_MODES = _shim_modes()


# EVERY UI SCREEN THE ENGINE PUSHES BY NAME, read out of the engine for the
# same reason the modes are read out of the shim: a copy drifts, and drift
# is what put an impossible predicate in five consecutive plans.
#
# `mode` can only say that SOME menu is open. The engine gives each screen
# an id (Screens.push(Game, "BoxMenu")) and the shim has always passed it
# through as ui.screenId — nothing could test it, so "access the PC" was
# inexpressible and the model reached for {"mode":"pc"}. This is the
# vocabulary that makes it sayable.
def _engine_screens() -> tuple:
    try:
        src = ""
        root = Path.home() / "Developer" / "gen1recomp" / "src"
        for p in root.rglob("*.lua"):
            src += p.read_text(errors="ignore")
    except OSError:
        src = ""
    found = tuple(sorted(set(
        re.findall(r'Screens\.push\(\s*\w+\s*,\s*"([A-Za-z]+)"', src))))
    # an unreadable engine must not silently accept anything
    return found or ("BoxMenu", "DexEntryMenu", "PlayerPC", "ShopMenu",
                     "SlotMachine", "StartMenu")


UI_SCREENS = _engine_screens()


# The vocabulary the decomposition may reference. Predicates come from the
# executor's DSL; maps/flags are the executor's instrumentation, exposed here
# so the model can name done_when conditions exactly.
PREDICATES = {
    "map": "current map id equals VALUE (e.g. {\"map\":\"PEWTER_CITY\"})",
    "screen": "a particular UI screen is open (e.g. {\"screen\":\"BoxMenu\"} "
              "for the Pokemon storage in a PC, {\"screen\":\"PlayerPC\"} "
              "for its item storage). This is the one that can name a "
              "SPECIFIC machine or menu, which \"mode\" cannot — every menu "
              "in the game reports mode \"ui\". The screens that exist are: "
              + ", ".join(UI_SCREENS),
    "mode": "obs mode equals VALUE, and the ONLY values that exist are "
            + ", ".join(f'"{m}"' for m in OBS_MODES)
            + " (usually \"overworld\"). A mode says WHAT KIND of screen is "
              "up and never WHICH ONE or WHOSE: a PC, a shop counter and a "
              "naming box are all \"ui\", and every person in the game "
              "speaks in \"dialog\", so neither can mark a subgoal about "
              "one particular machine or one particular person. And "
              "\"dialog\" can never be TRUE when a condition is tested: "
              "conditions are checked once the game has settled, and "
              "settling rides plain text to the next decision, so the box "
              "has always closed by then. Mark a conversation that matters "
              "by what it CHANGED — an event flag, an item, a party "
              "member — not by the box it was said in",
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
    "knows_move": "a party Pokemon knows a MOVE (e.g. "
        "{\"knows_move\":\"MEGA_PUNCH\"}, or {\"knows_move\":{\"move\":"
        "\"MEGA_PUNCH\",\"slot\":1}} for one particular member). A TM in the "
        "bag does nothing until it is taught, and a Pokemon that only knows "
        "weak or non-damaging moves loses fights its level says it should "
        "win — when the journal shows your hits dealing very little, teaching "
        "a move is a subgoal you can aim at, not just a thing that happens on "
        "its own",
    "has_species": "a NAMED species is in the party (e.g. "
        "{\"has_species\":\"PIDGEY\"}, or a list for several). Pair it with "
        "any_of when more than one species would do: {\"any_of\":["
        "{\"has_species\":\"PIDGEY\"},{\"has_species\":\"RATTATA\"}]}. Set "
        "battle_policy \"catch\" on the subgoal so wild battles throw balls "
        "instead of knocking the target out, and remember you can only catch "
        "what lives where you are standing",
    "party_type": "the party contains a Pokemon of a TYPE (e.g. "
        "{\"party_type\":\"WATER\"}, or a list to require several). Use this "
        "rather than has_species when what you need is COVERAGE and any "
        "species of that type would serve — it does not commit the plan to "
        "one encounter that may not show up. The psychic type is spelled "
        "PSYCHIC_TYPE. Set battle_policy \"catch\" on the subgoal, or wild "
        "battles knock out the very thing you are trying to keep",
    "dex_owned": "at least N species OWNED in the Pokedex (e.g. "
        "{\"dex_owned\":10}). Owning counts a species you have caught or "
        "evolved into, not one merely seen in battle — so set battle_policy "
        "\"catch\" on the subgoal and carry balls",
    "any_of": "EITHER/OR: a LIST of predicates, satisfied as soon as ANY "
        "one of them holds (e.g. {\"any_of\":[{\"has_item\":"
        "{\"HELIX_FOSSIL\":1}},{\"has_item\":{\"DOME_FOSSIL\":1}}]}). Use "
        "this whenever the game offers a CHOICE and taking one option means "
        "you can never have the other. Writing the alternatives as two "
        "subgoals instead is a trap: the second one can never come true, so "
        "the plan hunts forever for a thing it already chose not to take",
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


# ...MINUS THE ONES THIS BUILD CAN NEVER SET. The engine ships Yellow's
# content alongside Red's, and its flag list carries both — so
# EVENT_BEAT_MT_MOON_3_JESSIE_JAMES validated fine, a leg was authored
# around it, and the run spent twenty escalations hunting a trainer who is
# not on the map. A REAL FLAG ID IS NOT EVIDENCE OF A REAL ENCOUNTER.
# engine_flags.txt now holds only flags mentioned somewhere outside the
# yellow-specific files (10 of 511 dropped: the four Jessie/James fights,
# Pikachu's starter events, Bulbasaur-in-Cerulean, Squirtle-from-Jenny).
# The full list is kept beside it as engine_flags.all.txt and the dropped
# ones as engine_flags.excluded.txt; regenerate by re-scanning
# gen1recomp/data and src for each name and keeping those with a mention
# in a path that does not contain "yellow".
ENGINE_FLAGS = _engine_names("engine_flags.txt")
# Every item id the engine defines (data/generated/items.lua), for the same
# reason ENGINE_FLAGS exists: KEY_ITEMS is a seven-entry spelling aid, and
# using it as the whole has_item universe made "I have the fossil" — the
# RIGHT condition for a fossil leg — unwritable in any spelling. The model
# may name any real item; validation only checks the string is real.
ENGINE_ITEMS = _engine_names("engine_items.txt")
# Every move id the engine defines (data/generated/moves.lua), so knows_move
# can be spell-checked the same way. Manual tier: the TM's own description
# names the move it teaches, and a Pokemon's summary screen lists its moves.
ENGINE_MOVES = _engine_names("engine_moves.txt")
# Every species and every type the engine defines. Same tier as the rest:
# the Pokedex names species, the status screen prints types. These exist so
# that "catch a WATER type before the next gym" is a condition a plan can
# actually be held to — before them the only writeable upkeep was
# party_size, under which "catch a Rattata to soak hits" and "catch a
# water type to cover the gym" are the same subgoal and both are satisfied
# by whatever walks into the grass first.
ENGINE_SPECIES = _engine_names("engine_species.txt")
ENGINE_TYPES = _engine_names("engine_types.txt")

# The game's printed outdoor map (data/generated/maps.lua connections),
# shared with the executor — used to name roads the run has stood beside
# and never crossed.
try:
    MAP_EDGES = json.loads(
        Path(__file__).with_name("map_edges.json").read_text())
except (OSError, ValueError):
    MAP_EDGES = {}

# The same printed map's LABELLED PLACES: which named cave, tunnel or
# landmark each road has a door into (planner/gen_map_doors.py). Same tier
# as the edges above — the Town Map draws ROCK TUNNEL its own pin at (14,3)
# beside ROUTE 10's at (14,4) — and filtered by that geometry, so a place
# sharing its city's pin is absent. What is behind a door stays unknown.
try:
    MAP_DOORS = json.loads(
        Path(__file__).with_name("map_doors.json").read_text())
except (OSError, ValueError):
    MAP_DOORS = {}


# THE MAP IS AN ITEM, AND IT IS IN THE GAME. Both blocks below are the
# TOWN MAP's face — which roads touch, and which named places sit beside
# them — and they were handed over from turn 0, before the map is in the
# bag. A player does not have them until Daisy hands the thing over in
# Blue's house, which is a real errand with a real gate (EVENT_GOT_STARTER).
#
# Gating it was dismissed once, correctly, because the run had never
# obtained the map in any playthrough and the gate would have been dead —
# the interaction is spent on leg 1 before it can pay, and the harness then
# retired her for ever. That is fixed (see _worth_another_word and the
# ROOMS WHERE SOMEBODY IS WORTH ANOTHER WORD line), so the errand is now
# reachable and the gate is a gate rather than a wall.
#
# Read from the state snapshot the re-author already uses; when it cannot
# tell, the safe answer is NOT HELD, and it says so rather than going quiet.
def holding_town_map() -> bool:
    for src in ("run/last_state.json", "run/obs.json"):
        try:
            o = json.loads(Path(src).read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(o, dict):
            continue
        bag = o.get("bag")
        if isinstance(bag, dict):
            return "TOWN_MAP" in bag
    return False


def doors_text() -> str:
    """The labelled places, as the printed map shows them.

    Written because a plan read "Enter Diglett's Cave from Route 10, exit
    east into Route 11". Diglett's Cave joins Routes 2 and 11; the tunnel
    on Route 10 is Rock Tunnel. Two real places, swapped — and the map
    names both.

    THE PIN, AND NOT WHAT IT IMPLIES (user's call, 2026-08-17). This used
    to go on to state the routing rule the ids encode: an id under ONE road
    is entered and left on that road, an id under TWO roads joins those
    two, and a shared printed name over four roads is two different
    tunnels. Every one of those is a conclusion about interior
    connectivity, which the Town Map does not draw — and SYS called the
    interior "the one thing it cannot work out for itself" in the sentence
    before handing it over. The listing stays, because a labelled pin
    beside a road is the map's own face. What a repeated id MEANS is left
    to the model: it can see the token twice, and drawing the inference is
    the part that belongs to it.
    """
    if not MAP_DOORS:
        return ""
    rows = "\n".join(
        f"  {road}: " + ", ".join(
            f"{lbl} (enter {ids[0]})" for lbl, ids in sorted(places.items()))
        for road, places in sorted(MAP_DOORS.items()))
    return ("\n\nPLACES THE PRINTED MAP NAMES, and the road each one opens "
            "off. This is the map's own labelling, not scouting: what lies "
            "BEYOND any of these doors is not here. The listing is COMPLETE "
            "— every road with a door into a named place is above.\n"
            + rows)


def edges_text() -> str:
    """The printed map's outdoor connections.

    The same sheet the doors come off. It was already being quoted at the
    author, but ONLY where the run had failed — "roads you have stood
    beside and never crossed" names printed connections too — so the model
    saw the map exclusively as a list of its own defeats, and nothing ever
    told it which roads simply touch. A player has the Town Map open.

    Adjacency only: which roads meet. Not where anything is, not what is
    on them, not which way to go.
    """
    if not MAP_EDGES:
        return ""
    rows = "\n".join(
        f"  {m}: " + ", ".join(f"{d} to {nb}"
                               for d, nb in sorted(edges.items()))
        for m, edges in sorted(MAP_EDGES.items()))
    return ("\n\nHOW THE PRINTED MAP JOINS UP outdoors — which roads and "
            "towns touch, and in which direction. A pair not listed here "
            "does not meet on the map:\n" + rows)

# The bag SCREEN says "HM01", never "HM_CUT" — the model's spelling is the
# game's own on-screen spelling, and five feedback rounds could not talk it
# out of the name every player reads. Accept the screen's names; the
# numbering is Gen 1 canon.
ITEM_ALIASES = {"HM01": "HM_CUT", "HM02": "HM_FLY", "HM03": "HM_SURF",
                "HM04": "HM_STRENGTH", "HM05": "HM_FLASH"}


def normalize_items(plan: dict):
    for s in plan.get("subgoals") or []:
        dw = s.get("done_when")
        if isinstance(dw, dict) and isinstance(dw.get("has_item"), dict):
            dw["has_item"] = {ITEM_ALIASES.get(k, k): v
                              for k, v in dw["has_item"].items()}

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

Hard rule on GRANULARITY: each subgoal is ONE event or interaction that
happens within a single map. "Go to the shop and buy potions" is two —
arrive, then buy.

TRAVEL IS THE EXCEPTION, and naming every road is worse than naming none.
The executor routes between milestones by itself over ground this run has
already walked, and it knows which roads have never once opened. So a
journey across walked ground is ONE subgoal naming where you want to BE:
{"map":"CELADON_CITY"}, not a road-by-road chain through Route 5, Route 6
and Route 7. Spelling out the roads does not help it — it FORCES the exact
route you named, including any road that has never opened, when it could
have found a way round. It can aim at a town it has NEVER SEEN, because the
printed map says which way that is — so "never been there" is not a reason
to spell out the roads.

The one thing it cannot work out for itself is a way through an INTERIOR,
because the printed map does not draw what is inside one. Where the road
you need runs through a tunnel, a cave or a building — the named places
listed above, whose ids you have — say THAT as its own subgoal, and leave
the outdoor walking on either side of it as one step each.

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


def fired_flags() -> list:
    """Every event flag this run has watched fire, oldest first — the only
    flag names the harness may volunteer (they are history, not contents)."""
    fired = []
    try:
        for line in Path("run/executor_log.jsonl").read_text().splitlines():
            if '"flag_fired"' not in line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            f = r.get("flag")
            if f and f not in fired:
                fired.append(f)
    except OSError:
        pass
    return fired


def recent_events(cap: int = 14) -> str:
    """The last things that actually HAPPENED, newest last.

    Replaces an earlier attempt that listed every event flag whose NAME
    matched the objective's words. That was rejected (user, 2026-08-15) and
    rightly: telling a run standing in the Rocket Hideout that a flag
    called EVENT_ROCKET_DROPPED_LIFT_KEY exists is not spelling help, it is
    telling it what the dungeon contains. What a run DID is different — it
    is history, the same tier as the journal, and it is what makes a
    {"flag":...} condition writable without being told the answers.

    Numbered families collapse so fourteen beaten trainers cannot crowd out
    the one deed that mattered.
    """
    import collections
    fired = fired_flags()
    if not fired:
        return ""
    fam: collections.OrderedDict = collections.OrderedDict()
    for f in reversed(fired):                 # newest first while grouping
        fam.setdefault(re.sub(r"_\d+", "_N", f), []).append(f)
    out = [b + (f" x{len(g)}" if len(g) > 1 else "") if len(g) > 1 else g[0]
           for b, g in fam.items()][:cap]
    return ("\n\nWHAT THIS RUN HAS ALREADY DONE, most recent first (event "
            "records the game itself wrote; a {\"flag\":...} condition can "
            "name any of these): " + ", ".join(out)
            + (f" (+{len(fam) - cap} more)" if len(fam) > cap else "") + ".")


def outline_so_far(cap: int = 12) -> str:
    """Your own playthrough list, split at where the run has got to.

    recent_events() is a flat set of things that fired; this is the same
    history in ORDER, in the model's own words, and the two together are
    what let it place a new leg in the arc instead of in a vacuum. Every
    line is the model's own product — its outline, and the chain's count
    of how far it got — so nothing here tells it anything about the game.
    """
    try:
        legs = [l.strip() for l in
                Path("plans/outline.txt").read_text().splitlines() if l.strip()]
        n = int(Path("run/outline_leg").read_text().strip() or 0)
    except (OSError, ValueError):
        return ""
    if not legs:
        return ""
    n = max(0, min(n, len(legs)))
    out = ""
    if n:
        show = legs[:n][-cap:]
        out += ("\n\nTHE OBJECTIVES YOU HAVE ALREADY FINISHED, in the order "
                "you finished them: "
                + ("... " if n > cap else "")
                + "; ".join(show) + ".")
    if n < len(legs):
        out += ("\n\nWHAT YOU PLANNED TO DO AFTER THIS ONE: "
                + "; ".join(legs[n + 1:n + 1 + 4]) + ".")
    return out + done_ledger_text()


def build_prompt(goal: str, start: str | None = None) -> str:
    return (
        f"GOAL: {goal}\n\n"
        f"STARTING STATE: {start or NEW_GAME_START}\n\n"
        f"PREDICATES you may use in done_when (pick the ONE that best marks "
        f"the subgoal complete):\n"
        + "\n".join(f"  {k}: {v}" for k, v in PREDICATES.items())
        + "\n\nMAP IDs on this route (use exact strings):\n  "
        + ", ".join(ROUTE_MAPS)
        + (edges_text() + doors_text() if holding_town_map()
           else "\n\nYou are not carrying a TOWN MAP. Kanto's layout — "
                "which roads touch which, and what is named where — is "
                "printed on one, and you have not got hold of one yet. "
                "Plan from what you have walked.")
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
        + recent_events()
        + outline_so_far()
        + f"\n\nBADGES: {', '.join(BADGES)}\n\n"
        "Author the ordered subgoal list now. Remember the granularity rule.")


VALID_KEYS = set(PREDICATES)


def pred_keys(pred) -> set:
    """Every predicate key in play, including inside any_of branches (the
    executor's helper, kept here so the author imports nothing from it)."""
    out = set()
    for k, v in (pred or {}).items() if isinstance(pred, dict) else []:
        if k == "any_of":
            for alt in (v or []):
                out |= pred_keys(alt)
        else:
            out.add(k)
    return out


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
        _check_pred(dw, tag, sid, probs)
    # A PLACE IS NOT THE DEED. Leg 11 of run 13 ("Chase the Team Rocket
    # thief out of the burgled house") ended on confront_thief:
    # {"map":"CERULEAN_CITY"} — walking out of the house satisfied it, the
    # judge said DONE, and EVENT_BEAT_CERULEAN_ROCKET_THIEF never fired: a
    # false completion the run pays for later at Route 9. When the
    # objective's own verb is a deed, its LAST subgoal must end on what the
    # deed leaves behind — a flag, an item, a badge, a party change — not
    # on standing somewhere.
    goal = str(plan.get("goal") or plan.get("objective") or "").strip()
    # verbs whose leftover is ALWAYS a flag/item/badge/party change. Not
    # "give"/"talk"/"find": a drink handed to a guard leaves passage, and a
    # hideout found IS a place — a place condition is right for those.
    DEED = ("defeat", "chase", "retrieve", "rescue", "wake", "deliver",
            "obtain", "buy", "clear", "beat", "catch", "receive")
    if subs and goal and goal.split()[0].lower().rstrip(",:") in DEED:
        last = subs[-1] if isinstance(subs[-1], dict) else {}
        dw = last.get("done_when") or {}
        keys = set(pred_keys(dw)) if isinstance(dw, dict) else set()
        if keys and keys <= {"map", "area", "no_battle", "party_healthy"}:
            probs.append(
                f"subgoal[{len(subs) - 1}] ({last.get('id')}) is the LAST step "
                f"of a leg whose objective is a deed (\"{goal[:60]}\"), but "
                f"its condition is only a place ({', '.join(sorted(keys))}). "
                f"Standing somewhere is not the deed done: end on what the "
                f"deed leaves behind — an event flag, an item gained, a "
                f"badge, a party change.")
    return probs


def _check_pred(dw: dict, tag: str, sid, probs: list):
    """Validate one predicate — recursively, so an any_of branch gets the
    same item/map/flag scrutiny as a top-level one. Without the recursion an
    alternative could name a misspelled item and sail through."""
    if not isinstance(dw, dict):
        probs.append(f"{tag} ({sid}) predicate is not an object")
        return
    # A subgoal whose ONLY condition is no_battle is already satisfied the
    # moment it starts — you author plans out of battle — so it marks
    # nothing and the run walks straight past it. It came up as the finish
    # line for "defeat the Rocket boss" and for Giovanni: two fights that
    # would have counted as won without being fought.
    if set(dw) == {"no_battle"}:
        probs.append(f"{tag} ({sid}) no_battle alone is true whenever you "
                     f"are not fighting, so it marks nothing — name what "
                     f"the fight CHANGES (a flag, a badge, an item)")
    for k, v in dw.items():
            if k not in VALID_KEYS:
                probs.append(f"{tag} ({sid}) unknown predicate '{k}'")
            elif k == "any_of":
                if not isinstance(v, list) or len(v) < 2:
                    probs.append(f"{tag} ({sid}) any_of needs a LIST of at "
                                 f"least two alternative predicates")
                else:
                    for alt in v:
                        _check_pred(alt, tag, sid, probs)
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
                # A FLAG'S NAME IS A FACT. Close matches over the whole
                # engine list told a plan that wrote EVENT_TOWER_GHOSTS_GONE
                # "did you mean EVENT_BEAT_GHOST_MAROWAK?" — the ghost's
                # identity, handed over by the spell-checker (2026-08-18).
                # Items and species are pamphlet tier (a list of things
                # that exist); event names are what the game contains.
                # Suggest only from what this run has already watched
                # fire; otherwise say to condition on something visible.
                near = difflib.get_close_matches(v, fired_flags(),
                                                 n=3, cutoff=0.6)
                hint = (f" — did you mean {', '.join(near)}?" if near else
                        " — if you cannot spell the event, condition on "
                        "something you can see instead: a map, an item, a "
                        "badge, or a party change")
                probs.append(f"{tag} ({sid}) flag '{v}' is not an event this "
                             f"game defines{hint}")
            elif k == "badge" and v not in BADGES:
                probs.append(f"{tag} ({sid}) badge '{v}' unknown")
            elif k == "has_species" and ENGINE_SPECIES:
                names = ([v] if isinstance(v, str)
                         else list(v or []) if isinstance(v, (list, tuple))
                         else list((v or {}).keys()))
                for sp in names:
                    sp = str(sp).upper()
                    if sp not in ENGINE_SPECIES:
                        near = difflib.get_close_matches(
                            sp, ENGINE_SPECIES, n=3, cutoff=0.6)
                        hint = (f" — did you mean {', '.join(near)}?"
                                if near else "")
                        probs.append(f"{tag} ({sid}) '{sp}' is not a species "
                                     f"this game defines{hint}")
            elif k == "party_type" and ENGINE_TYPES:
                names = [v] if isinstance(v, str) else list(v or [])
                for ty in names:
                    ty = str(ty).upper()
                    if ty in ENGINE_TYPES:
                        continue
                    # the engine calls it PSYCHIC_TYPE so the type and the
                    # move of the same name cannot be confused; nobody
                    # writing a plan would guess that
                    if ty + "_TYPE" in ENGINE_TYPES:
                        probs.append(f"{tag} ({sid}) the type is spelled "
                                     f"{ty}_TYPE here, not {ty}")
                        continue
                    near = difflib.get_close_matches(ty, ENGINE_TYPES,
                                                     n=3, cutoff=0.5)
                    hint = (f" — did you mean {', '.join(near)}?"
                            if near else f" — types are: "
                            f"{', '.join(sorted(ENGINE_TYPES))}")
                    probs.append(f"{tag} ({sid}) '{ty}' is not a type this "
                                 f"game defines{hint}")
            elif k == "knows_move" and ENGINE_MOVES:
                # The TM is TM_MEGA_PUNCH; the MOVE it teaches is MEGA_PUNCH.
                # Naming the TM here would be checked against a move list it
                # can never be in, so say which half is wanted.
                mv = str((v or {}).get("move") if isinstance(v, dict)
                         else v or "").upper()
                if mv not in ENGINE_MOVES:
                    stripped = mv.split("_", 1)[-1] if mv.startswith(
                        ("TM_", "HM_")) else ""
                    if stripped in ENGINE_MOVES:
                        hint = (f" — {mv} is the ITEM; the move it teaches "
                                f"is {stripped}")
                    else:
                        near = difflib.get_close_matches(
                            mv, ENGINE_MOVES, n=3, cutoff=0.6)
                        hint = (f" — did you mean {', '.join(near)}?"
                                if near else "")
                    probs.append(f"{tag} ({sid}) '{mv}' is not a move this "
                                 f"game defines{hint}")
    _check_pred_shapes(dw, tag, sid, probs)


# WHAT A PREDICATE'S VALUE MUST LOOK LIKE. The checks above validate NAMES —
# is that a real item, a real move, a real species — and the loop passes
# everything else on key-membership alone. But pred_holds indexes some of
# these values directly (`want["x"]`, `int(want.get("slot"))`), so a shape
# the model is perfectly free to write takes the whole executor down in the
# middle of a leg, and two more shapes are accepted and then quietly mean
# nothing:
#   {"party_nonempty": "true"}          -> bool(party) != "true" is ALWAYS
#                                          true, so the subgoal can never
#                                          be satisfied
#   {"slot_level": {"slot": 2,
#                   "level": 15}}       -> the key is `min`; `level` is
#                                          ignored, need becomes 0, and the
#                                          subgoal is instantly true having
#                                          trained nothing
# Rejecting them here is how the model finds out — it gets the problem back
# and re-authors. pred_holds is hardened separately, because a plan can
# reach the executor by routes that never pass through this validator.
_SHAPES = {
    "lead_level": "int", "party_min_level": "int", "party_size": "int",
    "dex_owned": "int",
    "party_nonempty": "bool", "party_alive": "bool",
    "party_healthy": "bool", "no_battle": "bool",
}


def _check_pred_shapes(dw: dict, tag: str, sid, probs: list):
    for k, v in dw.items():
        want = _SHAPES.get(k)
        if want == "int" and (isinstance(v, bool)
                              or not isinstance(v, int)):
            probs.append(f"{tag} ({sid}) {k} takes a whole number, not "
                         f"{v!r}")
        elif want == "bool" and not isinstance(v, bool):
            why = (" — a string is never equal to a boolean, so this "
                   "condition could never come true"
                   if isinstance(v, str) else "")
            probs.append(f"{tag} ({sid}) {k} takes true or false, "
                         f"not {v!r}{why}")
        elif k == "screen" and v not in UI_SCREENS:
            # Same treatment as mode, and for the same reason: a screen id
            # the engine never pushes is a condition that can never be
            # true, and finding that out costs four attempts and a ladder.
            probs.append(
                f"{tag} ({sid}) screen {v!r} is not a screen this game has "
                f"— the ones that exist are " + ", ".join(UI_SCREENS))
        elif k == "screen" and v in ("BagMenu", "MoveLearnMenu", "PartyMenu",
                                     "StartMenu", "OptionsMenu",
                                     "TrainerCard", "PokedexMenu",
                                     "DexEntryMenu", "TownMap"):
            # A MENU NO OP LEAVES OPEN IS NOT A STEP. Run 13's CUT leg was
            # written as open_bag {screen:BagMenu} → select_hm_cut
            # {screen:MoveLearnMenu} → teach; no op opens the bag as a
            # resting state (use_item works the bag itself and closes it),
            # so the run pressed menu at random rooms for ten rounds looking
            # for "the trigger". The screens an op does leave open are the
            # PC's (BoxMenu, PlayerPC) and a shop's; the rest are the
            # inside of a single op.
            probs.append(
                f"{tag} ({sid}) screen {v!r} is the inside of one op, not a "
                f"step: no op leaves it open. Teaching a machine is ONE op "
                f"— use_item item=HM_CUT slot=N (forget=MOVE if it knows "
                f"four); condition on knows_move, not on a menu.")
        elif k == "mode" and v == "dialog":
            # A REAL MODE THAT IS NEVER TRUE WHEN IT IS TESTED. done_when is
            # evaluated against a SETTLED observation, and settle()'s whole
            # job is to ride plain text to the next decision — so the box is
            # always closed by the time the check runs. The run spoke to the
            # Viridian old man and sat through the whole catch tutorial over
            # and over with {"mode":"dialog"} never once holding.
            # Same class as {"mode":"pc"}: a value the harness accepts and
            # can never report at the moment it matters. Rejected where it
            # is written, for the same reason and at the same cost.
            probs.append(
                f"{tag} ({sid}) mode \"dialog\" can never be true when a "
                f"condition is checked: conditions are tested after the "
                f"game settles, and settling rides plain text to the next "
                f"decision, so the box has always closed. Mark the "
                f"conversation by what it CHANGED — a flag, an item, a "
                f"party member — not by the box it was said in")
        elif k == "mode" and v not in OBS_MODES:
            # NAME THE FIVE, and say what the near miss was reaching for.
            # "pc" is not a wrong guess so much as a reasonable one about a
            # vocabulary nobody published.
            probs.append(
                f"{tag} ({sid}) mode {v!r} is not a mode this game "
                f"reports — the only ones that exist are "
                + ", ".join(OBS_MODES)
                + ". Every menu screen is \"ui\", so a subgoal about one "
                  "particular machine cannot be marked by mode at all")
        elif k == "player_at":
            if not isinstance(v, dict):
                probs.append(f"{tag} ({sid}) player_at takes "
                             f"{{\"x\":N,\"y\":N}}, not {v!r}")
            else:
                miss = [a for a in ("x", "y")
                        if not isinstance(v.get(a), (int, float))
                        or isinstance(v.get(a), bool)]
                if miss:
                    probs.append(f"{tag} ({sid}) player_at needs a number "
                                 f"for {' and '.join(miss)}")
                if "radius" in v and (isinstance(v["radius"], bool)
                                      or not isinstance(v["radius"],
                                                        (int, float))):
                    probs.append(f"{tag} ({sid}) player_at radius must be "
                                 f"a number")
        elif k == "slot_level":
            if not isinstance(v, dict):
                probs.append(f"{tag} ({sid}) slot_level takes "
                             f"{{\"slot\":N,\"min\":N}}, not {v!r}")
            else:
                if not isinstance(v.get("slot"), int) or \
                        isinstance(v.get("slot"), bool):
                    probs.append(f"{tag} ({sid}) slot_level needs a whole "
                                 f"number for slot (1 is the lead)")
                if not isinstance(v.get("min"), int) or \
                        isinstance(v.get("min"), bool):
                    extra = (" — you wrote 'level'; the key is 'min'"
                             if "level" in v else "")
                    probs.append(f"{tag} ({sid}) slot_level needs a whole "
                                 f"number for min{extra}")
        elif k == "knows_move" and isinstance(v, dict) and "slot" in v:
            if not isinstance(v["slot"], int) or isinstance(v["slot"], bool):
                probs.append(f"{tag} ({sid}) knows_move slot must be a "
                             f"whole number")
        elif k == "area" and isinstance(v, str) and "|" in v:
            mp = v.split("|", 1)[0]
            if ROUTE_MAPS and mp not in ROUTE_MAPS:
                probs.append(f"{tag} ({sid}) area '{v}' names map '{mp}', "
                             f"which is not in the route list")


def author(goal: str, model: str, rounds: int = 5,
           start: str | None = None) -> dict | None:
    # 5 rounds, not 3: with correct suggestions in the feedback the author
    # still re-minted a DIFFERENT wrong id each round (HM01 -> flag guess
    # -> HM01 again) and three rounds died before the oscillation settled.
    fb = ""
    for rnd in range(1, rounds + 1):
        user = build_prompt(goal, start) + (
            f"\n\nFIX THESE PROBLEMS from your last attempt — where a "
            f"problem offers a 'did you mean' suggestion, use that exact "
            f"id verbatim, and change NOTHING else about your plan:\n{fb}"
            if fb else "")
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
        normalize_items(plan)
        probs = validate(plan)
        if not probs:
            # tag each subgoal so escalation/distillation runs it macro-less
            for s in plan["subgoals"]:
                s.setdefault("escalation_rounds", 4)
                # WHO WROTE THIS SUBGOAL, written at the moment it is
                # created. The recorded fix was "written once at creation
                # and never touched"; the never-touched half shipped and
                # this half did not, so `subgoal_provenance` had exactly one
                # writer in the codebase — a setdefault in distill() filling
                # the literal "unknown (pre-audit)". Across 742 plan files:
                # 3,906 subgoals with no provenance at all, 594 placeholder,
                # and the only 24 naming a model are in the old hand-seeded
                # spine files. File-level authored_by is honest and well
                # covered but cannot tell a model-written subgoal from a
                # hand-inserted one in the same file, which is the exact
                # distinction the claim once overstated.
                # Nothing is backfilled: a plan written before today does
                # not get to claim an author it cannot prove.
                s.setdefault("subgoal_provenance",
                             {"authored_by": model,
                              "via": "author.py decomposition",
                              "goal": goal})
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
    "knows_move teaches it something that actually hurts; "
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
    "\n\nWHEN ONE SUBGOAL KEEPS DYING PART-WAY THROUGH A SEQUENCE OF "
    "DEEDS, SPLIT IT. The journal shows what the failed attempts achieved "
    "inside it — a bush cut, a building entered, a first lock opened — "
    "and every such act can be its own subgoal with its own condition "
    "(the game defines an event flag for most of them). One subgoal per "
    "deed means each attempt BANKS what it achieved instead of redoing "
    "the whole dance inside one budget, and the next attempt resumes at "
    "the first unbanked deed."
    "\n\nWHEN THE JOURNAL PROVES A MARCH UNREACHABLE, DO NOT RE-MARCH IT. "
    "A line like 'could not get map:X — N attempts' or a direction marked "
    "PROVEN uncrossable is the run reporting that this exact sequence of "
    "maps does not connect from where it stands, however right it looks "
    "from memory. Re-issuing those same map subgoals is not a revision. "
    "If the destination still matters, the way there is a DIFFERENT "
    "sequence — through maps and doors the evidence has never condemned, "
    "even ones that feel like a detour."
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


try:
    _ITEM_IDS = {l.strip() for l in
                 (Path(__file__).resolve().parent / "engine_items.txt")
                 .read_text().splitlines() if l.strip()}
except OSError:
    _ITEM_IDS = set()


def _looks_like_item_name(name: str) -> bool:
    """A map object name that names an item's CONTENTS (ROUTE2_HP_UP,
    MTMOON1F_TM_WATER_GUN, OAKSLAB_CHARMANDER_POKE_BALL). The shim emits
    ITEM_x_y for those since 2026-08-18; names of this shape still sit in
    ledgers and journals written before, and must not reach the author —
    what is in a ball is not on the screen. Same rule as executor.py."""
    n = str(name or "")
    if n.startswith("ITEM_"):
        return False
    if n.endswith("_POKE_BALL"):
        return True
    parts = n.split("_")
    return any("_".join(parts[i:]) in _ITEM_IDS for i in range(1, len(parts)))


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
        # ONE LINE PER DOORWAY, NOT PER TILE. A door spans two tiles and
        # both get recorded, so the same passage was stated twice or three
        # times — 20 of 91 lines in the walked graph said something the
        # line above it already said. Which tile you step on is not a fact
        # the model needs; where the door goes is. Keep every DISTINCT
        # destination, name the tiles once.
        byd: dict = {}
        for key, e in sorted((exp[region] or {}).items()):
            byd.setdefault(e.get("to"), []).append((key, e))
        for dest, group in sorted(byd.items(), key=lambda kv: str(kv[0])):
            keys = ", ".join(k for k, _ in group)
            shut = all((e or {}).get("shut") for _, e in group)
            lines.append(f"  {region}  --{keys}-->  {dest}"
                         + ("  (SHUT: walked into it and turned back every "
                            "time)" if shut and dest == region else ""))
    # WHAT GETS CUT MATTERS MORE THAN HOW MANY. This was an alphabetical
    # names[:8], so CERULEAN_CITY showed eight COOLTRAINERs and GUARDs and
    # dropped CUT_TREE — the one object in that city the party could act
    # on, and the only thing standing between it and Route 9. The run stood
    # in Cerulean 321 times without going east while the answer sat in the
    # ledger, trimmed out of the evidence by sort order.
    # Names carry their own kind: people are <MAPID>_<ROLE>, signposts are
    # TEXT_*, and terrain you can DO something to is bare (CUT_TREE, PC,
    # TRASH_CAN_n). Order by that, collapse numbered families, and say what
    # was dropped rather than truncating in silence.
    seen = []
    # NEVER PRESSED IS A FACT THE AUTHOR WAS NOT SHOWN. This listed every
    # thing ever sighted, so a house whose two people the run has never
    # spoken to read exactly like the mart it has pressed nine times. The
    # touched ledger is right there; a * marks what this run has never
    # pressed, and those go first. Which of them is worth a subgoal is the
    # author's; that they are unpressed is not a judgment.
    touched_all = d.get("touched") or {}
    for region, names in sorted((d.get("sightings") or {}).items()):
        names = [n for n in (names or []) if not _looks_like_item_name(n)]
        if not names:
            continue
        pre = region.split("|")[0].replace("_", "")
        got = set(touched_all.get(region) or [])

        def _rank(n, _p=pre):
            if n.startswith("TEXT_"):
                return 2            # a signpost; its words are recorded
            if n.startswith(_p):
                return 1            # a person standing there
            return 0                # terrain — the actionable kind

        fam: dict = {}
        for n in names:
            base = re.sub(r"_\d+$", "", n)
            fam.setdefault(base, []).append(n)
        collapsed = []
        for b, g in fam.items():
            unpressed = [n for n in g if n not in got]
            label = b if len(g) == 1 else f"{b} x{len(g)}"
            if unpressed:
                label += "*"
            collapsed.append((0 if unpressed else 1, label))
        collapsed.sort(key=lambda t: (t[0], _rank(t[1].split(" x")[0]
                                                  .rstrip("*")), t[1]))
        collapsed = [t[1] for t in collapsed]
        shown, extra = collapsed[:8], len(collapsed) - 8
        seen.append(f"  {region}: {', '.join(shown)}"
                    + (f" (+{extra} more)" if extra > 0 else ""))
    dead = []
    for tgt, regions in (d.get("dead_ends") or {}).items():
        for region, n in regions.items():
            dead.append(f"  {tgt} was NOT reachable from {region} ({n}x)")
    areas = sorted({r for r in exp} | {t for v in exp.values()
                                       for t in [e.get("to") for e in v.values()] if t})
    # ALL OF THEM, GROUPED. A flat alphabetical [:40] hid 48 of the 88
    # blocks already walked, and the validator forbids naming a code that
    # is not listed — so half the map was unaimable-at, silently, with the
    # survivors picked by spelling. Sharing the map prefix costs a fraction
    # of the room and drops nobody. These get MORE numerous as the game
    # goes on (a place is now bounded by seams and one-way drops, and the
    # Rocket hideout is nothing but fiddly locked pockets), so a fixed cap
    # was only ever going to bite harder.
    # WRITTEN OUT IN FULL, because the model has to copy one of these
    # verbatim into a predicate. Collapsing them to CERULEAN_CITY|20,0|8,7
    # is shorter and unusable: it is not a code, and the validator would
    # bounce it. The whole list costs ~2KB of a 22KB budget; hiding half
    # the map to save that is a bad trade.
    _grouped = ", ".join(areas)
    out = ("\n\nAREA CODES you may use with the \"area\" predicate (these are "
           "the enclosed areas actually walked; a map with several is split "
           "into parts that cannot be walked between, listed after its "
           "name):\n  " + _grouped
           + "\n\nWHAT PREVIOUS RUNS ACTUALLY WALKED (evidence — trust this "
           "over your memory of the game; MAP|region means one connected "
           "area, so the SAME map id appearing with DIFFERENT regions is a "
           "map split into parts that cannot walk to each other):\n"
           + "\n".join(lines))
    # ROADS STOOD BESIDE AND NEVER CROSSED. The walker knows these (it
    # ranks its own moves around them) but the AUTHOR never did, so a
    # plan kept being written as "go to Route 12, then Lavender" and the
    # run spent its rounds pressing north at a sleeping Snorlax. Derived
    # from visits alone — a well-trodden map whose printed neighbour has
    # never been entered — so it clears itself the moment the road opens.
    vis: dict = {}
    for r, n in (d.get("visits") or {}).items():
        m = r.split("|")[0]
        vis[m] = vis.get(m, 0) + n
    blocked = sorted(
        f"  {m} --{dirn}--> {nb}  (stood in {m} {vis[m]}x, never once "
        f"reached {nb})"
        for m, edges in MAP_EDGES.items()
        for dirn, nb in edges.items()
        if vis.get(m, 0) >= 8 and not vis.get(nb))
    if blocked:
        out += ("\n\nROADS YOU HAVE STOOD BESIDE AND NEVER CROSSED. Each of "
                "these is a printed connection the run has had many chances "
                "to take and has not taken. WHY is not recorded and is not "
                "always the same: someone may want something, something may "
                "be asleep on it, or the road may leave from a part of that "
                "map the run has never stood in — Route 10's south end is "
                "past Rock Tunnel, so standing at its north end forever "
                "would earn it a line here. What is true of every one of "
                "them is that a route using it HAS NOT WORKED YET, so a "
                "plan built on one needs something to change first — "
                "reaching that road from somewhere else, or doing the deed "
                "that opens it. WHICH, is yours to say:\n"
                + "\n".join(blocked))
        # EVERY WAY IN, GROUPED BY THE PLACE. The lines above are one leg
        # each, so "both the roads I have tried into Saffron are shut, and
        # the map draws two more I have never stood on" had to be
        # reassembled from scattered facts every time. The printed map
        # knows all four approaches and the ledger knows which have been
        # walked; putting them side by side is bookkeeping. Which untried
        # approach to go and find, or whether to open one of the shut ones
        # instead, is not.
        into: dict = {}
        for m, edges in MAP_EDGES.items():
            for dirn, nb in edges.items():
                into.setdefault(nb, []).append((m, dirn))
        hammered = {nb for m, edges in MAP_EDGES.items()
                    for nb in edges.values()
                    if vis.get(m, 0) >= 8 and not vis.get(nb)}
        walls = []
        for dest in sorted(hammered):
            rows, ways = [], 0
            for src, dirn in sorted(into.get(dest, [])):
                n = vis.get(src, 0)
                ways += 1
                rows.append(
                    f"    from {src} heading {dirn}: "
                    + (f"stood there {n}x and never once got through"
                       if n else "you have never stood in that place"))
                # A ROAD CAN HAVE HALVES. Where a road has a named place
                # opening off it, its far side may be reachable only
                # through that door — Route 10's south end is past Rock
                # Tunnel, so a plan hopping ROUTE_10 -> LAVENDER_TOWN is
                # standing at the north end asking for a road that leaves
                # from the south. The two facts sat in different tables and
                # were never put side by side. What that means here is
                # yours to judge.
                for lbl, ids in sorted((MAP_DOORS.get(src) or {}).items()):
                    been = sum(vis.get(i, 0) for i in ids)
                    rows.append(
                        f"      ({src} also has a door into {lbl} "
                        f"[{ids[0]}] — "
                        + (f"gone through {been}x" if been
                           else "never gone through") + ")")
            if rows:
                walls.append(f"  {dest} — {ways} way(s) in on the "
                             f"printed map:\n" + "\n".join(rows))
        if walls:
            out += ("\n\nEVERY PRINTED WAY INTO A PLACE YOU HAVE NEVER "
                    "REACHED, and what has happened at each:\n"
                    + "\n".join(walls))
    if seen:
        # Same cliff, same remedy: bounded, and it says what it dropped.
        shown_seen, cut = seen[:40], max(0, len(seen) - 40)
        out += ("\n\nWHAT WAS SEEN IN EACH AREA (so you can aim a subgoal "
                "at the RIGHT part of a map — the same map id can have "
                "several unconnected parts, and only one of them holds the "
                "thing you need; * = this run has never pressed it)"
                + (f", first {len(shown_seen)} of {len(seen)} areas"
                   if cut else "")
                + ":\n" + "\n".join(shown_seen))
    fired = [f"  {f} fired in {region}"
             for f, region in sorted((d.get("flag_sites") or {}).items())]
    hints = d.get("hints") or {}
    if hints:
        # THE PROMPT HAS A CLIFF AND IT EATS THE FRONT. Ollama evaluates at
        # half of num_ctx and drops the START of an over-long prompt, which
        # is where the goal, the predicates and the map vocabulary live —
        # so an evidence block that grows without bound does not merely
        # crowd the rest, it silently deletes the instructions. This block
        # doubled the day the dialogue capture started keeping whole
        # speeches instead of final pages. Keep the places the run has
        # spent the most time in, which are the places it is stuck, and SAY
        # what was left out rather than quietly dropping it.
        vis_r = d.get("visits") or {}
        ranked = sorted(hints, key=lambda r: -vis_r.get(r, 0))
        keep = sorted(ranked[:14])
        # WHAT A PERSON SAID, ONCE. Three things clutter this ledger: the
        # harness's own feedback filed under whatever op was running
        # ("field_move: AAAAA hacked away with CUT!", six times), the same
        # sentence heard in several places, and a speech recorded at two
        # lengths from before whole-page capture — so the guard's truncated
        # "Oh wait there, the road's closed." now sits beside his full
        # line. Keep the longest telling of each, drop what no NAMED thing
        # said, and never repeat a sentence the model has already read.
        # NOT by speaker: the Saffron guard's line is filed under use_warp,
        # because he speaks when you walk into his gate and no NPC name is
        # attached. Filtering on the op name deleted the one sentence this
        # run most needs. What marks harness noise is the CONTENT — a line
        # narrating the player's own action rather than addressing them.
        _noise = ("hacked away with", "there are no pok", "saved the game",
                  "got away safely", "was thrown", "used ")
        def _speeches(lines):
            best: dict = {}
            for ln in lines:
                who, _, said = ln.partition(": ")
                said = said.strip()
                low = said.lower()
                if not said or any(w in low for w in _noise):
                    continue            # the harness narrating, not speech
                if _looks_like_item_name(who):
                    ln = f"an item: {said}"
                k = said[:40]
                if len(said) > len(best.get(k, "")):
                    best[k] = ln
            return list(best.values())
        shown, said_before = [], set()
        for r in keep:
            # A shorter telling of a speech already shown is the same
            # speech: the guard's pre-fix "Oh wait there, the road's
            # closed." is the tail of his full "I'm on guard duty. Gee,
            # I'm thirsty, though! Oh wait there, the road's closed.",
            # recorded in another region before whole-page capture landed.
            def _new(ln):
                said = ln.partition(": ")[2].strip()
                return not any(said in prev or prev in said
                               for prev in said_before)
            fresh = [ln for ln in _speeches(hints[r]) if _new(ln)]
            said_before.update(ln.partition(": ")[2].strip() for ln in fresh)
            if fresh:
                shown.append(f"  in {r}:\n    " + "\n    ".join(fresh[-4:]))
        body = "\n".join(shown)
        more = len(hints) - len(keep)
        out += ("\n\nWHAT PEOPLE HAVE SAID, and where they said it. This "
                "game explains its own gates out loud, so a sentence here is "
                "often the reason a route did not work"
                + (f" (the {len(keep)} places you have stood in most; "
                   f"{more} quieter place(s) not shown)" if more else "")
                + ":\n" + body)
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
    # WAYS THAT TURNED THE RUN BACK, with the model's own lifting
    # condition where it named one — the blockers ledger, so a rewrite
    # does not send the plan back into a guard it has met three times
    # without a step for what the model itself said opens the way.
    blk = [b for b in (d.get("blockers") or {}).values()
           if isinstance(b, dict) and not b.get("cleared")]
    if blk:
        rows = []
        for b in sorted(blk, key=lambda b: (-int(b.get("n") or 0),
                                             str(b.get("where")))):
            row = f"  {b.get('where')} ({b.get('key')}): turned back"
            if b.get("n"):
                row += f" {b['n']}x"
            if b.get("what"):
                row += f" — {b['what']}"
            if b.get("your_words"):
                row += f" — you called it: {b['your_words']}"
            if b.get("lifts"):
                row += f" — YOU SAID {json.dumps(b['lifts'])} lifts it"
            else:
                row += " — nothing named yet as what lifts it"
            rows.append(row)
        out += ("\n\nWAYS THAT TURNED THE RUN BACK (a plan that walks into "
                "one again without first meeting what lifts it is a plan "
                "that has already failed):\n" + "\n".join(rows[:8]))
    # Nearness = the maps the run has spent the most time in, which is
    # where it is and where it keeps returning. Mechanical, not a judgment
    # about what matters.
    vis_m: dict = {}
    for r, n in (d.get("visits") or {}).items():
        m = r.split("|")[0]
        vis_m[m] = vis_m.get(m, 0) + n
    near = {m for m, _ in sorted(vis_m.items(), key=lambda kv: -kv[1])[:14]}
    return _fit(out, near=near)


# Ollama evaluates a prompt at HALF of num_ctx and drops its FRONT — where
# the goal, the predicates and the map vocabulary live — so oversize does
# not degrade the reasoning, it deletes the instructions. Per-block caps
# were not enough: the walked graph and the event-site list grow with every
# region entered, so the total crept back over the cliff within the hour.
# Budget the whole thing instead, trimming the blocks that grow, and say
# what was dropped. 22000 chars leaves room for the journal, the drafts and
# the vocabulary inside a 12288-token evaluation.
EVIDENCE_BUDGET = 22000


def _fit(text: str, budget: int = EVIDENCE_BUDGET,
         near: set | None = None) -> str:
    """Trim the growing blocks until the evidence fits, FAREST FIRST.

    These lists are alphabetical by region, not chronological, so "oldest"
    and "newest" are not properties they have — a head-and-tail trim keeps
    the B's and the V's and silently drops everything from Mt Moon to Rock
    Tunnel. What actually distinguishes a line is whether it concerns
    ground near where the party is or is going: those are the facts a plan
    written now can act on. Keep them, drop the far ones, and say how many
    went."""
    while len(text) > budget:
        # A HEADER IS A RUN OF CAPITALS, not thirteen characters drawn
        # from a set that happens to include lowercase-adjacent
        # punctuation. The old pattern needed 12+ chars of [A-Z ,'-] after
        # the first letter, so `AREA CODES you may use...` failed on the
        # `y` of "you" at character 11 and the whole block was glued to
        # whichever one came before it. Four consecutive capitals is what
        # every real header here has and no prose paragraph does.
        blocks = re.split(r"\n\n(?=[A-Z]{4,})", text)
        i = max(range(len(blocks)), key=lambda j: len(blocks[j]))
        lines = blocks[i].splitlines()
        if len(lines) < 8:
            return text[:budget] + "\n[evidence truncated to fit]"
        head, body = lines[0], lines[1:]
        keep_n = max(4, len(body) * 3 // 4)
        if near:
            body.sort(key=lambda l: 0 if any(m in l for m in near) else 1)
        kept, cut = body[:keep_n], len(body) - keep_n
        blocks[i] = "\n".join(
            [head] + sorted(kept)
            + [f"  ... {cut} line(s) about ground far from here not shown ..."])
        text = "\n\n".join(blocks)
    return text


def prompt_guard(where: str, **parts) -> None:
    """Say BEFORE the call that a prompt is near the cliff, and name what is
    making it big.

    chat() already notices truncation, but only afterwards and only as a
    number — and the 48 truncations already in this repo's logs (44 at the
    12288 cap, 4 at 8192) all came from the same place, the review prompt,
    every one of them right after "[drafts] 6 earlier draft(s) shown". The
    number alone never said that. This does.
    """
    total = sum(len(v or "") for v in parts.values())
    cap = brock_probe.NUM_CTX // 2
    est = total // 4                    # ~4 chars per token, good enough
    if est < cap * 0.9:
        return
    big = sorted(parts.items(), key=lambda kv: -len(kv[1] or ""))[:3]
    print(f"[prompt] {where} is ~{est} tokens against a {cap} cap"
          + (" — IT WILL BE TRUNCATED FROM THE FRONT" if est >= cap else
             " — close to the cliff")
          + ". Biggest parts: "
          + ", ".join(f"{k} {len(v or '') // 4}" for k, v in big))


def evidence_text(observed, journal, drafts) -> str:
    """The whole evidence prefix, budgeted AS A WHOLE.

    EVIDENCE_BUDGET was applied inside observed_text and nowhere else, so
    it capped the walked graph and then let the journal, the draft list and
    the plan JSON pile on top of it unmeasured. Ollama evaluates at half of
    num_ctx and drops the FRONT — where the predicates, the map ids and the
    guidance live — so going over does not blur the reasoning, it deletes
    the instructions, and a review then reaches for a predicate that does
    not exist. The three growing blocks are budgeted together; the
    vocabulary is appended AFTER this and is never trimmed.
    """
    return _fit((observed_text(observed) if observed else "")
                + (journal_text(journal) if journal else "")
                + drafts_text(drafts or []))


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
            # ...but only claim it when it is TRUE. A route walk that ends
            # with the condition met can have distilled==0 and still have
            # fought a gym leader on the way in, so op-count alone called
            # the Cascade Badge "nothing was done".
            idle = (r.get("via") == "pre-check"
                    or (k == "escalate_success" and not r.get("distilled")
                        and not r.get("walked")))
            events.append(f"  OK      {r.get('subgoal')}"
                          + (" (already true on arrival — nothing was done,"
                             " no building was entered)" if idle else ""))
        elif k == "subgoal_failed":
            events.append(f"  FAILED  {r.get('subgoal')}")
        elif k == "subgoal_skipped":
            events.append(f"  SKIPPED {r.get('subgoal')} — the model "
                          f"declared it moot: \"{(r.get('reason') or '')[:120]}\"")
        elif k == "skip_last_step":
            # the model's own verdict on the OBJECTIVE: it asked to skip the
            # plan's final step, i.e. it holds the objective is already
            # fulfilled or its condition is wrong. Said once per verdict.
            line = (f"  MOOT?   the model asked to SKIP the plan's FINAL step "
                    f"{r.get('subgoal')} — its words: "
                    f"\"{(r.get('reason') or '')[:140]}\"")
            if line not in events:
                events.append(line)
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
    tried = tried_text(recs)
    if not events and not unreach and not tried:
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
            objs = ["an item" if _looks_like_item_name(o) else o
                    for o in objs]
            who = f", with {', '.join(objs)} right there" if objs else ""
            out += (f"  during {sg}: could not get {tgt} in {reg} — "
                    f"{n} attempts{who}\n")
    return out + tried


def _canon_op(step: dict) -> str:
    op = step.get("op")
    if op in ("use_warp", "walk_to", "field_move"):
        return f"{op}({step.get('x')},{step.get('y')})"
    if op == "cross":
        return f"cross({step.get('dir')})"
    if op == "interact":
        return f"interact({step.get('name') or (step.get('x'), step.get('y'))})"
    if op in ("buy", "sell", "use_item", "toss"):
        return f"{op}({step.get('item')})"
    return f"{op}()"


def tried_text(recs: list, top_subgoals: int = 4, top_ops: int = 5) -> str:
    """WHAT EACH SUBGOAL OF THE LAST PLAN TRIED, COUNTED — and what the
    executor's model said it was doing while it tried.

    The rewrite pass is asked to fix a leg that failed, and it was shown
    the story (wipes, walls, money) and the could-not-get ledger — but not
    the repetition itself: that talk_to_clerk ran 27 escalation rounds over
    four attempts, proposed interact(VIRIDIANMART_CLERK) nine times and got
    the shop counter every time, and that its own plans read "I will check
    the mart clerk again" five rounds running. A plan that does the same
    thing five times with nothing changing is not a plan the author can
    recognise if the five are collapsed into one FAILED line. This is the
    executor's own ops and the model's own words, counted; nothing here
    says what to do instead.

    Scoped to the LAST plan in the journal (every attempt of it): the leg
    being rewritten is the one whose evidence this is."""
    # the last plan's goal, and everything from its first attempt onward
    starts = [i for i, r in enumerate(recs) if r.get("kind") == "plan_start"]
    if not starts:
        return ""
    goal = recs[starts[-1]].get("goal")
    first = next(i for i in starts if recs[i].get("goal") == goal)
    seg = recs[first:]
    per: dict = {}
    pending: dict = {}
    for r in seg:
        k = r.get("kind")
        sg = r.get("subgoal")
        if not sg:
            continue
        d = per.setdefault(sg, {"attempts": 0, "rounds": 0, "ops": {},
                                "last": {}, "plans": {}, "goal": ""})
        if k == "escalate_start":
            # one per attempt (and per backtrack); subgoal_attempt is only
            # logged for steps that HAVE a macro to replay, and the steps
            # that get here mostly do not
            d["attempts"] += 1
            d["goal"] = d["goal"] or (r.get("goal") or "")
        elif k == "escalate_proposal":
            d["rounds"] += 1
            macro = [m for m in (r.get("macro") or []) if isinstance(m, dict)]
            for m in macro:
                c = _canon_op(m)
                d["ops"][c] = d["ops"].get(c, 0) + 1
            pending[sg] = [_canon_op(m) for m in macro]
            pl = (r.get("plan") or "").strip()
            if pl:
                d["plans"][pl] = d["plans"].get(pl, 0) + 1
        elif k == "escalate_feedback":
            for t in (r.get("trace") or []):
                head = t.split(":", 1)[0]
                for c in pending.get(sg, []):
                    if head.startswith(c.split("(")[0]) and c not in d["last"]:
                        d["last"][c] = t.split(":", 1)[1].strip()[:110] \
                            if ":" in t else t[:110]
                # keep the LAST outcome, not the first
                for c in pending.get(sg, []):
                    if head.startswith(c.split("(")[0]):
                        d["last"][c] = t.split(":", 1)[1].strip()[:110] \
                            if ":" in t else t[:110]
            pending.pop(sg, None)
    rows = [(sg, d) for sg, d in per.items() if d["rounds"] >= 3]
    if not rows:
        return ""
    rows.sort(key=lambda kv: -kv[1]["rounds"])
    out = ["\n\nWHAT EACH STEP OF THAT PLAN TRIED, counted over all its "
           "attempts — the executor's own ops and, in quotes, what it "
           "said it was doing. A step that proposes the same thing again "
           "and again with the same result is a step whose IDEA is wrong, "
           "not one that needs another go:"]
    for sg, d in rows[:top_subgoals]:
        out.append(f"  {sg}: escalated {d['attempts']} time(s), "
                   f"{d['rounds']} round(s) in all"
                   + (f" — \"{d['goal'][:80]}\"" if d["goal"] else ""))
        for c, n in sorted(d["ops"].items(), key=lambda kv: -kv[1])[:top_ops]:
            last = d["last"].get(c)
            out.append(f"      {c} x{n}" + (f" — last: {last}" if last else ""))
        for pl, n in sorted(d["plans"].items(), key=lambda kv: -kv[1])[:3]:
            out.append(f"      it said (x{n}): \"{pl[:140]}\"")
    return "\n".join(out)


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


DRAFTS_DIR = Path("plans/drafts")


def _goal_slug(goal: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "_", goal.lower()).strip("_")[:48]
            or "goal")


def _skel(plan: dict) -> list:
    return [(s.get("id"), json.dumps(s.get("done_when"), sort_keys=True))
            for s in plan.get("subgoals") or []]


def archive_draft(goal: str, plan: dict):
    """Anti-variance memory: every plan authored for a goal is banked and
    survives restarts. The donor lore re-rolled on every fresh authoring
    (captain -> rooftop -> Bill -> Rocket) and the one CORRECT draw was
    deleted with its campaign cycle — a dice roll paid and thrown away."""
    try:
        d = DRAFTS_DIR / _goal_slug(goal)
        d.mkdir(parents=True, exist_ok=True)
        skel = _skel(plan)
        for f in sorted(d.glob("*.json")):
            try:
                if _skel(json.loads(f.read_text())) == skel:
                    return
            except (ValueError, OSError):
                continue
        n = len(list(d.glob("*.json"))) + 1
        (d / f"{n:03d}.json").write_text(json.dumps(plan, indent=1))
    except OSError:
        pass


def load_drafts(goal: str, limit: int = 6) -> list:
    out = []
    try:
        for f in sorted((DRAFTS_DIR / _goal_slug(goal)).glob("*.json"))[-limit:]:
            try:
                out.append(json.loads(f.read_text()))
            except (ValueError, OSError):
                continue
    except OSError:
        pass
    return out


def drafts_text(drafts: list) -> str:
    if not drafts:
        return ""
    lines = ["\n\nPLANS YOU WROTE FOR THIS SAME GOAL IN EARLIER ATTEMPTS. "
             "Different attempts remembered different things; none is "
             "binding, but a subgoal from an earlier draft that the "
             "evidence supports may be ADDED under the same rules as any "
             "other addition:"]
    for i, p in enumerate(drafts, 1):
        skel = "; ".join(
            f"{s.get('id')} {json.dumps(s.get('done_when'))}"
            for s in (p.get("subgoals") or [])[:20])
        lines.append(f"  draft {i}: {skel}")
    return "\n".join(lines)


PLAN_PICK_SYS = """You wrote several PLANS for the same Pokemon Red goal,
in separate sittings. Different sittings remembered different things about
the game, and one of these is your best account of how to do it.

Read them and pick ONE, whole. You are choosing between accounts, not
editing them: nothing you write here is kept except the number.

Judge them on whether the ROUTE is one the game allows and whether the
final condition is really the goal. A plan that names places this run has
proven it cannot reach is worse than a shorter one that starts somewhere
it can stand right now.

Reply with ONLY a JSON object, the reason FIRST:
{"why": "one sentence", "pick": N}"""


def _plan_digest(plan: dict) -> str:
    return " -> ".join(
        f"{s.get('id')}{json.dumps(s.get('done_when'), sort_keys=True)}"
        for s in (plan.get("subgoals") or []))


def pick_plan(goal: str, plans: list, model: str,
              start: str | None = None) -> dict:
    """The model chooses among its OWN drafts; the harness only counts.

    Same lever that took the variance out of the outline, one level down.
    A single leg draw is high-variance in exactly the way the outline was:
    six plans for "Retrieve the Silph Scope" named four different buildings
    and never converged, and each one was played to exhaustion before the
    next was written. Drawing several at once and choosing between them
    spends the same tokens on comparison rather than on walking.

    Choose-only, like the outline merge: the reply is an index, and what
    comes back is that draft VERBATIM. Nothing here composes a plan.
    """
    if len(plans) == 1:
        return plans[0]
    body = (f"THE GOAL: {goal}\n"
            + (f"WHERE THE PARTY STANDS NOW: {start}\n" if start else "")
            + "\nYOUR PLANS:\n"
            + "\n\n".join(
                f"  {i}. " + "\n     ".join(
                    f"{s.get('id')}: {json.dumps(s.get('done_when'))}"
                    for s in (p.get("subgoals") or []))
                for i, p in enumerate(plans, 1)))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": PLAN_PICK_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
        n = ans.get("pick")
        n = int(n) if str(n).strip().lstrip("-").isdigit() else 0
    except (ValueError, KeyError, OSError, AttributeError, TypeError):
        n = 0
    if not 1 <= n <= len(plans):
        print(f"[draws] no usable pick; keeping draft 1 of {len(plans)}")
        return plans[0]
    print(f"[draws] picked draft {n} of {len(plans)}: "
          f"{str(ans.get('why') or '')[:160]}")
    return plans[n - 1]


def author_best_of(goal: str, model: str, draws: int = 3,
                   start: str | None = None) -> dict | None:
    """Several independent plans for one goal, then the model picks one."""
    plans, seen = [], {}
    for i in range(max(1, draws)):
        # ONE FLAKY CALL MUST NOT COST THE CHAIN. Taking several drafts
        # multiplies the chances of a timeout, and the first one killed the
        # whole run: author() lets a transport error out, fresh_discovery
        # runs under set -e, and a 25-leg campaign died on a socket. A draw
        # that fails is a draw we do not have, nothing more.
        try:
            p = author(goal, model, start=start)
        except (OSError, TimeoutError, ValueError) as e:
            print(f"[draws] draft {i + 1} failed ({type(e).__name__}: "
                  f"{str(e)[:80]}) — carrying on with the rest")
            continue
        if not p:
            continue
        key = _plan_digest(p)
        if key in seen:                      # same account written twice
            seen[key] += 1
            continue
        seen[key] = 1
        plans.append(p)
        # Every DRAW, not just the winner. Only the picked plan was
        # archived, so how much the drafts actually differed — the one
        # number that says whether taking three of them is worth three
        # times the calls — was thrown away at the moment it was measured.
        archive_draft(goal, dict(p, drawn_as=f"draw {len(plans)}"))
        print(f"[draws] draft {len(plans)}: {len(p['subgoals'])} subgoals: "
              + " -> ".join(
                  str((s.get("done_when") or {}).get("map")
                      or (s.get("done_when") or {}).get("badge") or "?")
                  for s in p["subgoals"]))
    if not plans:
        return None
    for k, n in seen.items():
        if n > 1:
            print(f"[draws] one shape was written {n}x")
    return pick_plan(goal, plans, model, start=start)


# How many subgoals one review round may INVENT. Gap-filling is a step or
# two ("you cannot reach Route 7 from Route 6 without crossing Saffron");
# a dozen is a different plan wearing the audit's clothes.
MAX_REVIEW_ADDS = 4


def review(goal: str, plan: dict, model: str, start: str | None = None,
           rounds: int = 2, observed: Path | None = None,
           journal: Path | None = None, drafts: list | None = None) -> dict:
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
    repeat_add = None
    base = (evidence_text(observed, journal, drafts)
            + build_prompt(goal, start))
    for rnd in range(1, rounds + 1):
        _rev = build_review(goal, plan, start)
        prompt_guard("the review prompt", system=REVIEW_SYS,
                     evidence_and_vocabulary=base, plan_under_review=_rev)
        reply = brock_probe.chat(
            [{"role": "system", "content": REVIEW_SYS},
             {"role": "user", "content": base + "\n\n" + _rev}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            continue
        try:
            revised = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        normalize_items(revised)
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
        # A REVISION IS AN AUDIT, NOT A NEW PLAN. The outline review was
        # bounded for exactly this reason (97315bb: reorder, insert and
        # flag, never delete or reword) after a free rewrite deleted Bill.
        # The plan review kept its licence and used it: handed the draft
        # the model had just CHOSEN for avoiding the shut Saffron gate, it
        # returned a seventeen-step tour of western Kanto that walked back
        # to Route 6 and through Saffron anyway — twelve subgoals invented
        # in one pass, and the choice the drafts lever had just made
        # discarded on the way. Filling a gap is one or two steps. Anything
        # past that is a plan the pick never selected, so keep the pick.
        added = [x["id"] for x in revised["subgoals"]
                 if x["id"] not in {y["id"] for y in plan["subgoals"]}]
        # THE CAP DEFENDS A SOUND PICK, NOT A BROKEN ONE. It was added to
        # stop an audit discarding the draft the model had just chosen —
        # but the very next pass it refused a review that was inserting the
        # eastern road into a plan hopping ROUTE_5 -> ROUTE_6 -> ROUTE_7,
        # two pairs the printed map does not join at all. A plan with a
        # hole in its route has not earned that protection: filling a hole
        # IS the audit's job, and doing it properly can take more than a
        # couple of steps. Sound plans keep the tight cap.
        hops = [ (a.get("done_when") or {}).get("map")
                 for a in plan["subgoals"] ]
        hops = [h for h in hops if h]
        gap = any(b not in (MAP_EDGES.get(a) or {}).values() and a != b
                  for a, b in zip(hops, hops[1:])
                  if a in MAP_EDGES and b in MAP_EDGES)
        cap = MAX_REVIEW_ADDS * 4 if gap else MAX_REVIEW_ADDS
        # SAYING THE SAME THING TWICE IS CONVICTION, NOT THRASH. The cap
        # stops an audit replacing a plan wholesale on a whim, and a whim
        # does not come back identical. Asked to review a three-step plan
        # to Celadon, this one proposed the SAME eleven-step eastern route
        # in both rounds — the route the run genuinely needs, and the only
        # one the model has ever found. Refusing it twice for being large
        # was the cap outliving its reason.
        if repeat_add is not None and added and added == repeat_add:
            print(f"[review] round {rnd} proposed the same {len(added)} "
                  f"addition(s) again — taking it as considered, not a "
                  f"rewrite")
            cap = max(cap, len(added))
        repeat_add = list(added)
        if len(added) > cap:
            print(f"[review] round {rnd} added {len(added)} subgoals "
                  f"(cap {MAX_REVIEW_ADDS}) — that is a rewrite, not an "
                  f"audit; keeping the plan as chosen: "
                  f"{', '.join(added[:6])}...")
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

HOW THESE GET PLAYED, so you can write them to fit. The list is worked
through IN ORDER, one objective at a time, and nothing is pursued outside
its own turn — there is no working on something quietly in the background
while another objective runs. So an objective naming an ACCUMULATED state
(a full team, a pile of money, a set of items) is not gathered along the
way: it is begun from wherever things stand at its place in the list, with
everything before it already finished and nothing after it started yet. If
you want something built up gradually, write the separate acquisitions
where they each actually happen, instead of one objective at the end that
names the total.

THE EIGHT GYM BADGES are given to you below, because they are printed on
the box and recited by anyone who has one, and because remembering them is
not the part of this worth your effort. LISTED ALPHABETICALLY BY LEADER,
which is deliberately NOT the order to fight them in:

  Defeat Blaine for the Volcano Badge
  Defeat Brock for the Boulder Badge
  Defeat Erika for the Rainbow Badge
  Defeat Giovanni for the Earth Badge
  Defeat Koga for the Soul Badge
  Defeat Lt. Surge for the Thunder Badge
  Defeat Misty for the Cascade Badge
  Defeat Sabrina for the Marsh Badge

Include all eight, word for word, and put each one where you judge it
belongs. Which order they go in, what has to happen between them, and
everything else the playthrough needs, is still entirely yours.

Expect about THIRTY objectives, those eight among them. THE COUNT IS THE
POINT. Eight of the thirty are badges, so the other twenty-odd are the
journey between them — the caves crossed, the people helped, the things
fetched, the towns arrived in. A list much shorter than thirty has folded
that journey away, and the journey is the half that a run gets stuck in.
Unfold it.

Reply with ONLY a JSON array of strings."""


# Doubts the outline passes record about their own product, persisted next
# to outline.txt so the leg author sees them when that leg comes up. The
# note is the model's own words fed back to itself — not our knowledge.
OUTLINE_NOTES = []


# AN OBJECTIVE THAT HEDGES IS NOT AN OBJECTIVE. OUTLINE_SYS already asks
# for "a thing that is either done or not done — a milestone you could tell
# someone you had reached", and a draft still produced "Defeat Giovanni (if
# not already done) and reach Cinnabar Island". That is unwritable as a
# done_when and it is a duplicate wearing a disclaimer. Dropped from the
# draft rather than argued with: whatever else that draft said still counts,
# and the real objective underneath ("reach Cinnabar Island") is one the
# other five drafts also name.
_HEDGES = re.compile(
    r"\bif (?:not )?already\b|\bif (?:you )?(?:need|necessary|possible)"
    r"|\(if\b|\bor equivalent\b|-equivalent\b|\bas needed\b|\bif able\b",
    re.I)


def _stem(w: str) -> str:
    """Crude enough for objective wording: surfing -> surf, fossils -> fossil.

    Exists because "Obtain the HM for Surf" and "Obtain the HM for surfing"
    reached one outline as two objectives, and the review flagged both as
    duplicates of each other while the design kept them anyway.
    """
    # PLURALS ONLY. Stripping "-ing" as well turned FLYING into FLY, and in
    # this game a TYPE and a MOVE routinely share a name — Fly/Flying,
    # Surf, Cut, Fire, Psychic — so "the party holds a FLYING type" was
    # judged the same objective as "a party Pokemon knows the move FLY" and
    # deleted. It bought "Obtain the HM for surfing" matching "...for Surf",
    # which is a DUPLICATE, and a duplicate leg completes instantly while a
    # deleted one never runs at all. Wrong trade; taken back.
    for suf in ("es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


# The eight, in the same words OUTLINE_SYS hands over, so a merge that
# drops one can be noticed. Alphabetical by leader here too — this list is
# a checklist, never an itinerary.
#
# SEEDED, AND SAID SO (user's ruling, 2026-08-17). The audit flags this as
# borderline: badge NAMES are on the box, but the leader-to-badge pairing
# and the objective wording are ours, and _check_badges re-inserts them
# against the model's own choice. The ruling is that this is pamphlet tier —
# the sort of thing the booklet in the box tells a player before they start —
# and so it stays, stated plainly rather than quietly.
# What that means for the claim, exactly: EIGHT of roughly thirty outline
# objectives are harness-seeded. Everything else on the list, and every plan
# under every objective, is the model's. Nobody should have to read
# _check_badges to find that out.
SEEDED_BADGES = (
    "Defeat Blaine for the Volcano Badge",
    "Defeat Brock for the Boulder Badge",
    "Defeat Erika for the Rainbow Badge",
    "Defeat Giovanni for the Earth Badge",
    "Defeat Koga for the Soul Badge",
    "Defeat Lt. Surge for the Thunder Badge",
    "Defeat Misty for the Cascade Badge",
    "Defeat Sabrina for the Marsh Badge",
)


def _check_badges(legs: list) -> list:
    """Every seeded badge objective survives to the final outline.

    The merge chooses, and choosing can drop. A missing gym is not a leg
    the ladder can rescue — nothing downstream knows it was ever meant to
    be there — so a dropped one is put back and SAID OUT LOUD. It goes at
    the end because the harness has no business deciding where a gym sits;
    the review runs after this and may move it, and failing that a leg out
    of place still gets played, while a leg that is gone never does.
    """
    have = [_names(l) for l in legs]
    out = list(legs)
    for want in SEEDED_BADGES:
        key = _names(want)
        if any(key & h for h in have):
            continue
        print(f"[outline] !! {want!r} was seeded and the outline lost it — "
              f"putting it back at the end")
        out.append(want)
    return out


SKELETON = (
    "Defeat Brock for the Boulder Badge",
    "Defeat Misty for the Cascade Badge",
    "Defeat Lt. Surge for the Thunder Badge",
    "Defeat Erika for the Rainbow Badge",
    "Defeat Koga for the Soul Badge",
    "Defeat Sabrina for the Marsh Badge",
    "Defeat Blaine for the Volcano Badge",
    "Defeat Giovanni for the Earth Badge",
    "Defeat the Elite Four",
    "Defeat the Champion",
)

GAP_SYS = """You are filling in a Pokemon Red playthrough. The SPINE of it
is fixed and given to you — the badges in the order they are taken, and the
end of the game after them. You are not being asked to change it or to
judge it.

You are asked about ONE GAP in it: what has to happen between the objective
before the gap and the objective after it, for the one after to be possible
at all.

Think about what stands between them: a road that is shut until somebody is
helped, a thing that must be fetched or handed over, a move you cannot get
past without, a person who wants something first. Those are the objectives
that belong in this gap. Anything a player must do to make the next badge
reachable belongs here; anything they merely COULD do does not.

Write each as a short phrase in the player's own terms, a thing that is
either done or not done. Do not restate the objectives on either side of
the gap, and do not write the steps inside an objective — those are
authored later, from the objective alone.

An empty gap is a real answer. Reply with ONLY a JSON array of strings, in
the order they should be done."""


def _gap_draw(goal: str, before: str | None, after: str | None,
              model: str, cap: int, spine: tuple) -> list:
    """What has to happen between two fixed points of the spine.

    The whole-list passes kept getting the ORDER wrong — Silph Co. before
    Brock, the S.S. Ticket before the Bill errand that hands it over, Rock
    Tunnel ten objectives late — because nothing anchored an errand to the
    badge it serves. Asked per gap, an errand cannot land in the wrong half
    of the game: it is authored INTO a position rather than assigned one
    afterwards. What goes in each gap is still entirely the model's.
    """
    where = (f"AFTER: {before}\nBEFORE: {after}" if before and after
             else f"BEFORE THE FIRST BADGE: {after}" if after
             else f"AFTER THE LAST: {before}")
    body = ("THE GOAL: " + goal + "\n\nTHE SPINE:\n"
            + "\n".join(f"  {i}. {s}"
                          for i, s in enumerate(spine or SKELETON, 1))
            + f"\n\nTHE GAP YOU ARE FILLING:\n{where}\n\n"
            "What has to happen in that gap?")
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": GAP_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            return []
        got = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return []
    if not isinstance(got, list):
        return []
    out = []
    for x in got[:cap]:
        if not isinstance(x, (str, int, float)):
            continue
        t = str(x).strip()
        if not t or _HEDGES.search(t):
            continue
        # never a restatement of either post it is nailed between
        k = _names(t)
        if k and any(k & _names(s) for s in (before, after) if s):
            print(f"[gap] dropped {t!r}: it restates the badge beside it")
            continue
        out.append(t)
    return out


def _fill_gap(goal: str, before: str | None, after: str | None,
              model: str, cap: int = 8, spine: tuple = (),
              draws: int = 3, max_draws: int = 4) -> list:
    """Ask each gap SEVERAL TIMES and pool, for the same reason drafts are.

    One ask per gap was measured and it starved: the first four gaps of a
    live run came back EMPTY — the stretch holding Mt. Moon, Oak's parcel,
    Bill and the Pokedex, which is exactly where this run keeps walling —
    and the finished outline had lost Mt Moon, Bill, the Silph Scope, the
    Poke Flute, three HMs, Rock Tunnel and Poke Balls against the
    whole-list pipeline's. The whole-list pipeline pools 35-48 distinct
    objectives out of six drafts before it chooses anything; this asked
    eleven questions once each and kept whatever came back. Same variance,
    fewer samples.

    Pooled in FIRST-SEEN order, never ranked by how many draws agreed: the
    merge prompt's own rule is that count is how often you said it, not how
    true it is, and a gate only one draw remembered is still a gate.
    """
    pooled, seen = [], set()
    for r in range(max_draws):
        got = _gap_draw(goal, before, after, model, cap, spine)
        fresh = 0
        for t in got:
            k = _objective_key(t)
            if k and k in seen:
                continue
            if k:
                seen.add(k)
            pooled.append(t)
            fresh += 1
        if r + 1 >= draws and not fresh:
            break
    if len(pooled) > cap:
        print(f"[gap] kept {cap} of {len(pooled)} pooled; dropped: "
              + ", ".join(repr(t) for t in pooled[cap:]))
        pooled = pooled[:cap]
    return pooled


STAGES_PATH = Path("plans/outline.stages")

STAGE_SYS = """Here is a Pokemon Red playthrough outline you wrote. Group
it into STAGES — the stretches a player would think of as one leg of the
journey, usually a region and the work done while you are there.

You are not reordering it and not rewriting it. Every objective keeps its
place and its wording; you are only saying where one stretch ends and the
next begins.

Reply with ONLY a JSON array; each element is {"stage": "<a short name>",
"upto": N} where N is the number of the LAST objective in that stage. The
stages must cover the whole list in order, ending at the last objective."""


def _stage_outline(legs: list, model: str) -> dict:
    """Ask the model where its own outline changes chapter.

    Written because the outline's ORDER is wrong in the small and right in
    the large: one live list put HM01 Cut nine places before the S.S. Anne
    that hands it over, while getting the region-by-region march exactly
    right. Stages are the unit on which that distinction can be acted on —
    across them the order is evidence, within them it is a guess. Recorded
    beside the outline rather than in it, so outline.txt stays one
    objective per line and every reader of it is untouched.
    """
    body = ("THE OUTLINE:\n"
            + "\n".join(f"  {i}. {l}" for i, l in enumerate(legs, 1)))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": STAGE_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            return {}
        got = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return {}
    if not isinstance(got, list):
        return {}
    out, at = {}, 0
    for s in got:
        if not isinstance(s, dict):
            continue
        name = str(s.get("stage") or "").strip()
        try:
            upto = int(s.get("upto"))
        except (TypeError, ValueError):
            continue
        upto = min(max(upto, at + 1), len(legs))
        if not name or upto <= at:
            continue
        for i in range(at, upto):
            out[legs[i]] = name
        at = upto
    # anything past the last stage keeps going under its name rather than
    # falling out: a leg with no stage would be in no block at all
    if at < len(legs) and out:
        last = out[legs[at - 1]]
        for i in range(at, len(legs)):
            out[legs[i]] = last
        print(f"[stages] the last {len(legs) - at} objective(s) were left "
              f"unassigned — kept in {last!r}")
    if out:
        seen = []
        for l in legs:
            if out.get(l) and (not seen or seen[-1] != out[l]):
                seen.append(out[l])
        print(f"[stages] {len(seen)} stages: " + " -> ".join(seen))
    return out


STAGE_MISSING_SYS = """You wrote a Pokemon Red playthrough outline and
grouped it into stages. You are being shown ONE stage of it, with the rest
of the outline around it for context.

The question is only about that stage: IS ANYTHING MISSING FROM IT? Not
from the playthrough as a whole — from this stretch. Something that
happens here, that a player passing through would have to do, that the
list does not say.

Rules:
- You may only ADD, and only within this stage. Nothing already written is
  to be reworded, moved or removed.
- Add nothing that is already there in different words, anywhere in the
  outline — look at the whole list, not just the stage.
- Add nothing that HAPPENS BY ITSELF when something already listed is
  done.
- Add nothing you cannot tell whether you have done. An objective is a
  thing that becomes true.
- "Nothing is missing" is a real answer; reply with an empty array.

Reply with ONLY a JSON array; each element is
{"item": "<the objective>", "after": N}, where N is the number of the
objective in THIS STAGE it comes after (0 = first in the stage)."""


def _stage_missing(goal: str, legs: list, stages: dict, model: str,
                   cap: int = 4) -> list:
    """Ask each stage what it is missing.

    THE WINDOW IS THE WHOLE POINT. Asked about the outline entire, this
    question returned badge no-ops and then "a Pokemon capable of defeating
    X" eight times. Asked badge-to-badge, phrased as what GATES the next
    badge, the first four gaps came back empty — the stretch holding Mt.
    Moon, the parcel and Bill. A stage is the unit in between: wide enough
    to have contents worth reading back, narrow enough that "what else
    happens here" has an answer. The model chose the boundaries itself.
    """
    out = list(legs)
    order = []
    for leg in legs:
        st = stages.get(leg)
        if st and st not in order:
            order.append(st)
    for st in order:
        here = [l for l in out if stages.get(l) == st]
        if not here:
            continue
        body = ("THE GOAL: " + goal + "\n\nTHE WHOLE OUTLINE:\n"
                + "\n".join(f"  {i}. {l}" + (f"   <- {st}"
                                             if stages.get(l) == st else "")
                            for i, l in enumerate(out, 1))
                + f"\n\nTHE STAGE YOU ARE CHECKING: {st}\n"
                + "\n".join(f"  {i}. {l}" for i, l in enumerate(here, 1))
                + "\n\nIs anything missing from that stage?")
        try:
            reply = brock_probe.chat(
                [{"role": "system", "content": STAGE_MISSING_SYS},
                 {"role": "user", "content": body}], model)
            m = re.search(r"\[.*\]", reply, re.S)
            adds = json.loads(m.group(0)) if m else []
        except (ValueError, KeyError, OSError):
            continue
        if not isinstance(adds, list):
            continue
        got = 0
        for a in adds:
            if got >= cap:
                print(f"[stage:{st}] cap reached, {len(adds) - cap} more "
                      f"were offered")
                break
            if not isinstance(a, dict):
                continue
            item = str(a.get("item") or "").strip()
            if not item or _HEDGES.search(item):
                continue
            k = _objective_key(item)
            if k and any(k == _objective_key(l)
                         or len(k & _objective_key(l)) >= 2 for l in out):
                print(f"[stage:{st}] already in the outline: {item!r}")
                continue
            try:
                after = int(a.get("after") or 0)
            except (TypeError, ValueError):
                after = 0
            if after < 1:
                pos = out.index(here[0])
            else:
                anchor = here[min(after, len(here)) - 1]
                pos = out.index(anchor) + 1
            out.insert(pos, item)
            stages[item] = st
            here = [l for l in out if stages.get(l) == st]
            got += 1
            print(f"[stage:{st}] + {item!r}")
    return out


ERA_SYS = """You know Pokemon Red. Someone is asking you about it, in
their own words, one part of the game at a time. Answer the way you would
answer a person: in your own structure, at whatever length the question
deserves, with whatever detail you think matters.

You will be asked about the early game, then the middle, then the late.
Answer only the part asked; you will be able to see what you already said,
so do not repeat yourself.

At the end I will ask you to reduce all of it to a checklist, and only then
will the format matter."""

ERA_ASKS = (
    ("EARLY", "draw me up an outline of the early game of pokemon red "
              "version"),
    ("MIDDLE", "what does the mid game look like"),
    ("LATE", "and the late game, through to the end"),
)

ERA_LIST_ASK = """Now take all the bullet points from all three parts and
put them together into ONE list, in the order they are played.

This is not a summary and nothing is being chosen. Every bullet you wrote
belongs on the list — you are copying your own outline into a flat form,
not deciding what was important.

Each line becomes its own plan, written later and played separately from
the line alone, so write each one as a thing that is either DONE or NOT
DONE — a milestone you could tell someone you had reached. Short phrases in
the player's own terms. No numbering, no headings, no commentary, no steps
folded inside one line, no "if" and no "or equivalent".

Reply with ONLY a JSON array of strings."""


def outline_eras(goal: str, model: str) -> list:
    """Ask for the game in three eras, in ONE conversation, LOOSELY — and
    only ask for the checklist at the end.

    The user's design in two parts. First (2026-08-16): "do it while it has
    the other answers in its context", so the eras share a message list and
    the model can see what it already named. Second (2026-08-17), from a
    conversation the user ran by hand: ASK FOR LESS. Their prompt was
    "draw me up an outline of the early game of pokemon red version" — no
    JSON, no short-phrase rule, no count, no badge list — and it produced
    Oak's parcel, Viridian Forest, the Bicycle, the Card Key, the Rocket
    Hideout, Silph Co and the Saffron blockade, every one of which the
    constrained version had lost.

    And then it wrote its own checklist, unprompted: nine clean one-line
    objectives summarising the prose it had just been allowed to write.
    That is the whole idea here — GENERATION and FORMATTING are different
    jobs, and demanding the format up front was costing the content. The
    objective-quality rules now live in the final ask, applied to material
    that already exists.
    """
    msgs = [{"role": "system", "content": ERA_SYS}]
    for era, ask in ERA_ASKS:
        msgs.append({"role": "user", "content": ask})
        try:
            reply = brock_probe.chat(msgs, model) or ""
        except (OSError, ValueError, KeyError):
            reply = ""
        msgs.append({"role": "assistant", "content": reply})
        print(f"[era:{era}] {len(reply)} chars of prose", file=sys.stderr)
    msgs.append({"role": "user", "content": ERA_LIST_ASK})
    try:
        reply = brock_probe.chat(msgs, model) or ""
    except (OSError, ValueError, KeyError):
        return []
    m = re.search(r"\[.*\]", reply, re.S)
    if not m:
        print("[era] no checklist came back", file=sys.stderr)
        return []
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return []
    out, seen = [], []
    for x in got if isinstance(got, list) else []:
        if not isinstance(x, (str, int, float)):
            continue
        t = str(x).strip()
        if not t or _HEDGES.search(t):
            continue
        k = _objective_key(t)
        if k and any(k == s or len(k & s) >= 2 for s in seen):
            print(f"[era] the checklist repeats itself: {t!r}",
                  file=sys.stderr)
            continue
        if k:
            seen.append(k)
        out.append(t)
    print(f"[era] checklist: {len(out)} objectives", file=sys.stderr)
    return out


SPINE_SYS = """Here are the eight gym badges of Pokemon Red, listed
alphabetically by leader. Put them in the order you would take them.

Reply with ONLY a JSON array of the eight strings, copied exactly as they
are written below, in the order you would do them."""


def _ask_spine(goal: str, model: str, tries: int = 3) -> tuple | None:
    """The ORDER of the badges, from the model, not from us.

    The user's point (2026-08-16): if handing over the badge order feels
    like too much, don't hand it over — ask for it, because the model will
    simply produce it. That keeps the spine model-authored while still
    giving the gap-filling passes something fixed to hang errands between,
    which is the whole benefit. We supply only the eight NAMES, which the
    draft prompt already seeds as vocabulary.

    Refused rather than patched if the answer is not all eight: quietly
    substituting our own order is exactly the thing this exists to avoid.
    """
    want = {frozenset(_names(b)): b for b in SEEDED_BADGES}
    for _ in range(tries):
        try:
            reply = brock_probe.chat(
                [{"role": "system", "content": SPINE_SYS},
                 {"role": "user", "content": "THE GOAL: " + goal
                  + "\n\nTHE EIGHT, ALPHABETICALLY BY LEADER:\n"
                  + "\n".join(f"  {b}" for b in SEEDED_BADGES)}], model)
            m = re.search(r"\[.*\]", reply, re.S)
            if not m:
                continue
            got = json.loads(m.group(0))
        except (ValueError, KeyError, OSError):
            continue
        if not isinstance(got, list):
            continue
        order, seen = [], set()
        for x in got:
            k = frozenset(_names(str(x)))
            hit = next((w for w in want if w & k), None)
            if hit and hit not in seen:
                seen.add(hit)
                order.append(want[hit])
        if len(order) == len(SEEDED_BADGES):
            print("[spine] the model ordered its own badges:")
            for i, b in enumerate(order, 1):
                print(f"  {i}. {b}")
            return tuple(order) + ("Defeat the Elite Four",
                                   "Defeat the Champion")
        print(f"[spine] answer named {len(order)} of {len(SEEDED_BADGES)} "
              f"badges — asking again")
    return None


def outline_skeleton(goal: str, model: str) -> list:
    """Spine given, gaps asked for — the user's design, 2026-08-16.

    An alternative to outline(), not a replacement, so the two can be put
    side by side. What it hands over is the badge ORDER on top of the badge
    NAMES that outline() already seeds; the user's call, on the grounds
    that the order is on the pamphlet and the Cerulean badge house recites
    it. Everything between the badges — which errands exist, what they are
    called, what order they go in inside a gap — is asked for, never
    supplied.
    """
    spine = _ask_spine(goal, model)
    if not spine:
        print("[spine] the model would not order its badges; "
              "falling back to the whole-list outline")
        return outline(goal, model)
    legs = []
    for i, post in enumerate(spine):
        before = spine[i - 1] if i else None
        got = _fill_gap(goal, before, post, model, spine=spine)
        for t in got:
            print(f"[gap] {'before ' + post if not before else 'between'}"
                  f"{'' if not before else f' {before} and {post}'}: {t!r}")
        legs.extend(got)
        legs.append(post)
    tail = _fill_gap(goal, spine[-1], None, model, spine=spine)
    for t in tail:
        print(f"[gap] after {spine[-1]}: {t!r}")
    legs.extend(tail)
    return legs


def _names(text: str) -> frozenset:
    """What an objective is ABOUT: its names, stemmed, verbs thrown away.

    INITIALISMS SURVIVE HERE AND NOWHERE ELSE. _norm_obj strips the dots,
    so "S.S. Ticket" arrives as "s s ticket" and both letters fall out as
    noise — which meant "Obtain the S.S. Ticket" and "Clear the S.S. Anne"
    had NOTHING in common as far as every guard here could tell, and the
    gate-before-what-it-gates rule could not fire on the exact case it was
    written for. Consecutive single letters are glued back into one token.
    """
    merged, run = [], []
    for w in _norm_obj(text).split():
        if len(w) == 1:
            run.append(w)
            continue
        if run:
            merged.append("".join(run))
            run = []
        merged.append(w)
    if run:
        merged.append("".join(run))
    return frozenset(_stem(w) for w in merged
                     if len(w) > 1 and w not in _STOP and w not in _GENERIC)


def _objective_key(text: str) -> frozenset:
    return _names(text)


def _dedupe_outline(legs: list) -> list:
    """Drop objectives that are the same thing twice, keeping the first.

    TWO NAMES IN COMMON, or the same names outright. Equality alone was
    too weak by a mile: one pass produced FIVE S.S. Ticket objectives, each
    naming a different and mostly wrong source — Celadon City, the Celadon
    Game Corner, the Captain, the Game Corner, "the Chief of Saffron City"
    — and every pair differed in that last name, so none of them matched.
    They all share {ss, ticket}.

    Containment is still refused, and two-names is what lets us refuse it:
    "Defeat Giovanni" and "Defeat Giovanni for the Earth Badge" are TWO
    DIFFERENT FIGHTS in this game, the Rocket hideout and the Viridian gym,
    and they share only {giovanni} — one name — so they both survive, while
    the tickets collapse. That pair is the reason this threshold is two and
    not one.
    """
    out, kept = [], []
    for leg in legs:
        key = _objective_key(leg)
        hit = next(((k, t) for k, t in kept
                    if key and (k == key or len(k & key) >= 2)), None)
        if hit:
            print(f"[outline] dropped {leg!r}: the same objective as "
                  f"{hit[1]!r} ({', '.join(sorted(hit[0] & key)) or 'same'})")
            # KEEP WHAT THE LOSER KNEW. First-occurrence-wins threw away
            # "Retrieve the S.S. Ticket from Bill" in favour of the plain
            # "Obtain the S.S. Ticket" that came before it — and BILL is
            # the whole difference between an objective a plan can act on
            # and one it cannot, since his errand is the only thing that
            # opens Cerulean. Which wording is RIGHT is not ours to judge
            # (the specific one is sometimes specifically wrong: another
            # pass had the ticket coming from "the Chief of Saffron
            # City"), so nothing is overwritten. The dropped phrasing is
            # handed to whoever writes that leg's plan, as a note.
            OUTLINE_NOTES.append(
                (hit[1], f"also written as {leg!r} when the outline was "
                         f"drafted; the two were judged the same objective"))
            continue
        if key:
            kept.append((key, leg))
        out.append(leg)
    return out


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
        kept = [x for x in legs if not _HEDGES.search(x)]
        for x in legs:
            if _HEDGES.search(x):
                print(f"[outline] dropped a hedged objective: {x!r}")
        legs = kept
        if len(legs) >= 3:
            return legs
    return None


def outline(goal: str, model: str, rounds: int = 3,
            draws: int = 3, max_draws: int = 6) -> list | None:
    """The MODEL decides what the legs are.

    Handing it "win your first/second/third badge" is our decomposition of
    the game, not its own, and it quietly rules out the objectives that are
    not badges — deliver the parcel, help Bill, get the ticket, learn a
    field move. Those are exactly the ones a run gets stuck behind, and a
    leg it never names is a plan it never writes.

    One draw is high-variance — the same prompt gave nine non-badge
    objectives one day and none the next — so we take several and let the
    model compose the final list from its own drafts (_outline_merge).

    HOW MANY IS SEVERAL: keep drawing while each new draft still says
    something the others did not, and stop when one adds nothing (user,
    2026-08-16, generalising the upkeep round's loop). A fixed three was a
    guess against exactly the variance this docstring describes: three
    draws that happen to agree waste two, and three that all miss the same
    objective have no way to notice.

    THE DRY TEST IS DELIBERATELY CONSERVATIVE and will often not fire.
    Novelty is significant-word CONTAINMENT, so it catches an elaboration
    ("Help Bill" inside "Help Bill with his experiment") but NOT a synonym
    swap: "Defeat Brock for the Boulder Badge" and "Beat Brock for the
    Boulder Badge" each hold a word the other lacks, and count as two.
    Loosening it to a word-overlap RATIO would collapse "Defeat Brock for
    the Boulder Badge" into "Defeat Misty for the Cascade Badge" — they
    share half their significant words and differ only in the proper nouns
    — and losing a gym from the outline is a far worse failure than
    drawing a sixth draft nobody needed. So in practice this usually runs
    to max_draws and the early stop is a bonus, not the mechanism. The
    cost of that is minutes, once per chain; the cost of a false match is
    an objective that never gets planned.
    """
    OUTLINE_NOTES.clear()
    drafts, seen_sigs, tries = [], [], 0
    while len(drafts) < max_draws and tries < max_draws + 2:
        tries += 1
        d = _outline_draw(goal, model, rounds)
        if not d:
            continue
        fresh = []
        for o in d:
            sig = _sig(o)
            if sig and any(sig <= s or s <= sig for s in seen_sigs):
                continue
            fresh.append(o)
            if sig:
                seen_sigs.append(sig)
        drafts.append(d)
        print(f"[outline] draft {len(drafts)}: {len(d)} objectives, "
              f"{len(fresh)} not in any earlier draft"
              + (f" ({', '.join(repr(f) for f in fresh[:3])}"
                 + (", ..." if len(fresh) > 3 else "") + ")" if fresh else ""))
        if len(drafts) >= draws and not fresh:
            print(f"[outline] draft {len(drafts)} added nothing new — "
                  f"stopping at {len(drafts)} drafts")
            break
    if not drafts:
        return None
    if len(drafts) == 1:
        legs = drafts[0]
    else:
        legs = _outline_merge(goal, drafts, model)
        if not legs:
            print("[outline] merge unusable, keeping draft 1")
            legs = drafts[0]
    # ...then ask the finished list what it assumes it already has. Before
    # the review, so anything added is ordered with everything else.
    legs = _check_badges(legs)
    legs = _outline_upkeep(goal, legs, model)
    # LAST, after every pass that can add: the review inserts too, and one
    # outline reached the end holding Surf three times.
    legs = _dedupe_outline(_outline_review(goal, legs, model) or legs)
    stages = _stage_outline(legs, model)
    if stages:
        # ...and now that the outline has chapters, ask each of them what
        # it is missing. Last pass of all: everything before it has had its
        # say, so what is still absent here is absent on purpose or by
        # oversight, and this is the question that tells them apart.
        legs = _dedupe_outline(_stage_missing(goal, legs, stages, model))
        try:
            STAGES_PATH.write_text("".join(
                f"{stages[l]}\t{l}\n" for l in legs if l in stages))
        except OSError:
            pass
    _reconcile_upkeep(legs)
    return legs


def _reconcile_upkeep(legs: list):
    """Make the upkeep list agree with the outline it protects.

    UPKEEP_PATH is written in the middle of authoring, and three passes run
    AFTER it — the review, the dedupe and the per-stage completeness round —
    every one of which can drop an objective or keep a differently-worded
    twin of it. The file was never revisited, so it ended up naming lines
    the outline no longer contains: 7 of 12 entries in the live sample.

    An entry naming a line that is simply GONE is harmless but dishonest
    (it protects nothing); an entry whose wording lost a dedupe to a twin
    is the dangerous one, because the surviving line is then unprotected
    and an upkeep objective the world may not offer — the species does not
    appear, the balls run out — will STOP THE CHAIN. The dedupe records
    which wording absorbed which in OUTLINE_NOTES, so the protection can
    follow the objective to its surviving name instead of being lost.
    """
    try:
        entries = [l for l in UPKEEP_PATH.read_text().splitlines()
                   if l.strip()]
    except OSError:
        return
    if not entries:
        return
    # dropped wording -> the wording that absorbed it
    absorbed = {}
    for kept, note in OUTLINE_NOTES:
        m = re.search(r"also written as '(.+?)' when the outline", note)
        if m:
            absorbed[m.group(1)] = kept
    live, out, moved, lost = set(legs), [], [], []
    for e in entries:
        if e in live:
            out.append(e)
            continue
        # follow the chain of rewordings, bounded (a cycle would hang)
        cur, seen_e = e, {e}
        while cur in absorbed and cur not in live and len(seen_e) < 8:
            cur = absorbed[cur]
            if cur in seen_e:
                break
            seen_e.add(cur)
        if cur in live:
            out.append(cur)
            moved.append((e, cur))
        else:
            lost.append(e)
    out = list(dict.fromkeys(out))
    try:
        UPKEEP_PATH.write_text("\n".join(out) + ("\n" if out else ""))
    except OSError:
        return
    for was, now in moved:
        print(f"[upkeep] protection follows {was!r} -> {now!r}")
    for e in lost:
        print(f"[upkeep] {e!r} is no longer in the outline — dropped")
    print(f"[upkeep] {len(out)} of {len(entries)} entries still name a "
          f"live objective")


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
THIRTY: eight of those are badges, and all the rest is the journey between
them, which is the part worth keeping."""


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


UPKEEP_PATH = Path("plans/outline.upkeep")

# THE WORDS EVERY OBJECTIVE IS MADE OF. What tells you an addition is
# granted by the objective it hangs off is a shared NAME — Brock, HM01,
# the Silph Scope — never a shared verb. Matching on any word at all
# refused "Obtain a Potion" and "Obtain a team of Pokemon" for hanging off
# "Obtain a starter Pokemon", on the strength of the word "obtain": the
# first is a shop trip and the second is the entire reason the upkeep
# round exists, and both were thrown away by a test that could not tell a
# verb from a name. Subtracted from the overlap before it counts.
_GENERIC = frozenset("""
obtain get retrieve acquire find fetch collect deliver bring give
defeat beat win battle fight clear navigate cross enter exit
reach travel visit go return wake help
pokemon pokemons badge badges item items thing things
first second third next new
city town island area house place way path sail
party member team level type types move moves hold holds know knows
every least is at with capable or and the a an of from
""".split())
# ...that last line is about FALSE MATCHES, not about verbs. The two-name
# dedupe collapsed "Obtain the Secret Key from the house in Celadon City"
# into "Obtain the S.S. Ticket from Celadon City" — two different things
# reaching the threshold on {celadon, city} — and "Sail from Vermilion City
# to Cinnabar Island" into "Sail to the Fuchsia City" on {sail, city}. The
# distinctive half of "Celadon City" is Celadon; "city" is scaffolding that
# every third objective carries, and it was doing half the matching.

OUTLINE_UPKEEP_SYS = """You wrote a Pokemon Red playthrough outline. It
is a list of things that HAPPEN. This question is about the PARTY that has
to survive them.

Read it back and answer: WHAT SHOULD BE TRUE OF YOUR PARTY, AND WHEN, that
this list never makes true?

A trainer who only ever walks the story arrives at the end with one
exhausted starter. The catching, the training and the type coverage happen
along the way — but only if they are written down, because this list is
worked through IN ORDER, one objective at a time, and nothing is pursued
outside its own turn. There is no quietly levelling up in the background.

SAY IT AS A STATE THAT BECOMES TRUE, NOT AS A CAPABILITY. These are the
kinds of thing a plan can be held to, and they are the only kinds:
  - every party member is at least level N
  - the party has at least N Pokemon
  - a NAMED species is in the party (or any one of several)
  - the party holds a TYPE: WATER, FLYING, GHOST, GROUND and the rest
  - N species are owned in the Pokedex
  - a party Pokemon knows a particular MOVE

"Obtain a Pokemon capable of defeating Brock" is not one of these. Nobody
can tell whether it has been done, so nothing can act on it. "Every party
member at least level 12", "a WATER type in the party", "catch a PIDGEY or
a RATTATA" all say the same kind of thing in a way that is either true or
not.

Rules:
- You may only ADD. Nothing already on the list may be reworded, moved or
  removed; those decisions were already made.
- Add nothing that is already there in different words.
- Add nothing that HAPPENS BY ITSELF when something already on the list is
  done. If finishing the objective above it hands you the thing, then it
  is not missing — it is that objective, written twice.
- Put each one where it is needed, BEFORE the thing that needs it, not at
  the end.
- If the list genuinely leaves nothing for the party to become, reply with
  an empty array. That is a real answer.

Reply with ONLY a JSON array; each element is
{"item": "<the objective>", "after": N} where N is the outline position it
must come after (0 = before everything)."""


def _outline_upkeep(goal: str, legs: list, model: str,
                    cap: int = 12, rounds: int = 3) -> list:
    """Repeat the question until it stops finding anything.

    ONE PASS IS NOT ENOUGH, and the reason is a dependency rather than a
    failure of attention. Asked once, the live outline came back with
    Potions, Poke Balls and three HMs — every one a real gap, and Poke
    Balls in particular an objective an earlier framing experiment had
    LOST — but nothing about the party. Asked again with those on the
    list, the very next answer was "Capture enough Pokemon to fill a
    party", placed immediately after Poke Balls. It would not schedule
    catching before the means to catch. So the round runs again on its own
    output and stops when a pass adds nothing.
    """
    out, budget = list(legs), cap
    for r in range(rounds):
        before = len(out)
        out = _outline_upkeep_once(goal, out, model, budget)
        gained = len(out) - before
        budget -= gained
        if gained <= 0 or budget <= 0:
            break
        print(f"[upkeep] round {r + 1} added {gained}; asking again")
    # WHICH LEGS ARE UPKEEP, kept beside the outline rather than baked into
    # the objective text: a plan is addressed by its objective's WORDING,
    # so decorating the line would orphan every plan written for it. Same
    # sidecar shape as plans/outline.done. Written once, after the last
    # round, so it holds everything every round added.
    was = set(legs)
    upkeep = [l for l in out if l not in was]
    if upkeep:
        try:
            UPKEEP_PATH.write_text("\n".join(upkeep) + "\n")
        except OSError:
            pass
        print(f"[upkeep] {len(upkeep)} upkeep objective(s) recorded in "
              f"{UPKEEP_PATH}; these never stop the chain")
    return out


def _outline_upkeep_once(goal: str, legs: list, model: str,
                         cap: int = 12) -> list:
    """Ask the outline what it takes for granted, and let it add.

    Measured, not assumed: a run that plans only story beats plays the
    whole game on its starter — 0 balls thrown, 1 extra party member, 4
    species across two runs (DONE.md 2026-08-14b) — and the "have fun,
    catch lots of Pokemon" framing changed the wording of the outline and
    nothing about the play. The reason is structural: what gets a
    done_when gets done, and catching never had one. Asked DIRECTLY
    whether it meant to finish on its starter, the same model called the
    omission glaring and interleaved a team-building path through its own
    list unprompted, which is what this round is.

    ADD-ONLY, and that is not a style choice. The free-rewrite outline
    audit was measured NET-NEGATIVE on a cold list: with no play evidence
    to check against it is a second guess at recall, and it deleted Bill —
    the one objective that opens Cerulean. Same reasoning as
    _outline_review's tied hands. A wrong added leg is recoverable; a
    right leg deleted before play is just gone.
    """
    body = (f"THE GOAL: {goal}\n\nTHE OUTLINE YOU WROTE:\n"
            + "\n".join(f"  {i}. {leg}" for i, leg in enumerate(legs, 1)))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": OUTLINE_UPKEEP_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\[.*\]", reply, re.S)
        if not m:
            return legs
        adds = json.loads(m.group(0))
    except (ValueError, KeyError, OSError):
        return legs
    if not isinstance(adds, list):
        return legs
    result, added = list(legs), []
    for a in adds:
        if len(added) >= cap:
            print(f"[upkeep] stopping at {cap} additions; "
                  f"{len(adds) - cap} more were offered")
            break
        if not isinstance(a, dict):
            continue
        item = str(a.get("item") or "").strip()
        if not item:
            continue
        # ALREADY THERE IN OTHER WORDS. The same test the done-ledger uses
        # against still-listed objectives: a new entry whose significant
        # words are contained in one already on the list is that one.
        sig = _sig(item)
        if sig and any(sig <= _sig(l) or _sig(l) <= sig for l in result):
            print(f"[upkeep] already on the list in other words: {item!r}")
            continue
        try:
            after = int(a.get("after") or 0)
        except (TypeError, ValueError):
            after = 0
        if after < 1:
            pos, where, anchor = 0, "at the start", None
        elif after > len(legs):
            pos, where, anchor = len(result), "at the end", None
        else:
            # after == len(legs) lands here too, not in the branch above:
            # "at the end" and "after the last objective" are the same
            # position, but only one of them knows what it hangs off, and
            # the granted-by-its-anchor check needs to know
            anchor = legs[after - 1]
            pos = result.index(anchor) + 1
            where = f"after {anchor!r}"
        # GRANTED BY THE THING IT HANGS OFF. Asked what its outline assumed,
        # one live pass answered "Obtain the Badge for Brock" after "Defeat
        # Brock" — and then the same for Misty, Surge, Erika, Koga and
        # Sabrina, spending six of its eight additions on objectives the
        # neighbouring one completes for you, and hitting the cap with real
        # upkeep still unsaid. The prompt now forbids it; this is the
        # backstop, and it is narrow on purpose: only an addition anchored
        # DIRECTLY to an objective it shares a name with. That is the exact
        # shape of "X for the thing X gives you", and it also catches the
        # duplicate that slipped the sig test earlier — "Obtain HM01 Cut"
        # anchored to "Clear S.S. Anne and obtain HM01".
        if anchor and (_names(item) & _names(anchor)):
            print(f"[upkeep] refused {item!r}: it hangs off "
                  f"{anchor!r}, which is what gives it to you")
            continue
        result.insert(pos, item)
        added.append(item)
        print(f"[upkeep] + {item!r} {where}")
    if added:
        print(f"[upkeep] {len(added)} objective(s) added; "
              f"{len(result)} in the outline now")
    else:
        print("[upkeep] nothing added")
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
        # A GATE CANNOT GO AFTER THE THING IT GATES. This channel names
        # objectives "the game will not let you past until they are done",
        # and then it chose where to put one — and put "Obtain the S.S.
        # Ticket" NINE places after "Clear the S.S. Anne", with the
        # reason "you cannot board the S.S. Anne without the ticket"
        # written on it. The reasoning was right and the position
        # contradicted it. So: if anything ALREADY EARLIER shares a name
        # with what is being inserted, the insert belongs in front of the
        # earliest of them instead. Its own anchor is exempt — placing a
        # thing next to a related thing is what an anchor is for; this is
        # about the ones it would end up behind.
        anchor = legs[after - 1] if 1 <= after <= n else None
        key = _names(txt)
        if key:
            for j, earlier in enumerate(out[:pos]):
                if earlier == anchor or not (key & _names(earlier)):
                    continue
                print(f"[outline] {txt!r} was to go {where}, but "
                      f"{earlier!r} comes before it and needs it — "
                      f"moving it in front of that instead")
                pos, where = j, f"before {earlier!r}"
                break
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


PULLCHECK_SYS = """You have proposed moving one leg of your own Pokemon Red
outline forward, out of the order you planned it in, because you believe
the stuck leg cannot be done without it. You are proposing to move it a
long way, which is a large claim about your own plan being wrong, so this
one gets checked before it is applied.

Name the THING. What does the stuck leg need that the leg you want to move
would provide — an item, a move, a badge, a door opened, someone gone from
a doorway? One concrete thing, that you could point at.

It has to be something the leg you are moving HANDS YOU. Naming what the
stuck leg is itself trying to get is not an answer; that is the question
said over again.

If you cannot name one, say so. Two legs that mention the same name, or
happen in the same building, or simply feel related, is not one. Saying no
here costs nothing: the run asks a different question instead.

Reply with ONLY a JSON object, the reason FIRST:
{"why": "one sentence", "provides": "the one thing"}   or
{"why": "one sentence", "provides": null}"""


# How far a leg may be pulled on the strength of one question. Beyond
# this the pull has to say what it is FOR. Not a rule about the game —
# a rule about how much the harness will rearrange the model's own list
# on a single answer.
PULL_NEAR = 3
# ...and how far it will rearrange it at all. Beyond PULL_NEAR the pull
# must say what it provides; beyond PULL_MAX it does not happen on any
# answer. Live: "a party Pokemon knows FLY" was judged stuck behind
# "Defeat Erika" (twelve legs later), the confirm answered "HM02" — a
# fluent wrong fact — and the gym in the city the run cannot reach was
# pulled to the front of the list. Twelve legs of the model's own order,
# with Surge, Rock Tunnel and Lavender in between, on one sentence.
PULL_MAX = 8


def confirm_blocker(goal: str, n: int, text: str, gap: int, start: str,
                    journal: str, model: str) -> bool:
    """A long pull must name what it provides, or it does not happen.

    Leg 11 — "Obtain the Secret Key from the Rocket Hideout", an objective
    naming an item that is not in that dungeon — was judged stuck behind
    leg 23, "Defeat Giovanni for the Earth Badge", and the gym pulled
    twelve places forward on a party of one. The run had just fired
    EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI, and leg 23 was the only other line
    on the list with the word Giovanni in it. It reached for the name it
    recognised.

    A name in common survives "what blocks this?" and does not survive
    "what does that give you that this needs?". Asking the second question
    in different words is the whole of the guard; the answer is the
    model's either way.
    """
    body = (f"THE STUCK LEG, number {n - gap}: {goal}\n\n"
            f"THE LEG YOU WANT TO MOVE, number {n}, planned {gap} legs "
            f"later: {text}\n\nWHERE THE RUN STANDS: {start}\n{journal}")
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": PULLCHECK_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return False
    got = str(ans.get("provides") or "").strip()
    why = str(ans.get("why") or "")[:160]
    if not got or got.lower() in ("none", "null", "nothing"):
        print(f"[blocker] refused a {gap}-leg pull: {why}", file=sys.stderr)
        return False
    # THE ANSWER MAY NOT BE THE QUESTION. Asked what the Viridian gym
    # would hand a run stuck on "Obtain the Secret Key from the Rocket
    # Hideout", the model answered "the Secret Key", and explained that
    # the key only appears once Giovanni is beaten and leaves — a fluent
    # account of a game that does not work that way, from a run whose own
    # journal said it had beaten Giovanni and found no key. Raising the
    # burden of proof does not help when the proof can be invented.
    #
    # What cannot be invented is the shape of the reply. A thing the
    # pulled leg HANDS YOU is not the thing the stuck leg is reaching
    # for; when it is, no work has been located, the sentence has just
    # been read backwards. That much the harness can see without knowing
    # one fact about the game.
    if _sig(got) and _sig(got) <= _sig(goal):
        print(f"[blocker] refused a {gap}-leg pull: it says leg {n} provides "
              f"{got!r}, which is what the stuck leg is for — {why}",
              file=sys.stderr)
        return False
    print(f"[blocker] {gap}-leg pull provides {got!r}: {why}",
          file=sys.stderr)
    return True


def check_blocker(goal: str, ahead: list, start: str, journal: str,
                  model: str, leg: int = 0, observed=None, refused=()):
    """The model reorders its own outline when play proves it misordered.

    The Surge leg walled on a bush only CUT clears while the model's own
    outline held "Obtain the HM for Cut" two legs later — four rewrites
    marched back to the gym because a leg cannot reach outside itself.
    The outline is where that knowledge lives, so the outline is what has
    to move, and the model authored it, so the model moves it: the
    harness asks one question and applies a pull-forward, choose-only.

    What the harness does decide is how far it will rearrange the list on
    the strength of that one question. A pull from the next leg or two is
    cheap and usually right. A pull from twelve legs away says the plan
    was badly wrong, and it earns a second question in different words —
    see confirm_blocker. Distance raises the burden; it never forbids.
    """
    body = (f"THE STUCK LEG: {goal}\n\n"
            f"WHERE THE RUN STANDS: {start}\n"
            f"{journal}\n\nTHE LEGS STILL AHEAD:\n"
            + "\n".join(f"  {n}. {t}" for n, t in ahead
                        if _norm_obj(t) not in refused))
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
    if not isinstance(n, (int, float)):
        return None
    n = int(n)
    hit = [(a, t) for a, t in ahead if a == n]
    if not hit:
        return None
    text = hit[0][1]
    # A leg already pulled forward once and failed there is not pulled
    # again — otherwise a wrong pull is re-made every time the ladder
    # comes round, and the reorder budget is spent churning one mistake.
    if _norm_obj(text) in refused:
        print(f"[blocker] refused: leg {n} was pulled forward before and "
              f"did not unstick this", file=sys.stderr)
        return None
    # Moving a finished objective forward accomplishes nothing but four
    # more attempts at it; the sweep would cross it off at the next leg
    # boundary anyway, so settle it here rather than pay for it first.
    if check_already_done(text, start, model, observed=observed):
        print(f"[blocker] refused: leg {n} is already done", file=sys.stderr)
        return None
    gap = n - leg if leg else 0
    if gap > PULL_MAX:
        print(f"[blocker] refused a {gap}-leg pull: further than {PULL_MAX} "
              f"— the list is not rearranged that far on one answer; if "
              f"leg {n} truly comes first, the legs between are where the "
              f"stuck one belongs", file=sys.stderr)
        return None
    # EVERY PULL IS CONFIRMED, NEAR OR FAR. This ran only for pulls further
    # than PULL_NEAR, on the reasoning that a long reach is the suspicious
    # one — true, and it left the CIRCULAR pull entirely unguarded, because
    # the refusal that catches "leg N provides the very thing the stuck leg
    # is for" lives inside confirm_blocker. Live: "Reach Vermilion City"
    # was judged stuck behind "Retrieve the HM01 from the S.S. Anne", a gap
    # of ONE — and the ship is docked in Vermilion, so the pull put the
    # cargo before the port. Adjacent legs are where circularity is most
    # likely, not least: legs N and N+1 are usually about the same stretch
    # of the game. Distance still raises the burden inside confirm_blocker;
    # it is no longer what decides whether to ask at all.
    if not confirm_blocker(goal, n, text, gap, start, journal, model):
        return None
    return n


CHECKDONE_SYS = """You are judging whether a Pokemon Red objective is
ALREADY accomplished, going by where the run now stands. Trust what is in
hand and what has happened over what the wording seems to ask for next —
an objective is about its outcome, not about ceremony after the outcome.
Reply with ONLY {"why": "<one sentence>", "done": true} or
{"why": "<one sentence>", "done": false} — the why comes first."""


def _never_stood_in(goal: str, observed) -> str | None:
    """A map this objective names that the run has NEVER once been on.

    The model's judgment decides which facts satisfy which objective — a
    fossil in the bag settles "Retrieve the MT Moon fossil" and no
    mechanical rule could know that. But "Reach Cerulean City" was judged
    DONE while standing on Route 4 with Cerulean at zero visits, and the
    harness held the record that contradicted it. Refusing a claim its own
    ledger disproves is not judgment; it is not lying to itself.
    """
    if not observed:
        return None
    try:
        d = json.loads(Path(observed).read_text() or "{}")
    except (OSError, ValueError):
        return None
    seen = {r.split("|")[0] for r in (d.get("visits") or {})}
    words = re.sub(r"[^A-Z0-9]+", " ", goal.upper()).split()
    for m in ROUTE_MAPS:
        parts = m.split("_")
        # name it the way a person would: "Cerulean City", "Rock Tunnel"
        if len(parts) < 2 or m in seen:
            continue
        if all(w in words for w in parts):
            return m
    return None


def _badge_not_earned(goal: str, start: str) -> str | None:
    """A badge this objective names that the run is not wearing.

    Companion to _never_stood_in, and the same principle: refusing a claim
    the record disproves is not judgment, it is not lying to yourself.

    "Defeat Giovanni for the Earth Badge" was judged ALREADY DONE by a run
    holding four badges, none of them the Earth Badge, because the leg had
    just fired EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI — a different Giovanni in
    a different building. The judging prompt all but invites it: it says an
    objective is about its outcome and not the ceremony after it, which is
    right, and here the outcome was a badge nobody had. The leg was crossed
    off, so nothing will ever bring it back, and the Elite Four would have
    been reached one badge short with no record of why.

    Badges are the least ambiguous fact in the game and they are in the
    state text, so this costs nothing and needs no knowledge: an objective
    that names a badge is not done while that badge is not held.
    """
    g = re.sub(r"[^A-Z]+", "", goal.upper())
    have = re.sub(r"[^A-Z]+", "", (start or "").upper())
    for b in BADGES:
        if b in g and b not in have:
            return b
    return None


def _events_bearing(goal: str) -> str:
    """Events THIS RUN HAS FIRED whose names touch the objective's words.

    History, not a dictionary: every name here is something that already
    happened, so it tells the model nothing about what a place contains.
    (The rejected version listed flags that merely EXIST — user, 2026-08-15.)
    Leg 6 asked "Deliver the parcel from Bill to the Oak Lab" with
    EVENT_OAK_GOT_PARCEL set since leg 3, and nothing in front of the model
    said so. Matching is mechanical; whether it satisfies the objective is
    the model's call.
    """
    try:
        cur = json.loads(Path("run/obs.json").read_text())
    except (OSError, ValueError):
        return ""
    words = {w for w in re.sub(r"[^A-Z]+", " ", goal.upper()).split()
             if len(w) > 3}
    hit = [f for f in (cur.get("flags") or [])
           if words & set(re.sub(r"[^A-Z]+", " ", f.upper()).split())]
    if not hit:
        return ""
    return ("\n\nEVENTS ALREADY RECORDED THAT MENTION THIS OBJECTIVE'S OWN "
            "WORDS: " + ", ".join(sorted(hit)[:10]))


DONE_LEDGER = Path("plans/outline.done")
# Set by check_wording when the restatement it was given turns out to name
# something already accomplished. That is not a rejection — it is the model
# telling us, in its own words, what the objective MEANS, and then the
# evidence saying that thing has happened. See check_wording.
WORDING_SAYS_DONE = [False]
# THE THIRD VERDICT (2026-08-18). Asked to restate "Retrieve the Pokemon
# from the Poke Mart" with the counted repetition in front of it, the
# model answered "the run history and event flags show the parcel is
# delivered; there is no Pokemon to retrieve" — and the rung had only two
# outcomes, restate or stands, so the recognition fell through as "the
# wording stands" and the chain halted on a line the model had just called
# empty. VOID is the model's own verdict that the sentence describes
# nothing; the leg is crossed off with the reason recorded, exactly as a
# done-under-another-name is. The harness proposes nothing.
WORDING_SAYS_VOID = [False]


def done_ledger() -> list:
    """Accomplishments the run has recognised, as (deed, what it opens).

    Separate from outline.txt on purpose. The outline is a list of things
    to DO and the chain walks it in order; this is a list of things DONE,
    including work that was never on the list at all, and nothing is ever
    scheduled from it.
    """
    try:
        rows = [l.split("\t") for l in DONE_LEDGER.read_text().splitlines()
                if l.strip()]
    except OSError:
        return []
    return [(r[0].strip(), (r[1].strip() if len(r) > 1 else "")) for r in rows]


def done_ledger_add(rows: list) -> list:
    """Append accomplishments not already recorded; return what was new."""
    have = {_norm_obj(d) for d, _ in done_ledger()}
    new = []
    for deed, opens in rows:
        deed = str(deed).strip()
        if not deed or _norm_obj(deed) in have:
            continue
        have.add(_norm_obj(deed))
        new.append((deed, str(opens or "").strip()))
    if new:
        with DONE_LEDGER.open("a") as fh:
            for deed, opens in new:
                fh.write(f"{deed}\t{opens}\n")
    return new


def done_ledger_text(label: str = "ALSO ACCOMPLISHED, though it was never "
                                  "on your list", cap: int = 12) -> str:
    rows = done_ledger()[-cap:]
    if not rows:
        return ""
    return ("\n\n" + label + ":\n"
            + "\n".join(f"  {d}" + (f" — {o}" if o else "") for d, o in rows))


RECOGNIZE_SYS = """Look over what this run has done and name the
ACCOMPLISHMENTS in it. Not everything worth finishing was written on your
list: things get done early, in passing, or while chasing something else,
and some of them open doors that were shut.

You are shown what the run holds, what the game has recorded it doing, and
your own list of objectives. Name only accomplishments that are NOT
already on that list — restating a listed objective is not what this is
for — and only ones you can point at: the item is in the bag, the badge is
earned, the event has fired.

For each, say what it now makes possible, in one clause. If nothing
qualifies, say so; that is the ordinary answer.

Phrase each the way your list is phrased. Reply with ONLY a JSON object:
{"why": "one sentence",
 "done": [{"did": "Obtain <the thing>", "opens": "what it now allows"}]}
or {"why": "one sentence", "done": []}"""


def recognize_done(start: str, model: str, listed: list) -> list:
    """Name accomplishments the outline never thought to list.

    The sweep above asks which LISTED objectives are finished. This asks
    the wider question: what has this run achieved that it never wrote
    down? The Silph Scope came out of the Rocket Hideout during a leg that
    named the wrong key, and no line anywhere said so — the run held a
    thing that opens the Pokemon Tower and had no way to think of it as an
    accomplishment, only as an item.

    Nothing here is ever scheduled. It is recognition, and it feeds the
    picture every later pass reads: what is done, and what that opens.
    """
    body = ("WHERE THE RUN STANDS: " + start + recent_events()
            + done_ledger_text("ACCOMPLISHMENTS YOU HAVE ALREADY RECOGNISED")
            + "\n\nYOUR LIST OF OBJECTIVES, in order:\n"
            + "\n".join(f"  {n}. {t}" for n, t in listed))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": RECOGNIZE_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return []
    got = ans.get("done")
    if not isinstance(got, list) or not got:
        return []
    rows = [(str(r.get("did") or "").strip(),
             str(r.get("opens") or "").strip())
            for r in got if isinstance(r, dict)]
    return done_ledger_add([(d, o) for d, o in rows
                            if d and not _shadows(d, [t for _, t in listed])])


_STOP = {"the", "a", "an", "and", "for", "from", "of", "to", "in", "at",
         "out", "on", "with", "your", "all", "get", "s"}


def _sig(t: str) -> set:
    return {w for w in _norm_obj(t).split() if w not in _STOP}


def _shadows(deed: str, listed: list) -> bool:
    """Does this claimed accomplishment stand in for one still on the list?

    A ledger entry is fed back to every later pass, so a wrong one is not
    a wrong answer once — it is a premise from then on. The first live run
    of this produced "Defeat Giovanni — the path to the Earth Badge" from
    a run that had beaten the Rocket Hideout Giovanni and never been to
    the Viridian gym, with "Defeat Giovanni for the Earth Badge" sitting
    on the list unfinished. That is the same confusion that had already
    cost the run a leg, about to be written down as settled fact.

    So: a deed whose words are contained in an objective still to do is
    not recognised here. If that objective IS done, the sweep crosses it
    off and records it with its own full wording — one record either way,
    and never one that quietly answers a question still open.
    """
    d = _sig(deed)
    if len(d) < 2:
        return True
    return any(d <= _sig(t) for t in listed)


ALREADY_SYS = """You are checking your own playthrough list for work you
have ALREADY FINISHED. An objective still on the list is not proof it is
still outstanding — you may have done it early, or in passing, or while
chasing something else.

Judge only on what the run holds and what it has recorded doing. An
objective is about its OUTCOME: if the thing is in the bag, the badge is
earned, or the event has fired, it is done however it came about, and the
wording it was written in does not matter. If you cannot point at
something that shows it is done, it is NOT done — say so.

Reply with ONLY {"why": "<one sentence>", "done": true} or
{"why": "<one sentence>", "done": false} — the why comes first."""


def check_already_done(deed: str, start: str, model: str,
                       observed=None) -> bool:
    """Has this objective ALREADY been accomplished, at any point in the run?

    Different question from check_done, which asks whether the leg that
    just ran achieved its aim and is judged on that leg's delta. This one
    is judged on the whole run: an objective can have been satisfied ten
    legs ago and nobody noticed, because the chain's only record of
    progress is a high-water mark.

    Same refusal as check_done: a claim the ledger disproves is not
    judgment. The harness asks; which facts satisfy which objective is the
    model's to say.
    """
    never = _never_stood_in(deed, observed)
    if never:
        print(f"[already-done] refused: '{deed[:60]}' names {never} and the "
              f"run has never once stood on it", file=sys.stderr)
        return False
    badge = _badge_not_earned(deed, start)
    if badge:
        print(f"[already-done] refused: '{deed[:60]}' names {badge} and the "
              f"run is not wearing it", file=sys.stderr)
        return False
    body = (f"THE OBJECTIVE: {deed}\n\nWHERE THE RUN STANDS: {start}"
            + recent_events() + _events_bearing(deed))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": ALREADY_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return False
    if ans.get("done"):
        print(f"[already-done] {str(ans.get('why') or '')[:160]}",
              file=sys.stderr)
        return True
    return False


SWEEP_SYS = """Here is the rest of your own Pokemon Red playthrough list —
objectives you have not marked finished — together with what the run holds
and what it has recorded doing.

Some of them may be finished anyway. Work gets done early, in passing, or
while chasing something else, and nothing crosses it off. Name the ones
you can SHOW are already accomplished: the item is in the bag, the badge
is earned, the event has fired. If you cannot point at something, leave it
alone. Naming nothing is the ordinary answer and a perfectly good one.

Reply with ONLY a JSON object, the reason FIRST:
{"why": "one sentence", "done": [3, 7]}   or   {"why": "...", "done": []}"""


def sweep_already_done(ahead: list, start: str, model: str,
                       observed=None, behind: list = ()) -> list:
    """Which of the objectives still ahead are already accomplished?

    Runs at the END OF EVERY LEG, win or lose. The chain tracks progress
    as a single high-water mark, so an objective satisfied out of order
    stays on the list and is eventually attempted in full: four attempts,
    a rewrite apiece, half an hour of walking, before check_done catches
    it at the exhaustion gate. This asks the question up front instead.

    Two stages on purpose. The broad pass sees the objectives together and
    is cheap when the answer is none (the common case); each objective it
    names is then confirmed on its own, where a yes/no is far more
    reliable than a list from a 31B model and the ledger refusal applies.
    """
    if not ahead:
        return []
    # THE WHOLE ARC, not just the tail. Events are a flat set; objectives
    # are ordered narrative, and reading the finished ones beside the
    # remaining ones is what puts the flat set in sequence — the picture
    # the next author pass inherits, not just this one answer.
    body = ("WHERE THE RUN STANDS: " + start + recent_events()
            + ("\n\nOBJECTIVES YOU HAVE FINISHED, in order:\n"
               + "\n".join(f"  {n}. {t}" for n, t in behind) if behind else "")
            + done_ledger_text()
            + "\n\nSTILL ON YOUR LIST, in order:\n"
            + "\n".join(f"  {n}. {t}" for n, t in ahead))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": SWEEP_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return []
    want = ans.get("done")
    if not isinstance(want, list) or not want:
        return []
    by_n = dict(ahead)
    cand = []
    for v in want:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n in by_n and n not in [c for c, _ in cand]:
            cand.append((n, by_n[n]))
    if not cand:
        return []
    print(f"[sweep] {str(ans.get('why') or '')[:160]}", file=sys.stderr)
    return [(n, t) for n, t in cand
            if check_already_done(t, start, model, observed=observed)]


CHECKMISSING_SYS = """You are stuck on one objective of your own
playthrough, and neither finishing it nor reordering what you already
planned has worked. So the question is whether the plan is INCOMPLETE:
some deed the game wants first that you never wrote down.

You are shown what this run has actually DONE (events the game recorded),
what is still on the docket (the objectives you have not reached yet), and
the objective you are stuck on.

Name ONE missing objective, or none. It must be a thing the game will not
let you past until it is done, phrased the way the rest of your list is
phrased. Do NOT restate something already on the docket, and do not name
something the recorded events show is already done.

Reply with ONLY a JSON object, the reason FIRST:
{"why": "one sentence", "insert": "the objective"}   or
{"why": "one sentence", "insert": null}"""


def _norm_obj(t: str) -> str:
    """An objective's text, flattened for equality only.

    ACCENTS FOLD FIRST. Stripping non-ASCII outright turned "Pokemon" with
    its accent into the two tokens `pok` and `mon`, so ANY two objectives
    containing the word shared two "names" and were judged the same
    objective — "Clear Pokemon Tower" and "Obtain Pokemon Flute" were both
    thrown away as repeats of each other. The word itself is scaffolding
    and already in _GENERIC; it just has to survive as one token to be
    recognised there.
    """
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def check_missing(goal: str, ahead: list, start: str, model: str,
                  behind: list = (), observed=None, tries: int = 3) -> str:
    """Ask whether the PLAN is missing a step, when nothing else worked.

    The chain's last recourse used to be stopping. But a leg can be
    unreachable because a deed nobody listed has to happen first — the
    parcel before the mart will sell, Cut before Surge's gym — and the run
    holds the evidence for that: the events it HAS recorded, and the
    objectives it has not reached. Ours is to ask and to place the answer;
    which deed is missing is the model's to say.

    What it must NOT be is work already finished. The old filter compared
    the proposal against the objectives still AHEAD and never against the
    ones behind, so a run stuck on "the Secret Key" — a leg whose outline
    named the wrong item for a dungeon already cleared — could have been
    handed back "Obtain the Silph Scope" with the Scope in the bag, and
    spent four attempts proving it. Two gates now: matching text on the
    list either side of here is bookkeeping and the harness settles it,
    and whether an unmatched deed is nonetheless done is asked outright.
    A rejected proposal is quoted back, so the re-ask is not a re-roll.
    """
    try:
        cur = json.loads(Path("run/obs.json").read_text())
    except (OSError, ValueError):
        cur = {}
    done = sorted(cur.get("flags") or [])
    listed = {_norm_obj(t) for _, t in ahead} | {_norm_obj(t) for _, t in behind}
    base = (f"THE OBJECTIVE YOU ARE STUCK ON: {goal}\n\n"
            f"WHERE THE RUN STANDS: {start}\n\n"
            f"WHAT THE GAME HAS RECORDED YOU DOING ({len(done)} events): "
            + ", ".join(done[:60])
            + ("\n\nOBJECTIVES YOU HAVE ALREADY FINISHED:\n"
               + "\n".join(f"  {n}. {t}" for n, t in behind) if behind else "")
            + done_ledger_text()
            + "\n\nSTILL ON THE DOCKET, in order:\n"
            + "\n".join(f"  {n}. {t}" for n, t in ahead))
    turned_down: list = []
    for _ in range(max(1, tries)):
        body = base + ("\n\nYOU ALREADY PROPOSED THESE AND THEY WERE TURNED "
                       "DOWN — name something else or name none:\n"
                       + "\n".join(f"  - {d} ({w})" for d, w in turned_down)
                       if turned_down else "")
        try:
            reply = brock_probe.chat(
                [{"role": "system", "content": CHECKMISSING_SYS},
                 {"role": "user", "content": body}], model)
            m = re.search(r"\{.*\}", reply, re.S)
            ans = json.loads(m.group(0)) if m else {}
        except (ValueError, KeyError, OSError, AttributeError):
            return ""
        ins = str(ans.get("insert") or "").strip()
        if not ins or ins.lower() in ("none", "null"):
            return ""
        if _norm_obj(ins) in listed:
            turned_down.append((ins, "already on your own list"))
            continue
        if check_already_done(ins, start, model, observed=observed):
            turned_down.append((ins, "you have already done this"))
            continue
        print(f"[check-missing] {str(ans.get('why') or '')[:160]}",
              file=sys.stderr)
        return ins
    return ""


WORDING_SYS = """You are stuck on one objective of your own playthrough
list, and every other question has already been asked and answered: it is
not already done, no later objective of yours has to come first, and no
missing prerequisite explains it.

So the last question is about the SENTENCE. An objective is a description
of something to do, and a description can be wrong. It can name a thing
that is not where you thought it was, or name the wrong thing entirely,
or ask for something that is not there at all. You wrote this line before
you had been to any of these places.

You are shown where the run stands, what it has done, what it hit while
trying, and the rest of your list.

If the wording is wrong, write the objective again in ONE line: the same
intent, said accurately. Do not make it easier, and do not restate
something you have already finished — you will be asked, and a
restatement that turns out to be already done is thrown away.

If the sentence asks for something that is NOT THERE AT ALL — nothing in
this game does what the line describes, and no accurate restatement of
the same intent exists — say that. The line is crossed off your list with
your reason recorded, and nothing else changes; the objectives after it
stand.

If the wording is fine and you have simply not managed it yet, say so.
That is an ordinary answer and often the right one; the run stops and a
person looks at it.

Reply with ONLY a JSON object, the reason FIRST:
{"why": "one sentence", "reword": "the objective, said accurately"}   or
{"why": "one sentence", "reword": null, "void": true}                 or
{"why": "one sentence", "reword": null}"""


def _reword_chain(goal: str) -> list:
    """Every earlier wording that led to this one, oldest first."""
    try:
        rows = [l.split("\t") for l in
                Path("run/outline_rewordings").read_text().splitlines()
                if l.strip()]
    except OSError:
        return []
    by_new = {_norm_obj(r[2]): r for r in rows if len(r) > 2}
    chain, cur = [], _norm_obj(goal)
    while cur in by_new:
        r = by_new.pop(cur)
        chain.insert(0, (r[1], r[2]))
        cur = _norm_obj(r[1])
    return chain


def _reword_history(goal: str) -> str:
    """Every earlier restatement that led to this wording, and failed.

    The first live run reworded "Obtain the Secret Key from the Rocket
    Hideout" into "Obtain the Secret Key from Giovanni" — carrying the
    wrong premise straight through, and naming a Giovanni already beaten.
    Which belief is right is the model's business. Not handing it its own
    last answer is ours: three rewordings that each start from nothing
    are three chances to write the same sentence.
    """
    chain = _reword_chain(goal)
    if not chain:
        return ""
    return ("\n\nYOU HAVE ALREADY REWRITTEN THIS OBJECTIVE, and what you "
            "wrote failed too:\n"
            + "\n".join(f"  {a} -> {b}" for a, b in chain)
            + "\nSo the last restatement did not find the problem either. "
              "Whatever is wrong here, it is not what you changed.")


def check_wording(goal: str, ahead: list, behind: list, start: str,
                  journal: str, model: str, observed=None) -> str:
    """The last rung: is the objective itself wrong?

    The chain halted at "Obtain the Secret Key from the Rocket Hideout" —
    an item that is not in that dungeon, written before the run had been
    anywhere near it — with the hideout cleared, Giovanni beaten and both
    of its real key items in the bag. Nothing could satisfy the line, and
    the run had no way to say so: the three rungs ask whether the work is
    done, blocked, or missing a step, and none of them asks whether the
    sentence describes anything.

    THE MODEL NOTICES AND THE MODEL REWRITES (user, 2026-08-15). The
    harness does not detect an unwinnable objective and it does not
    propose wording; it asks one question after the others have failed,
    and applies an answer it did not shape.

    The worry that this is an escape hatch from hard legs had the shape of
    it wrong. A person playing does not fix their whole plan at the start
    with no way to change their mind when something is plainly not working
    (user, 2026-08-15) — holding the model to a sentence it wrote before
    it had been anywhere is not rigour, it is a worse player. What honesty
    requires is that the revision be the model's own, made from evidence,
    and that is what this asks for.

    The guard against rewording a hard leg into an easy one is therefore
    not a judgment about difficulty — it is that the restatement must
    survive the same already-done check as everything else. "Visit the
    Rocket Hideout" is caught not because it is weaker but because it is
    done.
    """
    body = (f"THE OBJECTIVE YOU ARE STUCK ON: {goal}\n\n"
            f"WHERE THE RUN STANDS: {start}\n{journal}"
            + _reword_history(goal)
            + recent_events() + done_ledger_text()
            + ("\n\nOBJECTIVES YOU HAVE FINISHED:\n"
               + "\n".join(f"  {n}. {t}" for n, t in behind) if behind else "")
            + "\n\nSTILL ON YOUR LIST, in order:\n"
            + "\n".join(f"  {n}. {t}" for n, t in ahead))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": WORDING_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return ""
    new = str(ans.get("reword") or "").strip()
    why = str(ans.get("why") or "")[:160]
    if (not new or new.lower() in ("none", "null")) and ans.get("void"):
        print(f"[wording] VOID, by the model's own account: {why}",
              file=sys.stderr)
        WORDING_SAYS_VOID[0] = True
        try:
            with open("run/outline_void", "a") as fh:
                fh.write(f"{goal}\t{why}\n")
        except OSError:
            pass
        return ""
    if not new or new.lower() in ("none", "null"):
        print(f"[wording] the wording stands: {why}", file=sys.stderr)
        return ""
    if _norm_obj(new) == _norm_obj(goal):
        print("[wording] refused: that is the same sentence",
              file=sys.stderr)
        return ""
    # NO GOING BACK ROUND. Showing the lineage was not enough on its own:
    # the first live use went "Rocket Hideout" -> "Silph Co. building" ->
    # "Rocket Hideout", spending two of three rewordings on a round trip
    # and landing exactly where it started. A wording this leg has already
    # worn and failed in is not a restatement, whatever reasoning arrives
    # with it — that is bookkeeping, and the harness can hold the ledger
    # without having an opinion about which wording is right.
    worn = set()
    for a, b in _reword_chain(goal):
        worn.add(_norm_obj(a))
        worn.add(_norm_obj(b))
    if _norm_obj(new) in worn:
        print(f"[wording] refused: {new!r} is a wording this leg has "
              f"already failed in", file=sys.stderr)
        return ""
    others = [t for _, t in ahead if _norm_obj(t) != _norm_obj(goal)]
    others += [t for _, t in behind]
    if _norm_obj(new) in {_norm_obj(t) for t in others} or _shadows(new, others):
        print(f"[wording] refused: {new!r} is another line of your own list",
              file=sys.stderr)
        return ""
    if check_already_done(new, start, model, observed=observed):
        # NOT A REFUSAL — A VERDICT ON THE ORIGINAL. Asked to restate
        # "Retrieve the Pokemon from the Poke Mart", the model answered
        # "Retrieve the Pokemon from Professor Oak's lab", and the ledger
        # says that is done. Both halves came from the model: what the
        # objective means, and that the meaning is satisfied. Discarding
        # the second half and stopping the chain threw away the answer and
        # kept the problem — twice, at leg 7 one night and leg 3 the next.
        # A leg that is genuinely blocked still stops; this fires only when
        # the model has named the objective as something accomplished.
        print(f"[wording] {new!r} is already done — so is {goal!r}, under "
              f"another name; the leg is spent, not stuck", file=sys.stderr)
        WORDING_SAYS_DONE[0] = True
        return ""
    print(f"[wording] {goal!r} -> {new!r}: {why}", file=sys.stderr)
    return new


LATER_SYS = """A Pokemon Red playthrough leg has been tried and failed,
and the question now is whether it was simply TOO EARLY.

Not whether it is done. Not whether some other leg has to happen first —
that has already been asked. This asks something else: is this objective
one you still mean to do, but LATER, once the run is somewhere else or
carrying something it does not carry yet?

The commonest reason a plan cannot be executed is that it was written in
the wrong place in the journey. Catching a water Pokemon means nothing
before you own a rod. A key item in a city you cannot enter yet is not a
task, it is a task-in-waiting.

Answer with ONLY {"why": "<one sentence>", "after": N} — the number of the
objective this one should now come AFTER — or {"why": "...", "after":
null} if it belongs where it is and failed for some other reason.

Write the why FIRST. Name the thing the later position gives you that
here and now does not: a place, an item, a move, a person. If you cannot
name it, the answer is null."""


def check_later(goal: str, n: int, ahead: list, start: str, journal: str,
                model: str, pushed: int = 0) -> int:
    """Is this objective right, but not yet? Then move it, don't drop it.

    The inverse of confirm_blocker and the commoner case: an outline's
    ordering mistakes are almost all TOO EARLY, because a model writing a
    playthrough puts a thing down when it thinks of it. Before this rung
    the ladder had four ways to say "something else first" and none to say
    "this, but later", so an objective that was merely premature could
    only be reworded, skipped, or fatal. Live: "the party holds a WATER or
    GRASS type" sat before Vermilion, where wild water Pokemon need a rod
    nobody has — the upkeep rule saved the chain by dropping it for good,
    which is the right call for a chain and the wrong one for the
    objective.

    The harness proposes nothing and evaluates nothing. It refuses a
    non-answer, a push that is not actually later, and a leg that has
    already been deferred twice — and applies anything else verbatim.
    """
    if pushed >= 2:
        print(f"[later] refused: {goal!r} has already been put off twice",
              file=sys.stderr)
        return 0
    body = (f"THE OBJECTIVE THAT FAILED: {n}. {goal}\n\n"
            f"WHERE THE RUN STANDS: {start}\n{journal}"
            + "\n\nYOUR LIST FROM HERE ON:\n"
            + "\n".join(f"  {i}. {t}" for i, t in ahead))
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": LATER_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply, re.S)
        ans = json.loads(m.group(0)) if m else {}
    except (ValueError, KeyError, OSError, AttributeError):
        return 0
    why = str(ans.get("why") or "")[:200]
    after = ans.get("after")
    if after in (None, "", "null"):
        print(f"[later] stays where it is: {why}", file=sys.stderr)
        return 0
    try:
        after = int(after)
    except (TypeError, ValueError):
        return 0
    last = ahead[-1][0] if ahead else n
    if after <= n:
        print(f"[later] refused: {after} is not later than {n} — {why}",
              file=sys.stderr)
        return 0
    if after > last:
        after = last
    print(f"[later] {goal!r} moves to after leg {after}: {why}",
          file=sys.stderr)
    return after


def check_done(goal: str, start: str, model: str,
               observed=None, gained: str = "") -> bool:
    """The model judges whether a failed leg's objective is already met.

    A leg can fail on a subgoal long after its aim is achieved: the fossil
    leg walked out of Mt Moon HOLDING the fossil and then failed three
    rewrites trying to condition on reviving it. No mechanical check can
    know that "Retrieve the MT Moon fossil" is satisfied by HELIX_FOSSIL
    x1 in the bag — which fact means which objective is exactly the
    judgment this project leaves to the model. The harness only asks, and
    only applies the answer.
    """
    # EVENTS THIS RUN HAS ALREADY WATCHED FIRE, when their names touch the
    # objective's own words. The delta above answers "did this leg do it";
    # this answers "was it already done" — and the two are different
    # questions. Leg 6 asked "Deliver the parcel from Bill to the Oak Lab"
    # with EVENT_OAK_GOT_PARCEL set since leg 3, and nothing in front of the
    # model said so. Matching is mechanical and names only what already
    # happened; whether it satisfies the objective is the model's call.
    bearing = _events_bearing(goal)
    never = _never_stood_in(goal, observed)
    if never:
        print(f"[check-done] refused: this objective names {never} and the "
              f"run has never once stood on it")
        return False
    badge = _badge_not_earned(goal, start)
    if badge:
        print(f"[check-done] refused: this objective names {badge} and the "
              f"run is not wearing it")
        return False
    reply = brock_probe.chat(
        [{"role": "system", "content": CHECKDONE_SYS},
         {"role": "user", "content": f"THE OBJECTIVE: {goal}\n\n"
          f"WHERE THE RUN STANDS: {start}"
          # WHAT THE LEG ACHIEVED, not just where it ended. A leg can fail
          # every subgoal and still have done the thing — and a FUSED
          # objective ("deliver the parcel from Bill", two errands welded
          # into one) can only be judged against what actually changed.
          + (f"\n\n{gained}" if gained else "") + bearing}], model)
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
    ap.add_argument("--outline-skeleton", action="store_true",
                    help="author the outline from the fixed badge spine, "
                         "asking what must happen in each gap between "
                         "badges (alternative to --outline)")
    ap.add_argument("--outline", action="store_true",
                    help="write the model's own list of objectives instead "
                         "of a subgoal plan (one line per leg)")
    ap.add_argument("--gained", help="what changed while the leg ran "
                    "(planner/leg_delta.py diff), as evidence for judging "
                    "whether a partly-successful leg is in fact done")
    ap.add_argument("--check-done", action="store_true",
                    help="ask the model whether --goal is already "
                         "accomplished at --start; exit 0 yes, 3 no")
    # the third rung of the ladder. It was written, wired into the shell,
    # and never declared here — so it only ever ran when a leg exhausted
    # all four attempts, and when Erika finally did, argparse killed the
    # whole chain instead of asking what was missing.
    ap.add_argument("--check-missing", action="store_true",
                    help="ask what deed the outline never listed")
    ap.add_argument("--check-already-done", action="store_true",
                    help="ask which objectives STILL AHEAD of --leg are "
                         "already accomplished; prints 'N<TAB>text' per "
                         "line and exits 0, or exits 3. With --deed, judges "
                         "that one objective instead")
    ap.add_argument("--deed", default=None,
                    help="a single objective for --check-already-done, "
                         "instead of sweeping the outline")
    ap.add_argument("--check-later", action="store_true",
                    help="ask whether the failed leg is right but too "
                         "early; prints the position it should follow")
    ap.add_argument("--pushed", type=int, default=0,
                    help="how many times this objective has been put off "
                         "already (--check-later refuses a third)")
    ap.add_argument("--check-wording", action="store_true",
                    help="last rung: ask whether the stuck --goal describes "
                         "anything doable, and let the model restate it; "
                         "prints the new objective and exits 0, or exits 3")
    ap.add_argument("--recognize-done", action="store_true",
                    help="name accomplishments this run made that were "
                         "never on the outline at all, and what they open; "
                         "records them in plans/outline.done")
    ap.add_argument("--check-blocker", action="store_true",
                    help="ask the model whether a later outline leg must "
                         "come before the stuck --goal; prints the leg "
                         "number and exits 0, or exits 3")
    ap.add_argument("--outline-path", type=Path, default=None)
    ap.add_argument("--leg", type=int, default=None,
                    help="1-based outline position of the stuck leg")
    ap.add_argument("--draws", type=int, default=3,
                    help="drafts to take before the model chooses among "
                         "them — outline objectives when --outline, "
                         "otherwise plans for the goal (default 3)")
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
                          args.model, observed=args.observed,
                          gained=args.gained or "")
        print("DONE" if done else "NOT_DONE")
        sys.exit(0 if done else 3)
    if args.check_wording:
        if not (args.outline_path and args.leg):
            ap.error("--check-wording needs --outline-path and --leg")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        ahead = [(n, lines[n - 1])
                 for n in range(args.leg, len(lines) + 1)]
        behind = [(n, lines[n - 1]) for n in range(1, args.leg)]
        jt = journal_text(args.journal) if args.journal else ""
        new = check_wording(args.goal, ahead, behind, args.start or "", jt,
                            args.model, observed=args.observed)
        if new:
            print(new)
            sys.exit(0)
        # 4 = "this objective is already accomplished under another name";
        # 5 = "this objective describes nothing that is there" (VOID);
        # the chain crosses the leg off instead of halting on it, either way
        sys.exit(4 if WORDING_SAYS_DONE[0] else 5 if WORDING_SAYS_VOID[0]
                 else 3)
    if args.check_later:
        if not (args.outline_path and args.leg):
            ap.error("--check-later needs --outline-path and --leg")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        ahead = [(n, lines[n - 1])
                 for n in range(args.leg, len(lines) + 1)]
        jt = journal_text(args.journal) if args.journal else ""
        at = check_later(args.goal, args.leg, ahead, args.start or "", jt,
                         args.model, pushed=args.pushed)
        if at:
            print(at)
            sys.exit(0)
        sys.exit(3)
    if args.recognize_done:
        if not args.outline_path:
            ap.error("--recognize-done needs --outline-path")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        got = recognize_done(args.start or "a brand new game", args.model,
                             list(enumerate(lines, 1)))
        for deed, opens in got:
            print(f"{deed}" + (f" — {opens}" if opens else ""))
        sys.exit(0 if got else 3)
    if args.check_already_done:
        st = args.start or "a brand new game"
        if args.deed:
            hit = check_already_done(args.deed, st, args.model,
                                     observed=args.observed)
            sys.exit(0 if hit else 3)
        if not (args.outline_path and args.leg):
            ap.error("--check-already-done needs --deed, or --outline-path "
                     "and --leg")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        ahead = [(n, lines[n - 1])
                 for n in range(args.leg + 1, len(lines) + 1)]
        behind = [(n, lines[n - 1]) for n in range(1, args.leg + 1)]
        got = sweep_already_done(ahead, st, args.model,
                                 observed=args.observed, behind=behind)
        for n, t in got:
            print(f"{n}\t{t}")
        sys.exit(0 if got else 3)
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
        # legs already pulled forward once that did not unstick anything
        try:
            refused = {_norm_obj(l.split("\t", 1)[-1]) for l in
                       Path("run/outline_pulls_failed").read_text().splitlines()
                       if l.strip()}
        except OSError:
            refused = set()
        n = check_blocker(args.goal, ahead, args.start or "", jt,
                          args.model, leg=args.leg, observed=args.observed,
                          refused=refused)
        if n:
            print(n)
            sys.exit(0)
        sys.exit(3)
    if args.check_missing:
        if not (args.outline_path and args.leg):
            ap.error("--check-missing needs --outline-path and --leg")
        lines = [l.strip() for l in args.outline_path.read_text()
                 .splitlines() if l.strip()]
        # what is still AHEAD, this leg included: the missing deed is a
        # prerequisite of the leg that just failed, not of the ones after it
        ahead = [(n, lines[n - 1])
                 for n in range(args.leg, len(lines) + 1)]
        if not ahead:
            sys.exit(3)
        behind = [(n, lines[n - 1]) for n in range(1, args.leg)]
        deed = check_missing(args.goal, ahead, args.start or "", args.model,
                             behind=behind, observed=args.observed)
        if deed:
            print(deed)
            sys.exit(0)
        sys.exit(3)
    if args.out is None:
        ap.error("--out is required except with --check-done")
    if args.outline or args.outline_skeleton:
        legs = (outline_skeleton(args.goal, args.model)
                if args.outline_skeleton
                else outline(args.goal, args.model,
                             draws=args.draws))
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
    plan = author_best_of(args.goal, args.model, draws=args.draws,
                          start=args.start)
    if not plan:
        sys.exit("author failed to produce a valid plan")
    if not args.no_review:
        prior = load_drafts(args.goal)
        if prior:
            print(f"[drafts] {len(prior)} earlier draft(s) for this goal "
                  f"shown to the review")
        plan = review(args.goal, plan, args.model, start=args.start,
                      observed=args.observed, journal=args.journal,
                      drafts=prior)
    plan.setdefault("goal", args.goal)
    plan["authored_by"] = args.model
    archive_draft(args.goal, plan)
    args.out.write_text(json.dumps(plan, indent=2))
    print(f"wrote {args.out}")
    for s in plan["subgoals"]:
        print(f"  {s['id']}: done_when={json.dumps(s['done_when'])}")


if __name__ == "__main__":
    main()
