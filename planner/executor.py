#!/usr/bin/env python3
"""SPD Tier-0 executor: run a plan of subgoals against the shim bridge.

A plan (JSON) is an ordered list of subgoals. Each subgoal has:
  id          name for logs
  macro       list of op steps; a step is {"op":..., ...params} plus optional
              "when": predicate — the step is skipped unless it holds (makes
              macros safely re-runnable after partial progress)
  battle_policy  name of the battle policy to run if a battle starts
              during this subgoal (default: "default")
  done_when   predicate that ends the subgoal (checked before/after each op)
  max_attempts   macro re-runs before giving up (default 3)

Predicate DSL (all listed keys must hold):
  {"map": "PALLET_TOWN"}       current map id
  {"mode": "overworld"}        obs mode
  {"screen": "BoxMenu"}        WHICH ui screen is open (obs.ui.screenId)
  {"party_nonempty": true}     at least one party mon
  {"badge": "BOULDERBADGE"}    badge earned
  {"flag": "EVENT_..."}        save event flag set (executor instrumentation)
  {"no_battle": true}          not in battle
  {"party_alive": true}        at least one mon with hp > 0

Battle policies here are HAND-SEEDED placeholders for spine validation only —
the record run requires model-authored policies (CLAIM_RULES v1); nothing in
this file ships into a record attempt's decision path.

Every action and predicate evaluation is logged to run/executor_log.jsonl —
provenance is load-bearing for the claim, so it is wired in from the start.

Usage: executor.py plans/opening.json [--bootstrap] [--max-battle-turns N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from bridge import Bridge, RUN
import battle_policy
import ledger

# Which gym holds which badge — the pamphlet's leader page.
# THE LEDGER SWITCH. RED_LEDGER=0 renders the exploration prompt the old
# way (the ~20 prose sections) so the two can be A/B'd with repeats.py and
# decisions.py; the default is the ledger (EXPLORE_DESIGN.md §3, §6b).
USE_LEDGER = os.environ.get("RED_LEDGER", "1") != "0"
# THE STALE BUDGET (EXPLORE_DESIGN §6d): rounds in a row that changed
# nothing the run carries, knows or is, on ground already walked this
# subgoal, before the subgoal is ended so the plan can be rewritten. A rule
# about spending, not about the game; RED_STALE=0 disables it.
STALE_CUTOFF = int(os.environ.get("RED_STALE", "6") or 0)

BADGE_GYMS = {
    "BOULDERBADGE": "PEWTER_GYM", "CASCADEBADGE": "CERULEAN_GYM",
    "THUNDERBADGE": "VERMILION_GYM", "RAINBOWBADGE": "CELADON_GYM",
    "SOULBADGE": "FUCHSIA_GYM", "MARSHBADGE": "SAFFRON_GYM",
    "VOLCANOBADGE": "CINNABAR_GYM", "EARTHBADGE": "VIRIDIAN_GYM",
}

# The game's own outdoor-map adjacency (data/generated/maps.lua
# connections), extracted once — the town map every player unfolds.
try:
    MAP_EDGES = json.loads(
        (Path(__file__).with_name("map_edges.json")).read_text())
except (OSError, ValueError):
    MAP_EDGES = {}

_HOPS: dict = {}


def static_hops(a: str, b: str, avoid=frozenset()):
    """How many printed-map legs from map A to map B, or None.

    DIRECT ADJACENCY IS NOT ENOUGH. Goal-ward preference only fired when
    an untried edge landed ON the target map, so the first hop of a
    three-hop journey ranked no better than any door — Cerulean's east
    edge, the whole eastern half of Kanto, never outranked the numeric
    door keys that sort ahead of it even with the road restored and an
    eastern destination named. Distance over the town map orders them.
    Interiors are not on the printed map, so a target inside a building
    is asked about by its city (see _doorstep).
    """
    if not a or not b:
        return None
    if a == b:
        return 0
    key = (a, b, avoid)
    if key in _HOPS:
        return _HOPS[key]
    seen, frontier, d = {a}, [a], 0
    while frontier:
        d += 1
        nxt = []
        for m in frontier:
            for m2 in (MAP_EDGES.get(m) or {}).values():
                if m2 in seen or (m, m2) in avoid:
                    continue
                if m2 == b:
                    _HOPS[key] = d
                    return d
                seen.add(m2)
                nxt.append(m2)
        frontier = nxt
    _HOPS[key] = None
    return None


def static_cost(a: str, b: str, toll: dict, extra: dict | None = None):
    """Cheapest printed-map route from A to B when some edges carry a TOLL.

    Plain hop-counting cannot choose between two shut doors, and Lavender
    has exactly two: Route 12 (one hop from where the run stands, leaned on
    328 times) and Route 10 (seven hops, tried 22). Every path from the
    south crosses the Snorlax, so distance always picked it, and the run
    went back to the same sleeping Pokemon for hundreds of arrivals.

    Pricing a shut edge by how hard it has ALREADY been leaned on makes
    the long road cheaper than the near wall, without anyone deciding
    which wall is real. Dijkstra rather than BFS because the edges now
    have weights; an untolled graph gives exactly the old hop count.
    """
    if not a or not b:
        return None
    if a == b:
        return 0
    import heapq
    best = {a: 0}
    q = [(0, a)]
    while q:
        cost, m = heapq.heappop(q)
        if m == b:
            return cost
        if cost > best.get(m, 1 << 30):
            continue
        # Printed roads AND roads this run has actually walked. The town
        # map has no line for an underground path, so Vermilion could only
        # reach Cerulean THROUGH Saffron — a tolled wall — while the run
        # had gone Route 5 to Route 6 underground 110 times. A connection
        # you have personally walked is the strongest evidence there is,
        # and leaving it out priced the open road above the shut one.
        for m2 in set((MAP_EDGES.get(m) or {}).values()) \
                | set((extra or {}).get(m) or ()):
            c = cost + 1 + toll.get((m, m2), 0)
            if c < best.get(m2, 1 << 30):
                best[m2] = c
                heapq.heappush(q, (c, m2))
    return None


# Which ROAD each interior opens off, inverted from the generated doors
# table (planner/map_doors.json, the printed map's own labelling). Without
# it an interior is not on the outdoor graph at all, so every distance from
# inside one fell through to the same worst score — and a run standing in
# Mt Moon rated the road outside better than the cave it was crossing, left,
# was pulled back by its plan, and left again.
import re as _re
try:
    _DOORS = json.loads(
        Path(__file__).with_name("map_doors.json").read_text())
    INTERIOR_ROAD = {mid: road for road, places in _DOORS.items()
                     for ids in places.values() for mid in ids}
    # ROADS A PLACE CUTS IN HALF. A named place listed under exactly ONE
    # road is entered and left on that road — Mt Moon on Route 4, Rock
    # Tunnel on Route 10 — so the road has two halves that cannot be walked
    # between. One listed under SEVERAL roads joins those roads instead
    # (the underground paths). The difference decides whether "stood here
    # often, never got across" means a wall or the wrong side.
    _roads_of = {}
    for _road, _places in _DOORS.items():
        for _label in _places:
            _roads_of.setdefault(_label, set()).add(_road)
    SPLIT_ROADS = {next(iter(rs)) for lbl, rs in _roads_of.items()
                   if len(rs) == 1}
    # Deeper floors too. The table names only what a road warps into
    # DIRECTLY, so Mt Moon's B2F was still nowhere — and rating the bottom
    # of a cave worse than its middle pushes a run upward out of it. A
    # floor belongs to the same place as its siblings.
    _FLOOR = _re.compile(r"_(B?\d+F|ROOF|ELEVATOR)$")
    for _mid, _road in list(INTERIOR_ROAD.items()):
        INTERIOR_ROAD.setdefault(_FLOOR.sub("", _mid), _road)
except (OSError, ValueError):
    INTERIOR_ROAD = {}


# A SERVICE IS NEVER EXHAUSTED. "Fully worked" means nothing is left to
# FIND here, which is trivially true of these and useless, because their
# value is a counter, a nurse or a panel that keeps working however many
# times you come back. Marked, they read as "done with this place" to
# every consumer of the ledger.
#
# ONE LIST, TWO READERS. The refusal in note_searched and the expiry at
# load time were written separately with the same tuple inline, and they
# drifted: the BIKE_SHOP sat in "Already fully worked" all day holding an
# untraded BIKE_VOUCHER (user, twice), and CELADON_MART_ELEVATOR — the
# only way to the department store's five floors — read as an exhausted
# closet the run entered four times and left four times. Neither ends in
# MART or POKECENTER. Splitting a rule across two call sites and updating
# one is this project's most repeated bug; the constant is the fix.
SERVICE_SUFFIXES = ("POKECENTER", "MART", "SHOP", "ELEVATOR")


def _is_service(region: str) -> bool:
    return str(region).split("|")[0].endswith(SERVICE_SUFFIXES)


def _doorstep(map_id: str) -> str:
    """The printed-map place a target sits in: itself if the town map
    draws it, else the road it opens off, else the city its name carries
    (CELADON_GYM -> CELADON_CITY, the same fallback badge routing uses)."""
    if not map_id or map_id in MAP_EDGES:
        return map_id
    if map_id in INTERIOR_ROAD:
        return INTERIOR_ROAD[map_id]
    fam = _re.sub(r"_(B?\d+F|ROOF|ELEVATOR)$", "", map_id)
    if fam in INTERIOR_ROAD:
        return INTERIOR_ROAD[fam]
    for suffix in ("_GYM", "_MART", "_POKECENTER", "_GATE"):
        if map_id.endswith(suffix):
            city = map_id[: -len(suffix)] + "_CITY"
            if city in MAP_EDGES:
                return city
    for city in MAP_EDGES:
        if city.endswith("_CITY") and map_id.startswith(
                city[: -len("_CITY")] + "_"):
            return city
    return map_id
import battle_oracle
import brock_probe   # reuse the live model driver (chat/parse) for escalation


# The model must never see executor instrumentation (event flags, the oracle
# probe) — CLAIM_RULES: those are for the executor's control flow, not eyes.
# WHAT AN ITEM OBJECT USED TO BE CALLED. Until 2026-08-18 the shim emitted
# the map's own object names for items — ROUTE2_HP_UP, OAKSLAB_CHARMANDER_
# POKE_BALL — which name the CONTENTS of a ball seen only from the outside.
# The shim now emits ITEM_x_y; these recognise the old names still sitting
# in persisted ledgers so they can be dropped on load (re-sighted under the
# handle on the next visit) rather than re-served for the rest of the run.
try:
    _ITEM_IDS = {l.strip() for l in
                 (Path(__file__).resolve().parent / "engine_items.txt")
                 .read_text().splitlines() if l.strip()}
except OSError:
    _ITEM_IDS = set()


def _looks_like_item_name(name: str) -> bool:
    n = str(name or "")
    if n.startswith("ITEM_"):
        return False                       # already the handle
    if n.endswith("_POKE_BALL"):
        return True
    parts = n.split("_")
    return any("_".join(parts[i:]) in _ITEM_IDS for i in range(1, len(parts)))


def model_view(obs: dict, holding_map: bool = False,
               walked_dest=None) -> dict:
    """The observation as the MODEL may see it.

    WHAT A DOOR LEADS TO IS NOT ON THE SCREEN. `map.warps[].dest` is the
    warp table — the far side of every door on the map the moment you set
    foot on it — and it rode into CURRENT_OBSERVATION every round while
    the renderers were being made to say UNKNOWN. Stripped here; a door's
    walked destination (from `walked_dest`) is the only one that stays.
    Seam names (`map.connections`) are the printed map's, and are shown
    only while the run holds the TOWN MAP; otherwise the direction alone.
    """
    o = dict(obs or {})
    o.pop("flags", None)
    if isinstance(o.get("map"), dict):
        _mm = dict(o["map"])
        _mid = _mm.get("id")
        _ws = []
        for w in (_mm.get("warps") or []):
            w2 = {k: v for k, v in dict(w).items() if k != "dest"}
            _known = walked_dest(_mid, f"{w.get('x')},{w.get('y')}") \
                if walked_dest else None
            if _known:
                w2["walked_to"] = _known
            _ws.append(w2)
        _mm["warps"] = _ws
        if not holding_map:
            _mm["connections"] = {d: "?" for d in
                                  (_mm.get("connections") or {})}
        o["map"] = _mm
    # HARNESS BOOKKEEPING IS NOT A THING THE PLAYER CAN SEE. `flags` and the
    # oracle probe were stripped and two others were not: `region_anchors`
    # is our own region-naming scratchpad, and `events` is the raw engine
    # emit-name list — the same instrumentation tier as the flags right
    # above, arriving under a different key.
    o.pop("events", None)
    # region_anchors sits under `map`, not at the top level — popping it
    # here did nothing until this was checked against a real observation.
    # dict() the map first: `o` is a SHALLOW copy, so editing map in place
    # would strip it from the executor's own observation too.
    if isinstance(o.get("map"), dict):
        _m = dict(o["map"])
        _m.pop("region_anchors", None)
        o["map"] = _m
    if isinstance(o.get("battle"), dict):
        b = dict(o["battle"])
        b.pop("probe", None)
        o["battle"] = b
    return o


# ---------------------------------------------------------------- predicates
# Enclosed-area codes are the smallest reachable cell, computed WITH static
# blockers — so removing a blocker re-fingerprints the room. Mt Moon's fossil
# room is MT_MOON_B2F|20,5 before a fossil is taken and MT_MOON_B2F|3,2 after,
# same room, same single exit. A goal naming the pre-gate code would become
# unsatisfiable the moment the gate opened. Areas sharing an exit signature
# are treated as the same place. Populated by the Executor from what it walked.
AREA_ALIASES: dict = {}


def _is_door_key(k) -> bool:
    """A door is keyed "x,y"; a seam by its direction (possibly with an
    "#alt" suffix when one seam lands in two places). Half the executor used
    to ask "is there a comma in it", which a suffixed key answers wrongly."""
    return bool(_re.fullmatch(r"\d+,\d+", str(k)))


def pred_keys(pred: dict | None) -> set:
    """Every predicate key in play, INCLUDING inside any_of branches.

    The gate checks ask literally "is 'flag' in this predicate". An
    either/or gate keeps its own kind one level down, so it would read as a
    trivial map hop: shallow round budget, and walked past on failure —
    exactly the treatment a load-bearing event must never get.
    """
    out = set()
    for k, v in (pred or {}).items():
        if k == "any_of":
            for alt in (v or []):
                out |= pred_keys(alt)
        else:
            out.add(k)
    return out


# WHAT THE SHIM ACTUALLY SAYS when an interact leaves a yes/no box open.
# Two guards were written against the phrase "asked a QUESTION", which the
# shim has never emitted — `grep 'asked a QUESTION' harness/shim.lua` is
# zero — so both were dead from the day they were added. The cost was
# exactly what their own comments predicted: pressing the Mt Moon DOME
# FOSSIL asked "You want the DOME FOSSIL?", the press was recorded as a
# TRY, the room swept itself as fully worked, and neither fossil was ever
# offered again. Match on the string that exists, from one place.
ASKING = "is ASKING something and the box is STILL OPEN"


# A PREDICATE THE HARNESS CANNOT READ IS UNMET, NEVER FATAL. pred_holds is
# called unguarded from run_subgoal, the ladder and the escalation loop, so
# anything it raises takes the whole executor down in the middle of a leg —
# and the value it is reading was written by a model. The rule was already
# stated for has_item and only implemented there. Malformations are recorded
# rather than swallowed: a condition that can never come true is a stalled
# leg, and a stalled leg with no explanation is the worst thing in this
# codebase to debug.
PRED_MALFORMED: dict = {}


def _pred_malformed(key, want, why):
    PRED_MALFORMED[f"{key}={want!r}"] = why


def _as_bool(want):
    """The predicate meant true or false; the model may have typed it."""
    if isinstance(want, bool):
        return want
    if isinstance(want, str):
        s = want.strip().lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
    if isinstance(want, (int, float)):
        return bool(want)
    return None


def _as_int(key, want):
    if isinstance(want, bool):
        return None
    if isinstance(want, (int, float)):
        return int(want)
    try:
        return int(str(want).strip())
    except (TypeError, ValueError):
        _pred_malformed(key, want, "expected a whole number")
        return None


def pred_holds(pred: dict | None, obs: dict) -> bool:
    if not pred:
        return True
    if not obs:
        return False
    for key, want in pred.items():
        if key == "any_of":
            # THE GAME OFFERS CHOICES; THE PREDICATE LANGUAGE DID NOT.
            # Mt Moon hands over ONE fossil, and the plan said so in plain
            # English twice ("pick up either the Helix Fossil or Dome
            # Fossil") — but with no OR to write it in, the alternative had
            # to become two sequential subgoals, and the second one can
            # never be satisfied by a game that already gave you the first.
            # This is expressiveness, not judgment: which branch to take is
            # still entirely the plan's to name.
            if not isinstance(want, (list, tuple)):
                _pred_malformed(key, want, "any_of needs a LIST of "
                                           "alternative predicates")
                return False
            if not any(pred_holds(alt, obs) for alt in want
                       if isinstance(alt, dict)):
                return False
        elif key == "map":
            if (obs.get("map") or {}).get("id") != want:
                return False
        elif key == "mode":
            if obs.get("mode") != want:
                return False
        elif key == "screen":
            # WHICH menu, when `mode` can only say THAT one is open. Every
            # UI screen reports "ui" — a PC, a shop counter, a naming box —
            # so "access the PC" was inexpressible and the model reached
            # for a mode that does not exist ({"mode":"pc"}), which cost a
            # whole chain. The engine names its own screens and the shim
            # has always passed the name through as ui.screenId; nothing
            # could test it. This is that test, and nothing more: it reads
            # the label already on the observation.
            if ((obs.get("ui") or {}).get("screenId")) != want:
                return False
        elif key == "party_nonempty":
            want = _as_bool(want)
            if want is None:
                _pred_malformed(key, want, "expected true or false")
                return False
            if bool(obs.get("party")) != want:
                return False
        elif key == "party_alive":
            alive = any((m.get("hp") or 0) > 0 for m in obs.get("party") or [])
            want = _as_bool(want)
            if want is None or alive != want:
                return False
        elif key == "party_healthy":
            mons = obs.get("party") or []
            healthy = bool(mons) and all(
                (m.get("hp") or 0) > 0
                and (not m.get("max_hp") or m["hp"] == m["max_hp"])
                and m.get("status") in (None, "", "0", "NONE", "OK")
                for m in mons)
            want = _as_bool(want)
            if want is None or healthy != want:
                return False
        elif key == "lead_level":
            lead = (obs.get("party") or [{}])[0]
            need = _as_int(key, want)
            if need is None or (lead.get("level") or 0) < need:
                return False
        # THE THREE THAT MAKE UPKEEP WRITEABLE. A plan could always say
        # "party_size 3" but never WHICH three, so "catch a water type to
        # cover the next gym" and "catch a Rattata to soak hits" were the
        # same subgoal to the harness and both were satisfied by whatever
        # wandered into the grass first. Every one of these reads something
        # the game prints on a screen: the status page shows a Pokemon's
        # types under its name, the Pokedex shows OWN and SEEN.
        elif key == "has_species":
            have = {str(m.get("species") or "").upper()
                    for m in (obs.get("party") or [])}
            need = ([want] if isinstance(want, str)
                    else list(want or []) if isinstance(want, (list, tuple))
                    else list((want or {}).keys()))
            if not all(str(s).upper() in have for s in need):
                return False
        elif key == "party_type":
            have = {str(t).upper()
                    for m in (obs.get("party") or [])
                    for t in (m.get("types") or [])}
            need = [want] if isinstance(want, str) else list(want or [])
            if not all(str(t).upper() in have for t in need):
                return False
        elif key == "dex_owned":
            # the Route 2 aide wants ten before he parts with FLASH
            # need = 0 on a bad value made this INSTANTLY TRUE, which is
            # the worst way for a condition to fail: the leg closes having
            # caught nothing.
            need = _as_int(key, want)
            if need is None:
                return False
            if ((obs.get("pokedex") or {}).get("owned") or 0) < need:
                return False
        elif key == "area":
            # An ENCLOSED AREA, not just a floor: "MAP|region", the same id
            # the graph, sightings and searched-rooms use. Mt Moon B2F has
            # four unconnected rooms and only one holds the nerd, so
            # {"map":"MT_MOON_B2F"} was satisfied by landing in any of them.
            m = (obs.get("map") or {})
            got = f"{m.get('id')}|{m.get('region')}"
            if got != want and got not in AREA_ALIASES.get(want, ()):
                return False
        elif key == "party_min_level":
            # EVERY party member at least this level. lead_level could only
            # see slot 1, so "train the backup" was inexpressible: the model
            # wrote train_nidoran {lead_level:15} while a L22 Charmeleon led,
            # which was already true and trained nothing. The weakest member
            # decides this one, so it cannot be satisfied by the lead alone.
            mons = obs.get("party") or []
            need = _as_int(key, want)
            if need is None or not mons or any(
                    (m.get("level") or 0) < need for m in mons):
                return False
        elif key == "slot_level":
            # a specific party slot (1-based), for "get the SECOND one to N"
            mons = obs.get("party") or []
            if not isinstance(want, dict):
                _pred_malformed("slot_level", want,
                                "needs {'slot':N,'min':N}")
                return False
            try:
                slot = int(want.get("slot", 1))
            except (TypeError, ValueError):
                slot = 1
            # `min` MISSING IS NOT `min` ZERO. int(get("min", 0)) made
            # {"slot":2,"level":15} — the obvious thing to write, and wrong
            # — mean "slot 2 is at least level 0", which is true the moment
            # a second Pokemon exists. The subgoal closed instantly having
            # trained nothing, which is the worst kind of pass.
            # `level` accepted as a synonym at RUNTIME only: the validator
            # rejects it during authoring so the model learns the key, but
            # a plan that reaches here by another route should still train
            # the mon rather than stall on a synonym.
            raw = want.get("min", want.get("level"))
            if raw is None:
                _pred_malformed("slot_level", want,
                                "no 'min' — the level to reach is unnamed")
                return False
            try:
                need = int(raw)
            except (TypeError, ValueError):
                _pred_malformed("slot_level", want, "min must be a number")
                return False
            if slot < 1 or slot > len(mons):
                return False
            if (mons[slot - 1].get("level") or 0) < need:
                return False
        elif key == "has_item":
            bag = obs.get("bag") or {}
            # {"ITEM": n} is the shape, but "ITEM" and ["A","B"] are the
            # obvious things to write and a plan is not hand-checked before
            # it runs. Read them as "one of each" rather than raising:
            # pred_holds is called from run_subgoal, so a TypeError here
            # kills the whole executor mid-plan, and an unattended run must
            # never die of a predicate it could have understood.
            if isinstance(want, str):
                want = {want: 1}
            elif isinstance(want, (list, tuple, set)):
                want = {str(i): 1 for i in want}
            elif not isinstance(want, dict):
                want = {}
            for item, n in want.items():
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    n = 1
                if not bag or bag.get(item, 0) < n:
                    return False
        elif key == "player_at":
            # {"x":N,"y":N,"radius":R} — where you are standing is
            # player-visible, and a map id alone cannot distinguish
            # disconnected regions that share one id
            pl = obs.get("player") or {}
            if pl.get("x") is None or pl.get("y") is None:
                return False
            # `want["x"]` was indexed straight into a value the model
            # wrote. {"player_at":[5,7]} or a missing "y" raised out of
            # pred_holds, which run_subgoal calls unguarded, and the whole
            # executor died mid-leg. Same law as has_item below: an
            # unattended run must never die of a predicate it could have
            # understood — and one it CANNOT understand is unmet, not fatal.
            if not isinstance(want, dict):
                _pred_malformed("player_at", want, "needs {'x':N,'y':N}")
                return False
            wx, wy = want.get("x"), want.get("y")
            if not isinstance(wx, (int, float)) or \
                    not isinstance(wy, (int, float)):
                _pred_malformed("player_at", want, "x and y must be numbers")
                return False
            r = want.get("radius", 4)
            if not isinstance(r, (int, float)):
                r = 4
            if abs(pl["x"] - wx) > r or abs(pl["y"] - wy) > r:
                return False
        elif key == "knows_move":
            # WHAT A POKEMON CAN DO WAS INEXPRESSIBLE. party_size could say
            # "catch something" and lead_level could say "train", but no
            # predicate could say "teach it a move that works" — so a plan
            # could not aim at the one action that would have ended twelve
            # losses to Misty with TM_MEGA_PUNCH sitting in the bag. Takes
            # a move id, or {"move": ..., "slot": N} for a particular
            # member; any member counts when no slot is named.
            want_mv = (want or {}) if isinstance(want, dict) else {"move": want}
            mid = str(want_mv.get("move") or "").upper()
            mons = obs.get("party") or []
            slot = want_mv.get("slot")
            if slot is not None:
                slot = int(slot)
                if slot < 1 or slot > len(mons):
                    return False
                mons = [mons[slot - 1]]
            if not any(
                    mid in [str(m.get("id") if isinstance(m, dict) else m).upper()
                            for m in (mon.get("moves") or [])]
                    for mon in mons):
                return False
        elif key == "party_size":
            need = _as_int(key, want)
            if need is None or len(obs.get("party") or []) < need:
                return False
        elif key == "badge":
            if want not in (obs.get("badges") or []):
                return False
        elif key == "flag":
            if want not in (obs.get("flags") or []):
                return False
        elif key == "no_battle":
            want = _as_bool(want)
            if want is None or (obs.get("mode") == "battle") == want:
                return False
        else:
            # WAS: raise. run_subgoal calls pred_holds unguarded, so one
            # mistyped key ended the run — and the run is meant to play
            # unattended for hours. A key nothing can evaluate is a
            # condition that is not met; it is recorded so the stall has a
            # name, and the validator rejects it at authoring time where
            # the model can still hear about it.
            _pred_malformed(key, want, "no such predicate")
            return False
    return True


# ------------------------------------------------------------ battle policies
# set by main() when --score-battles is passed: score every battle turn
# against the oracle without changing what the policy plays.
SCORE_BATTLES = False
# distill-then-verify: replay a successful macro from the subgoal's start
# checkpoint before committing it. Off by default — see escalate().
VERIFY_MACROS = False


# the spec every named policy resolves through; --policy-spec swaps in a
# model-authored artifact so the whole run's battle decisions come from it
ACTIVE_SPEC = battle_policy.DEFAULT_SPEC


def set_active_spec(spec):
    global ACTIVE_SPEC
    ACTIVE_SPEC = spec


# run-long damage journal: what the player has SEEN each move do to each
# species at each of our levels (HP bars are on screen). Feeds the policy's
# empirical KO detection — no computed damage internals in the decision
# path (pamphlet standard).
DAMAGE_JOURNAL: dict = {}


def _journal_damage(before_b: dict, after_obs: dict, move_id: str):
    me = before_b.get("me") or {}
    foe = before_b.get("foe") or {}
    key = battle_policy.journal_key(move_id, foe.get("species"),
                                    me.get("level"))
    hp0 = foe.get("hp") or 0
    ab = (after_obs or {}).get("battle") or {}
    if (after_obs or {}).get("mode") == "battle" \
            and (ab.get("foe") or {}).get("species") == foe.get("species"):
        d = hp0 - ((ab.get("foe") or {}).get("hp") or 0)
        if d > 0:
            DAMAGE_JOURNAL.setdefault(key, []).append(d)
    elif (after_obs or {}).get("mode") != "battle" and hp0 > 0:
        # battle ended on our move: the foe fainted — damage at least hp0
        # (a lower bound; min() keeps the ledger conservative)
        alive = any((m.get("hp") or 0) > 0
                    for m in (after_obs or {}).get("party") or [])
        if alive:
            DAMAGE_JOURNAL.setdefault(key, []).append(hp0)


def _run_policy(spec, bridge, obs, log, max_turns, intent="fight",
                want=None):
    """Drive a battle turn-by-turn with a battle_policy spec (rules as data).
    The spec also owns the wild-flee decision (should_flee); trainers can
    never be fled, and if fleeing fails 3 times we fight it out. With
    SCORE_BATTLES, probe the oracle each turn and log policy-vs-oracle
    agreement — the measuring stick, which does not alter play."""
    turns = 0
    flees = 0
    picks = 0
    op_fails = 0
    ctx = {"turn": 0, "used": {}, "intent": intent,
           "journal": DAMAGE_JOURNAL, "want": want}
    while obs and turns < max_turns:
        if obs.get("mode") != "battle":
            # the active mon may have fainted into the forced party pick
            # ("Use next POKeMON?" -> party menu). With a backup alive,
            # send the replacement the spec's rule chooses — party depth
            # exists precisely so a lead faint is not a blackout.
            slot = battle_policy.choose_replacement(obs, spec)
            if (obs.get("mode") == "ui" and picks < 6 and slot):
                picks += 1
                log("battle_turn", turn=turns, op="pick_party",
                    params={"slot": slot}, why="replacement")
                nxt = bridge.send("pick_party", slot=slot)
                r = (nxt or {}).get("result") or {}
                obs = nxt
                if r.get("ok"):
                    continue
            break
        turns += 1
        ctx["turn"] = turns
        # WHO IS OUT is a decision the policy could not make. It fought
        # with whoever was sent in, so party order was the only lever and
        # a Pokemon too frail to survive a turn could never be in a battle
        # at all. The spec — which the model writes — may now name a slot
        # and the conditions for bringing it in; nothing here knows why a
        # switch might be worth a turn.
        ctx.setdefault("started_as", None)
        if ctx["started_as"] is None:
            for _n, _m in enumerate((obs.get("party") or []), 1):
                if _m.get("species") == ((obs.get("battle") or {})
                                         .get("me") or {}).get("species"):
                    ctx["started_as"] = _n
                    break
        _to = battle_policy.should_switch(obs, spec, ctx)
        if _to:
            log("battle_turn", turn=turns, op="battle_switch",
                params={"slot": _to}, why="spec switch rule")
            obs = bridge.send("battle_switch", slot=_to)
            if ((obs or {}).get("result") or {}).get("ok"):
                obs = bridge.obs() or obs
                continue
        # gen1 escape odds IMPROVE with each failed attempt (the formula
        # counts tries), so a small cap is self-defeating: capping at 3
        # left a no-attacking-PP Charmeleon fighting a wild Zubat with
        # GROWL for 31 turns until it wiped. Keep trying while the spec
        # says flee; the turn cap still bounds the battle.
        if (flees < 12 and battle_policy.should_flee(obs, spec, ctx)):
            flees += 1
            log("battle_turn", turn=turns, op="battle_run", params={},
                why=f"flee wild ({intent})")
            obs = bridge.send("battle_run")
            # An op that cannot even reach its menu entry is not a failed
            # flee, it is a broken control path — and ignoring the result
            # hid exactly that for 14422 attempts. Say so loudly once per
            # battle rather than silently burning the turn budget.
            r = (obs or {}).get("result") or {}
            if r.get("ok") is False:
                log("battle_run_failed", turn=turns, detail=r.get("detail"))
            continue
        op = battle_policy.choose(obs, spec, ctx)
        why = op.pop("_why", None)
        name = op.pop("op")
        idx = op.get("index")
        if SCORE_BATTLES and name == "battle_move":
            probed = bridge.send("battle_probe")
            probe = (probed.get("battle") or {}).get("probe")
            if probe:
                sc = battle_oracle.score_turn(idx, probe)
                if sc.get("scoreable"):
                    log("oracle_score", turn=turns, **sc)
            obs = bridge.obs()   # refresh (probe left a battle obs)
        before_b = (obs or {}).get("battle") or {}
        # HP alongside intent: six logged EMBERs vs a 41-HP Staryu ended in
        # a wipe, which the damage math says is impossible — whether the
        # presses deliver the scored move is only visible as an HP trace.
        log("battle_turn", turn=turns, op=name, params=op, why=why,
            foe_hp=(before_b.get("foe") or {}).get("hp"),
            me_hp=(before_b.get("me") or {}).get("hp"))
        move_id = None
        if name == "battle_move":
            mv = next((m for m in ((before_b.get("me") or {}).get("moves")
                                   or []) if m.get("index") == idx), None)
            move_id = (mv or {}).get("id")
        obs = bridge.send(name, **op)
        r = (obs or {}).get("result") or {}
        if r.get("ok") is False:
            # A rejected op is not a turn. At 200x the battle INTRO outlasts
            # one op's worth of A-presses, so the opening battle_move calls
            # come back "menu never appeared" — and counting them as turns
            # burned three phantom Embers against Misty before a real one
            # fired. Same class as the flee check above: never ignore the
            # op's result.
            log("battle_move_failed", turn=turns, detail=r.get("detail"))
            turns -= 1
            op_fails += 1
            if op_fails >= 8:
                break
            continue
        op_fails = 0
        if move_id:
            _journal_damage(before_b, obs, move_id)
    log("battle_done", turns=turns, mode=obs.get("mode") if obs else None)
    return obs


def battle_slot1(bridge, obs, log, max_turns):
    """Baseline for comparison only: spam slot 1 (the old placeholder)."""
    turns = 0
    while obs and obs.get("mode") == "battle" and turns < max_turns:
        turns += 1
        obs = bridge.send("battle_move", index=1)
    return obs


# WHAT it is trying to catch rides along with the intent. The catch branch
# used to look only at "is this wild and do I have a ball", so a subgoal
# reading party_type WATER-or-GRASS threw at the first thing that appeared
# — which is how a WEEDLE joined the party while the objective it was
# authored for went unmet, and how balls that were meant for an Oddish were
# spent on bugs. The model gets no turn inside a wild battle, so it cannot
# work around this itself; the target has to travel with the policy.
BATTLE_POLICIES = {
    "default": lambda b, o, lg, mt, want=None: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="fight"),
    "typed_v0": lambda b, o, lg, mt, want=None: _run_policy(
        battle_policy.SPECS["typed_v0"], b, o, lg, mt, intent="fight"),
    "slot1": lambda b, o, lg, mt, want=None: battle_slot1(b, o, lg, mt),
    "traversal": lambda b, o, lg, mt, want=None: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="traversal"),
    "catch": lambda b, o, lg, mt, want=None: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="catch", want=want),
}


# HOW THE POKEMON ARRIVES IS NOT IN THE PREDICATE (user, 2026-08-17).
# party_size, party_type, has_species and dex_owned are each satisfied two
# completely different ways: you catch the thing in the grass, or somebody
# hands it to you across a counter. The predicate cannot tell those apart,
# and the policy was chosen from the predicate ALONE — so run 4 read
#
#   talk_to_clerk  "Talk to the clerk to retrieve the Pokemon"
#                  done_when {"party_size": 2}
#
# and went out to Route 1 to throw balls at Pidgeys, with the clerk one
# door away and the subgoal's own sentence naming her twice. The subgoal
# said talk; the id said talk; the harness read the number. Every battle
# under it logged policy=catch, the lead came out of it at 2/22hp, and
# a Pidgey satisfied the counter, so the subgoal reported DONE without the
# clerk ever being spoken to.
#
# WHICH WAY TO BREAK THE TIE, and why it is not "whatever the words say".
# Getting this backwards has already cost a run once in each direction:
# catch_backup ran the traversal policy and KO'd every wild it met with 13
# balls in the bag, and this run ran catch on an errand. But the two
# failures are not the same size. A wrongly-traversing catch subgoal FAILS
# and escalates, and the model gets to see it fail. A wrongly-catching
# errand SUCCEEDS — falsely, on a counter that any wild satisfies — and
# nothing downstream can question it, which is the same reason the touch
# ledger is written only for interactions that completed. So when the
# words and the number disagree, take the recoverable failure.
#
# The words are read narrowly and asymmetrically, so that a subgoal saying
# neither thing behaves exactly as it does today:
#   * says CATCH  -> catch, whatever else it says. The predicate is
#                    confirmed, not overridden.
#   * says TALK   -> not catch. This also fixes the honest case nobody had
#                    noticed: a Pokemon somebody GIVES you (the aide, the
#                    Magikarp salesman, the fossil revival) satisfies
#                    party_size without a ball being thrown, and used to
#                    send the run hunting anyway.
#   * says neither -> the predicate decides, as before.
# Measured before it shipped: over all 677 distinct subgoals in every plan
# ever written, exactly ONE changes policy — the clerk errand above.
_CATCH_WORDS = ("catch", "catching", "caught", "capture", "wild", "grass",
                "ball", "balls")
_GIVEN_WORDS = ("talk", "speak", "ask", "asking", "interact", "clerk",
                "cashier", "receptionist", "attendant", "aide", "nurse",
                "receive", "deliver", "give", "trade", "buy", "purchase",
                "sell")


def _subgoal_words(subgoal: dict) -> set:
    """The subgoal's own sentence, as words. The id counts: `talk_to_clerk`
    carries the signal even when goal_text is empty, and an underscore is a
    WORD character to a regex, so the id has to be broken up first or
    nothing in it ever matches."""
    text = f"{subgoal.get('id') or ''} {subgoal.get('goal_text') or ''}"
    return set(_re.findall(r"[a-z]+", text.lower().replace("_", " ")))


# the fifteen gen-1 type names, for telling a wanted TYPE from a wanted
# SPECIES on an op's want= (planner/engine_types.txt is the same list)
TYPE_NAMES = {"NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK",
              "BUG", "GHOST", "FIRE", "WATER", "GRASS", "ELECTRIC",
              "PSYCHIC", "ICE", "DRAGON"}


def choose_battle_policy(subgoal: dict) -> tuple:
    """(policy name, why) for one subgoal. Pure: no game, no observation.

    An explicit battle_policy on the subgoal always wins — the model asked
    for it by name and that is its decision to make.
    """
    name = subgoal.get("battle_policy")
    if name:
        return (name if name in BATTLE_POLICIES else "traversal"), "declared"
    keys = pred_keys(subgoal.get("done_when") or {})
    words = _subgoal_words(subgoal)
    if keys & {"party_size", "party_type", "has_species", "dex_owned"}:
        if words & set(_CATCH_WORDS):
            return "catch", "predicate, and the subgoal says so"
        if words & set(_GIVEN_WORDS):
            # the whole point of the rule: say which two things disagreed
            return "traversal", (
                "the predicate could be satisfied by catching, but this "
                "subgoal is about " + ", ".join(
                    sorted(words & set(_GIVEN_WORDS))) + " — a Pokemon "
                "handed over is not a Pokemon hunted, and a false success "
                "on the counter cannot be taken back")
        return "catch", "predicate"
    if keys & {"lead_level", "party_min_level", "slot_level"}:
        return "default", "predicate"
    return "traversal", "default"


# ----------------------------------------------------------------- executor
class Executor:
    def __init__(self, bridge: Bridge, max_battle_turns: int = 40,
                 can_escalate: bool = False, model: str = "",
                 plan=None, plan_path=None, run_id: str = "run"):
        self.b = bridge
        self.max_battle_turns = max_battle_turns
        self.can_escalate = can_escalate
        self.model = model
        self.plan = plan
        self.plan_path = plan_path
        self.failed_subgoal = None      # set by run_plan, read at exit
        self.run_id = run_id
        self.escalations = 0
        self._st: dict = {}         # live status (run/status.txt)
        # exploration memory: {"MAP|region": {(x,y): {"n": k, "to": "MAP|reg"}}}
        # Without it the run re-takes the same ladder forever (thin8 spent 12
        # redo rounds ping-ponging one warp). This is memory, not reward
        # shaping: it says where you HAVE been, the model still chooses.
        self.explored: dict = {}
        self.dead_ends: dict = {}   # subgoal id -> {region: failures}
        self.visits: dict = {}      # region -> times arrived
        self.frontier: dict = {}    # region -> every exit visible from it
        self.sightings: dict = {}   # region -> named objects seen there
        self.region_anchors: dict = {}   # map -> {cell: region name}
        self.searched: dict = {}    # "*" -> {region: fully worked};
                                    # flag:/item: keys add per-target claims
        self.contested: dict = {}   # target -> {region: a fight ran here}
        # (region, exit key, dest) triples a WALK has refuted: the
        # router synthesizes reverse-seam edges every call, so a
        # false one cannot be voided, only remembered.
        self._bad_seam: set = set()
        self._arrived = None        # (region, (x,y)) — the door we came in by
        self._came_from = None      # the region we were in a moment ago
        self._reversals = 0
        self._dead_visits = 0
        # THE OUTCOME LEDGER (EXPLORE_DESIGN §3, §6b): per "target|area",
        # per exit key or object name, how many times THIS subgoal did it
        # and what happened last, verbatim from the trace. Read by
        # ledger.build so every entry the model sees carries its own
        # history — "walk south -> ROUTE_1 — taken 4x — ok (crossed)".
        # In-memory only: it describes this subgoal, not the world.
        self._outcomes: dict = {}
        # THE PLAN ECHO (§6c): the model's own one-or-two-sentence plan
        # from its last reply, shown back to it next round. Ours to keep,
        # never to write.
        self._plan_said = ""
        # ...and the last few, with where it stood each time. Measured on
        # the first 128 ledger-era rounds: 19% of consecutive plans were a
        # leave-then-return flip ("Route 1 is fully worked, I will go
        # north" -> "the goal is on Route 1, I will return"), each round a
        # fresh derivation from the subgoal text with only the LAST plan in
        # view. Seeing its own last four in a row is how the flip becomes
        # visible to the one who is doing it. Its words, unedited.
        self._plans_said: list = []
        self._skipped = None        # subgoal id the model declared moot
        self._entered_map: dict = {}   # "target|map" -> entries for target
        self._revisit_refusals: dict = {}   # target -> refusals spent
        self._battle_regions: set = set()   # "target|region" a fight ran in
        self._blackouts: dict = {}          # target -> party wipes
        self._blackout_lead: dict = {}      # target -> lead level, last wipe
        self._faint_at = None               # region we were in when wiped
        self._ui_pending = 0                # rounds a prompt has sat open
        self._dead_ops: dict = {}           # (target, op, arg) -> failures
        self._dead_at: dict = {}            # ...and the world mark they are OF
        self._ferried: dict = {}            # target -> {region: untried set}
        self.map_doors: dict = {}           # map id -> every doorway seen
        self.save_each = False              # in-game SAVE after each subgoal
        self._tried_objs: dict = {}         # region -> objects interacted
        self._drift: dict = {}              # subgoal -> goalward progress
        self._pred_said: set = set()        # malformations already reported
        self._inert_objs: dict = {}         # region -> {object: state it was inert in}
        self._cant_afford: dict = {}        # item -> unit price we lack
        self._no_cross: dict = {}           # region -> dirs proven uncrossable
        # THE BLOCKERS LEDGER (EXPLORE_DESIGN §8): ways that turned the run
        # back, anywhere, remembered across targets and attempts so they
        # are not rediscovered — the Saffron guard was met on Route 8, then
        # Route 7, then Route 8 again, a leg apart each time. The HARNESS
        # writes what happened (a door that refused, the fixed ghost, a
        # script that spoke and turned you back); the MODEL names what it
        # thinks lifts each one, as a predicate like a goal's, and the
        # harness only reports whether that holds now. key = "AREA|exit".
        self.blockers: dict = {}
        self._op_intent = None
        # region -> {dir: world mark when it was proven}. A seam proof that
        # never expires is the one thing a shut DOOR is not (see _sealed).
        self._no_cross_at: dict = {}
        # region -> {key: {n, at}} — exits attempted that could not even be
        # reached, so nothing about them was recordable (see _spent_exits)
        self._exit_tries: dict = {}
        self._mark_now = None               # world mark as of the last settle
        self._rounds_here: dict = {}        # target|region -> rounds spent
        self._fight_region: str | None = None   # where the last trainer fought
        self.flag_sites: dict = {}          # flag -> area it fired in
        self.shut_doors: dict = {}   # region -> doors seen but unreachable
        self._last_obs_dormant = 0   # objects this map has yet to reveal
        self._last_key_items: list = []
        self._touch_bag: dict = {}   # region -> key items held when pressed
        # region -> {object name: [world mark when pressed, times re-offered]}
        self._touch_mark: dict = {}
        self.hints: dict = {}
        self.hints_at: dict = {}     # region -> {line: flags fired when heard}
        self._offered: dict = {}     # map -> {species: wild encounters}
        self._dead_why: dict = {}    # op signature -> last failure detail
        self._cut_bushes: dict = {}  # map -> ["x,y", ...] bushes cut before
        self._shelves: dict = {}     # mart map -> [items it sells], as seen
        self._plan_hist: dict = {}   # target -> [(round, where, plan)] last 8
        self._last_overworld_map = None
        self._known_flags = None            # None until the first obs
        self._last_said = ""                # dedupe repeated dialogue
        # A RESUMED SAVE ARRIVES MID-SENTENCE. The loaded game still holds
        # the last line it printed before saving, and the bootstrap
        # observation has not seen it yet — so the very first op of a run
        # looks like the thing that said it. Resuming inside the Vermilion
        # gym had a warp announce "Nope, there's only trash here." Nothing
        # precedes the first op, so nothing may be attributed to it.
        self._said_ready = False
        self._cur_target = ""
        self._idle_rounds = 0
        self._load_memory()
        # ATLAS: map edges observed so far this run ({map_id: {dir: dest}}).
        # Pure memory of past observations (the obs already showed each map's
        # connections while standing on it), re-served to the model so multi-
        # leg routing uses seen geography instead of its shaky world prior
        # (brock9: it kept hunting for Pallet WEST of Viridian, on ROUTE_22).
        self.atlas: dict = {}
        # How often each subgoal id has ALREADY failed, read from the
        # persisted journal: the cross-attempt rap sheet that shrinks a
        # repeat offender's escalation budget.
        self._prior_subgoal_fails: dict = {}
        self._retalked: set = set()     # people re-talked this attempt
        try:
            for line in (RUN / "executor_log.jsonl").read_text() \
                    .splitlines():
                if ('"subgoal_failed"' in line
                        or '"subgoal_failed_continuing"' in line
                        or '"plan_failed_at"' in line):
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    sid = d.get("subgoal")
                    if sid:
                        self._prior_subgoal_fails[sid] = \
                            self._prior_subgoal_fails.get(sid, 0) + 1
        except OSError:
            pass
        self.logf = open(RUN / "executor_log.jsonl", "a")
        self.t0 = time.time()

    # WHAT A BUILDING LOOKS LIKE FROM THE STREET. `dest` was carrying two
    # different facts and hiding it hid both: the MAP ID behind a door (you
    # cannot read that through a doorway, and it stays hidden) and WHAT KIND
    # OF BUILDING it is (you absolutely can — a gen 1 POKEMART and POKEMON
    # CENTER have their own roofs and their own signs on the street, and a
    # GYM is signed).
    #
    # Watched live, and it is not cosmetic: a clean-room run reached Viridian
    # with "(29,19)->UNKNOWN, (32,7)->UNKNOWN" and no way to tell the MART —
    # which holds Oak's Parcel, which is the only thing that moves the old
    # man off the road north — from a stranger's front door. It bounced
    # between Route 1 and the city border instead.
    #
    # Derived from the destination map id, which is fine: the harness may use
    # the table to compute something the player can SEE, the way use_warp
    # already uses it to retry a doorway's twin. What it may not do is hand
    # over the answer. A house stays UNKNOWN, because a house looks like a
    # house.
    _FRONTAGE = (("_MART", "a POKEMART — the shop roof and its sign are "
                           "visible from the street"),
                 ("_POKECENTER", "a POKEMON CENTER — the red roof is visible "
                                 "from the street"),
                 ("_GYM", "a GYM — it is signed outside"))

    @staticmethod
    def _frontage(dest_map) -> str | None:
        for suffix, words in Executor._FRONTAGE:
            if str(dest_map or "").endswith(suffix):
                return words
        return None

    # THE TOUCH RULE, in one place because it has now been got wrong in
    # two. A thing is written into the lifetime touched ledger ONLY for an
    # interaction that COMPLETED. Not one that never happened, not one that
    # asked a question nobody answered, not one whose fight was lost.
    #
    # The ledger is monotone and every consumer trusts it — the untouched
    # list, the fully-worked proof, the escort's ranking, the sweep's own
    # "everything reachable here has been tried". A false entry there is
    # not a missing hint, it is a WRONG FACT that nothing downstream can
    # question, and it is unrecoverable by design.
    #
    # It cost the Mt Moon fossils: the blind sweep pressed both, was asked
    # "You want the DOME FOSSIL?", declined (no answer given IS a decline),
    # and recorded them as done. The room read fully worked and the run
    # left the mountain with neither.
    #
    # _run_traced implements the same rule the other way round — it marks
    # provisionally before the op and RETRACTS on the three conditions
    # below. Both directions are fine; having neither, as the sweep did, is
    # not. If a fourth condition is ever found, it belongs in both.
    def _op_spoke(self, pre_obs: dict, obs: dict, said: str) -> bool:
        """Did THIS op cause a line to be PRINTED?

        Ask the counter, not the words. `last_text` outlives the box that
        printed it, so an op that said nothing of its own inherits whatever
        was said last — a warp out of the gym once reported "Nope, there's
        only trash here." Guarding that with "the text must have CHANGED"
        fixed the smear and created the opposite fault: ANYONE WHO REPEATS
        THEMSELVES GOES SILENT. A repeated line and a stale line are the
        same string and completely different facts.

        It cost this run the Viridian mart. The clerk says "Okay! Say hi to
        PROF.OAK for me!" every single time she is pressed, which names the
        next objective outright. The run was shown it on the first press
        and never again, and pressed her round after round after that,
        waiting for a Pokemon she does not have, told only "ok (moved,
        dialog still open)". A human watching could read the answer on
        screen the whole time.

        shim.note_text bumps `text_seq` whenever the game prints anything,
        so the question is settled without looking at the words at all. An
        observation with no counter — an old fixture, a replayed journal —
        keeps the string test it was recorded under rather than going
        quiet, so replaying old evidence still behaves as it did.
        """
        s1 = (obs or {}).get("text_seq")
        if isinstance(s1, int):
            return s1 != (pre_obs or {}).get("text_seq")
        return (bool(said) and said != self._last_said
                and said != ((pre_obs or {}).get("last_text") or "").strip())

    def _record_touch(self, region, name, res_obs) -> bool:
        """Write a touch, if the interaction earned it. Returns whether."""
        if not (region and name) or "None" in str(region):
            return False
        r = ((res_obs or {}).get("result") or {})
        if not r.get("ok"):
            return False                       # it never happened
        if ASKING in str(r.get("detail") or ""):
            return False                       # it asked; nothing answered
        self._tried_objs.setdefault(region, set()).add(name)
        self._stamp_touch(region)
        self._mark_touch(region, name, res_obs)
        return True

    def _note_blocker(self, area: str, key: str, kind: str, what: str):
        """Write (or bump) a way that turned the run back. Evidence only:
        WHERE, WHICH exit, WHAT was seen or said. Never what lifts it."""
        if not area or not key or "None" in str(area):
            return
        bk = f"{area}|{key}"
        b = self.blockers.setdefault(bk, {
            "where": area, "key": str(key), "kind": kind, "n": 0,
            "what": "", "lifts": None, "lifts_note": "", "cleared": False,
            "first": self._cur_target or ""})
        b["n"] = int(b.get("n") or 0) + 1
        w = (what or "").strip()
        if w:
            # keep what the FIGHT probe wrote: it is the one sentence that
            # says the fixed ghost cannot be fought, and a repeat of the
            # same "Be gone" line must not erase it
            keep = ""
            old = b.get("what") or ""
            if " — you pressed FIGHT" in old:
                keep = old[old.index(" — you pressed FIGHT"):]
            b["what"] = (w + keep)[:260] if keep and "you pressed FIGHT" not in w \
                else w[:260]
        b["cleared"] = False
        b["last"] = self._cur_target or ""

    def _clear_blocker(self, area: str, key: str, how: str):
        b = self.blockers.get(f"{area}|{key}")
        if b and not b.get("cleared"):
            b["cleared"] = True
            b["cleared_how"] = (how or "")[:160]
            self.log("blocker_cleared", where=area, key=str(key), how=how)

    def _declare_blockers(self, decls, obs) -> list:
        """The MODEL's word on blockers, from its reply's "blockers" key:
        [{"where": AREA?, "key": exit?, "what": ..., "lifts": {pred},
          "cleared": bool}]. Matches a recorded blocker by area (+ key when
        given), else records a new one it names. Returns trace lines."""
        out = []
        here = self._where(obs)
        for d in decls or []:
            if not isinstance(d, dict):
                continue
            where = str(d.get("where") or here or "").strip()
            key = str(d.get("key") or "").strip()
            cands = [b for b in self.blockers.values()
                     if b.get("where") == where
                     or (where and b.get("where", "").split("|")[0] == where)]
            if key:
                cands = [b for b in cands if b.get("key") == key]
            b = None
            if cands:
                live = [b for b in cands if not b.get("cleared")]
                b = (live or cands)[0]
            elif where:
                bk = f"{where}|{key or 'way'}"
                b = self.blockers.setdefault(bk, {
                    "where": where, "key": key or "way", "kind": "named",
                    "n": 0, "what": "", "lifts": None, "lifts_note": "",
                    "cleared": False, "first": self._cur_target or ""})
            if b is None:
                continue
            if d.get("what"):
                b["what"] = str(d["what"])[:220] if not b.get("what")                     else b["what"]
                b["your_words"] = str(d["what"])[:160]
            if isinstance(d.get("lifts"), dict) and d["lifts"]:
                b["lifts"] = d["lifts"]
                b["lifts_note"] = str(d.get("note") or "")[:120]
                out.append(f"noted: {b['where']} {b['key']} — you say "
                           f"{json.dumps(d['lifts'])} lifts it")
            if d.get("cleared") is True:
                b["cleared"] = True
                b["cleared_how"] = "you said so"
                out.append(f"noted: {b['where']} {b['key']} — you say it "
                           f"is dealt with")
        if out:
            self._save_memory()
        return out

    def _sweep_blockers(self, obs) -> None:
        """A fence that is no longer there is no longer a blocker.

        The Snorlax on Route 16 was woken and walked off; its entry stayed
        on the list saying the way was fenced by it. What the harness
        RECORDED was "these things stood across the walk" — so when none of
        the named things is on the map any more, the record has expired.
        Only entries whose text names things (the fenced class) are swept;
        a door that refused you is not disproved by anybody moving.
        """
        here = self._where(obs)
        names = {str(o.get("name") or "")
                 for o in ((obs.get("map") or {}).get("objects") or [])}
        for bk, b in (self.blockers or {}).items():
            if b.get("cleared") or b.get("where") != here:
                continue
            what = str(b.get("what") or "")
            if "the walk was fenced" not in what:
                continue
            named = _re.findall(r"([A-Z][A-Z0-9_]{3,})", what)
            named = [n for n in named if n not in ("CUT",)]
            if named and not any(n in names for n in named):
                b["cleared"] = True
                b["cleared_how"] = "what fenced it is no longer on this map"
                self.log("blocker_cleared", where=b.get("where"),
                         key=b.get("key"), how="fence gone")

    def blockers_text(self, obs, cap: int = 4) -> str:
        """WAYS THAT TURNED YOU BACK, nearest first, with the model's own
        lifting condition and whether it holds now. Empty when none."""
        self._sweep_blockers(obs)
        here = self._where(obs)
        rows = []
        for bk, b in self.blockers.items():
            if b.get("cleared"):
                continue
            path = self._route(here, b["where"]) if here else None
            dist = (len(path) if path is not None
                    else (0 if b["where"] == here else 99))
            rows.append((dist, bk, b))
        if not rows:
            return ""
        rows.sort(key=lambda r: (r[0], r[1]))
        lines = []
        for i, (dist, bk, b) in enumerate(rows[:cap], 1):
            k = b.get("key") or "way"
            what = ("a door" if b.get("kind") == "door"
                    else "the way" if b.get("kind") == "seam" else "a way")
            spot = (f"{what} ({k})" if b.get("kind") == "door"
                    else f"the way {k}" if b.get("kind") == "seam"
                    else f"{k}")
            far = ("here" if dist == 0 else
                   f"{dist} leg(s) away" if dist < 99 else
                   "no walked route from here")
            line = f"  {i}. {b['where']}, {spot}, {far} — turned you back"
            if b.get("n"):
                line += f" {b['n']}x"
            if b.get("what"):
                line += f" — {b['what']}"
            if b.get("your_words"):
                line += f" — you called it: {b['your_words']}"
            if b.get("lifts"):
                holds = pred_holds(b["lifts"], obs)
                line += (f" — you said {json.dumps(b['lifts'])} lifts it: "
                         + ("THAT HOLDS NOW — worth going back to try"
                            if holds else "not yet"))
            else:
                line += (" — nothing named yet as what lifts it")
            lines.append(line)
        more = len(rows) - min(len(rows), cap)
        return ("\nWAYS THAT HAVE ALREADY TURNED YOU BACK — not places to go: "
                "a record of what refused you and what was seen or said, "
                "kept so it is not tried again UNCHANGED. Nothing about you "
                "changed since = the same way gives the same answer; the "
                "untried ground is in the ledger above and in the places "
                "with ways never taken. If you know what would lift one, "
                "write it as \"blockers\":[{\"where\":AREA,\"lifts\":"
                "{condition}}] (a DONE_WHEN-style condition) and this list "
                "will say when you actually have it; \"cleared\":true when "
                "one is dealt with:\n"
                + "\n".join(lines)
                + (f"\n  (+{more} more, further off)" if more > 0 else ""))

    def _record_outcome(self, pre_obs, op: str, step: dict, note: str):
        """The outcome ledger: per (target|area) per key, how many times
        THIS subgoal did this thing here and what happened last, verbatim
        from the trace line minus the op's own name (the ledger prints the
        key). Read by ledger.build, so the entry the model sees next round
        says "taken 4x — ok (map->ROUTE_1, crossed)" or "pressed 3x — the
        world did not change, but it SPOKE — it said: ...". A wiped-out op
        is recorded like any other: what happened is what happened."""
        if op == "use_warp":
            key = f"{step.get('x')},{step.get('y')}"
        elif op == "cross":
            key = str(step.get("dir"))
        elif op == "interact" and step.get("name"):
            key = str(step["name"])
        else:
            return
        here = self._where(pre_obs)
        if not here or "None" in str(here):
            return
        book = self._outcomes.setdefault(f"{self._cur_target}|{here}", {})
        rec = book.setdefault(key, {"n": 0, "last": ""})
        rec["n"] = int(rec.get("n") or 0) + 1
        last = note.split(": ", 1)[1] if ": " in note else note
        rec["last"] = last.strip()[:200]
        # A WAY THAT SPOKE AND DID NOT OPEN turned you back: the fixed
        # ghost, a guard's line, a sleeping thing's — evidence for the
        # blockers ledger, in the words the game used.
        if op in ("use_warp", "cross") and "map->" in note:
            self._clear_blocker(here, key, "it opened")
        if op in ("use_warp", "cross") and (
                "GHOST appeared on the way" in note
                or ("did not change, but it SPOKE" in note)):
            said = ""
            if "it said: " in note:
                said = note.split("it said: ", 1)[1].strip()[:160]
            what = ("a GHOST appeared on the way there"
                    if "GHOST appeared on the way" in note else "")
            what = (what + (" — " if what and said else "") + said).strip()
            self._note_blocker(here, key,
                               "door" if op == "use_warp" else "seam",
                               what or "it spoke and did not open")
        # ...and a seam whose walk was fenced by somebody standing there
        # (the Snorlax on Route 12, a guard in a corridor) — the diagnostic
        # names them; keep that as the blocker's words
        # ...and a DOOR whose walk was interrupted by a script that spoke.
        # The Cycling Road gate shoves pedestrians back with "No pedestrians
        # are allowed on CYCLING ROAD!" — the op reports "couldn't reach the
        # warp tile (interrupted (battle or script))" with the line
        # attached, which is a refusal in every sense, and nothing recorded
        # it as one.
        elif (op == "use_warp" and "FAILED" in note
              and "interrupted (battle or script)" in note
              and "it said:" in note):
            said = note.split("it said: ", 1)[1].strip()[:160]
            self._note_blocker(here, key, "door",
                               f"a script turned you back — {said}")
        elif op == "cross" and "FAILED" in note and (
                "standing at its edge:" in note
                or "Right where the walk stopped:" in note):
            for tag in ("standing at its edge:", "Right where the walk stopped:"):
                if tag in note:
                    clause = note.split(tag, 1)[1].strip().split(".")[0][:160]
                    self._note_blocker(here, key, "seam",
                                       f"the walk was fenced — {clause}")
                    break

    def _go_step(self, sg, obs, step, ignore_done=False):
        """Walk to an area this run has walked before, by walked edges only.

        `to` is an area as the ledger names it (MAP|x,y) or a bare map id
        (then the nearest walked area of that map). No destination is
        guessed: if no chain of walked exits joins here to there, that is
        the answer. Returns (done, trace_lines, clean_ops)."""
        want = str(step.get("to") or step.get("area") or step.get("map")
                   or "").strip()
        here = self._where(obs)
        if not want:
            return False, ["go: say where — {\"op\":\"go\",\"to\":AREA} "
                           "with an area you have walked, as the ledger "
                           "names it"], []
        known = set(self.visits or {}) | set(self.explored or {}) \
            | set(self.frontier or {})
        if want in known:
            targets = [want]
        else:
            # a bare map id means some OTHER walked part of that map when
            # you are already standing on it
            targets = [r for r in known
                       if r.split("|")[0] == want and r != here]
            if not targets and here.split("|")[0] == want:
                targets = [here]
            if not targets:
                near = sorted({r.split("|")[0] for r in known
                               if want.split("|")[0][:5] in r})[:4]
                return False, [f"go: {want} is not anywhere you have walked"
                               + (f" — walked places with a name like it: "
                                  f"{', '.join(near)}" if near else "")
                               + "; only walked ground can be gone back "
                                 "to this way"], []
        if here in targets:
            return False, [f"go: you are already in {here}"], []
        best = None
        for t in targets:
            path = self._route(here, t)
            if path and (best is None or len(path) < len(best[1])):
                best = (t, path)
        if not best:
            return False, [f"go: no walked way from {here} to {want} is "
                           f"known — you have never walked a connected "
                           f"chain of exits between them (or a hop on it "
                           f"has failed in this world state)"], []
        region, path = best
        self.log("go_step", subgoal=sg.get("id"), to=region, legs=len(path))
        arrived = self._walk_route(sg, path)
        cur = self.settle() or {}
        at = arrived or self._where(cur) or "an unexpected stop"
        tr = [f"go: walked {len(path)} leg(s) over walked ground toward "
              f"{region} — now at {at}"]
        if not ignore_done and pred_holds(sg.get("done_when"), cur):
            return True, tr, [dict(step)]
        if self._where(cur) != region:
            tr.append("go: the walk did not arrive; author from here")
            return False, tr, []
        return False, tr, [dict(step)]

    def _explore_step(self, sg, obs, ignore_done=False):
        """One deterministic frontier expansion, because the model asked.

        The order is ledger.plan_explore's, and the ledger's ranking is
        arithmetic on walked ground: press the first thing here never
        pressed (items, then fixtures, people, signs); else take the best
        exit here never taken; else walk over walked ground to the nearest
        area that still has one and take or press it there; else say that
        nothing untried is reachable. It knows no destinations it has not
        walked and prefers no door for what is behind it. What it chose to
        run is run through _run_traced, so the touch rule, the hint
        ledger, transitions, blackout detection and the outcome ledger all
        see it as they would any op — and the concrete op is what gets
        distilled, never the word "explore".

        Returns (done, trace_lines, clean_ops)."""
        target = self._cur_target or ""
        cands = ledger.build(self, obs, target,
                             outcomes=self._outcomes_here(obs),
                             want_explore=False)
        order = {"item": 0, "fixture": 1, "cut_tree": 1, "npc": 2,
                 "trainer": 2, "sign": 3}
        outs = self._outcomes_here(obs)
        things = sorted((c for c in cands
                         if c.status in ("untouched", "unspoken", "cuttable")
                         and c.reachable
                         and c.kind not in ("door", "seam", "op")
                         # the observation called it reachable and the press
                         # said otherwise: believe the press. explore re-
                         # picked SLOT_MACHINE_13 three rounds running on
                         # the obs's word while interact kept failing "no
                         # reachable tile adjacent to target".
                         and "no reachable tile" not in
                         ((outs.get(c.key) or {}).get("last") or "")),
                        key=lambda c: (order.get(c.kind, 4), c.key))
        exits = [c for c in cands
                 if c.status == "untried" and c.kind in ("door", "seam")]

        def _run(step, why):
            ok, tr, cl = self._run_traced(sg, [step], ignore_done=ignore_done)
            return ok, [f"explore ({why}): {t}" for t in tr], cl

        def _thing_op(c):
            if c.status == "cuttable":
                return ({"op": "field_move", "move": "CUT", "x": c.x, "y": c.y},
                        f"cutting the bush at ({c.x},{c.y})")
            return ({"op": "interact", "name": c.key},
                    f"{len(things)} thing(s) here never pressed; "
                    f"pressing {c.key} first")

        if things:
            c = things[0]
            self.log("explore_step", subgoal=sg.get("id"), step="press",
                     what=c.key, left=len(things))
            return _run(*_thing_op(c))
        if exits:
            c = exits[0]
            self.log("explore_step", subgoal=sg.get("id"), step="exit",
                     what=c.key, left=len(exits))
            step = ({"op": "cross", "dir": c.key} if c.kind == "seam"
                    else {"op": "use_warp",
                          "x": int(c.key.split(",")[0]),
                          "y": int(c.key.split(",")[1])})
            return _run(step, f"{len(exits)} exit(s) here never taken; "
                              f"taking {c.label()}")
        # nowhere here: the nearest area over walked ground with a way never
        # taken or a thing never pressed (same rule as ledger.plan_explore)
        here = self._where(obs)
        best = None
        regions = set(list(self.frontier or {}) + list(self.sightings or {}))
        for region in regions:
            if region == here:
                continue
            left = self._frontier_left(region)
            unpressed = ledger.untouched_in(self, region)
            if not (left or unpressed):
                continue
            path = self._route(here, region)
            if not path:
                continue
            r = (len(path), -(len(left) + len(unpressed)), region)
            if best is None or r < best[0]:
                best = (r, region, left, unpressed, path)
        if not best:
            self.log("explore_step", subgoal=sg.get("id"), step="none")
            return False, ["explore: nothing untried anywhere you can walk "
                           "to over walked ground — something you have done "
                           "must be undone or something you carry must be "
                           "used to open new ground"], []
        _, region, left, unpressed, path = best
        self.log("explore_step", subgoal=sg.get("id"), step="walk",
                 to=region, legs=len(path), left=len(left),
                 unpressed=len(unpressed))
        arrived = self._walk_route(sg, path)
        cur = self.settle() or {}
        tr = [f"explore: this area is fully worked, so you were walked "
              f"{len(path)} leg(s) over walked ground to {region}, which "
              f"still has {len(left)} exit(s) never taken and "
              f"{len(unpressed)} thing(s) never pressed — now at "
              f"{arrived or self._where(cur) or 'an unexpected stop'}"]
        if not ignore_done and pred_holds(sg.get("done_when"), cur):
            return True, tr, []
        if self._where(cur) != region:
            tr.append("explore: the walk did not arrive; author from here")
            return False, tr, []
        # one expansion on arrival — the same order as at home
        cands2 = ledger.build(self, cur, target,
                              outcomes=self._outcomes_here(cur),
                              want_explore=False)
        outs2 = self._outcomes_here(cur)
        things2 = sorted((c for c in cands2
                          if c.status in ("untouched", "unspoken", "cuttable")
                          and c.reachable
                          and c.kind not in ("door", "seam", "op")
                          and "no reachable tile" not in
                          ((outs2.get(c.key) or {}).get("last") or "")),
                         key=lambda c: (order.get(c.kind, 4), c.key))
        exits2 = [c for c in cands2
                  if c.status == "untried" and c.kind in ("door", "seam")]
        if things2:
            things = things2                # for _thing_op's count
            ok, t2, cl = _run(*_thing_op(things2[0]))
            return ok, tr + t2, cl
        if exits2:
            c = exits2[0]
            step = ({"op": "cross", "dir": c.key} if c.kind == "seam"
                    else {"op": "use_warp",
                          "x": int(c.key.split(",")[0]),
                          "y": int(c.key.split(",")[1])})
            ok, t2, cl = _run(step, f"taking {c.label()} there")
            return ok, tr + t2, cl
        return False, tr, []

    def _outcomes_here(self, obs) -> dict:
        """This subgoal's outcome ledger for the area being stood in."""
        return self._outcomes.get(
            f"{self._cur_target}|{self._where(obs)}", {})

    def _retract_touch(self, region, name) -> None:
        """Un-write a provisional touch the interaction did not earn."""
        if region and name:
            self._tried_objs.get(region, set()).discard(name)

    def _walked_dest(self, map_id: str, key: str):
        """Where this run has actually come out when it took that door.

        A DOOR YOU HAVE NOT WALKED THROUGH HAS NEVER TOLD ANYONE WHERE IT
        GOES. `obs.map.warps[].dest` is the game's own warp table — it knows
        the far side of every door on the map the moment you set foot on it
        — and three model-facing lists were printing it for doors the run
        had never opened: the untried-exit list, the refusal text, and the
        atlas in every escalation prompt. Reporting that a doorway is THERE
        is stop-hiding; naming where it leads is pointing, and it is the
        same warp table already removed from the unopened-doors ledger.

        Keyed by MAP, not by region: the same coordinate in two regions of
        one floor is the same tile, so a door walked from the far side of a
        split map is a door this run has been through.

        Map EDGES are a different matter and keep their destinations — which
        roads touch is drawn on the Town Map the player is holding.
        """
        for reg, exits in (self.explored or {}).items():
            if reg.split("|")[0] != map_id:
                continue
            e = (exits or {}).get(key) or {}
            to = e.get("to")
            if to and to != reg and not e.get("shut"):
                return to
        return None

    def _taken_here(self, region) -> dict:
        """Exits this region counts as ALREADY TAKEN.

        A DOOR IS A TILE, AND A TILE BELONGS TO THE MAP. The walked ledger
        is keyed by REGION, and one map can end up under several region
        labels — Cerulean carried four. The label the run actually lives in
        had 426 visits and all eleven exits taken; a label it had stood in
        TWICE inherited the whole city's doorway list and reported ten of
        them as ways never tried. So every round, from the 426-visit label,
        the model was told there was somewhere new two legs away whose
        first step was the trashed-house door it had already opened 37
        times — and it went, and did it again, for hours. It was doing
        exactly what it was told.

        A coordinate key is the same tile whichever label you are standing
        in, so "taken" for those is a fact about the MAP. Directions stay
        region-local: on a genuinely split map the stub side cannot reach
        the far seam, and telling it that seam is taken would delete the
        one discovery that opens the map (Route 4's two halves are the
        standing example).

        The region's own entry always wins, so counts and shut-flags the
        run earned here are never overwritten by a neighbour's.
        """
        own = dict(self.explored.get(region) or {})
        mid = str(region).split("|")[0]
        for r2, ex2 in (self.explored or {}).items():
            if r2 == region or r2.split("|")[0] != mid:
                continue
            for k, e in (ex2 or {}).items():
                # coordinates only; a direction is not a tile
                if "," in k and k not in own:
                    own[k] = e
        return own

    def _note_unreached(self, region, key, obs):
        """Count an attempt that left no evidence. Keyed to the world it was
        made in, so the count starts again when anything changes."""
        if not (region and key):
            return
        now = self._world_mark(obs)
        book = self._exit_tries.setdefault(region, {})
        rec = book.get(key)
        if not isinstance(rec, dict) or rec.get("at") != now:
            rec = {"n": 0, "at": now}
            book[key] = rec
        rec["n"] = (rec.get("n") or 0) + 1

    def _spent_exits(self, region) -> dict:
        """Exits tried more than once in THIS state of the world, and never
        got through. Two, not one: the whole reason an unreachable attempt
        records no edge is that a wanderer in the doorway is not a fact
        about the door, and one failure could always be that."""
        now = getattr(self, "_mark_now", None)
        if now is None:
            return {}
        return {k: rec["n"]
                for k, rec in (self._exit_tries.get(region) or {}).items()
                if isinstance(rec, dict) and rec.get("at") == now
                and (rec.get("n") or 0) >= 2}

    @staticmethod
    def _holding_town_map(obs) -> bool:
        """Is the printed map actually in the bag? It is an item in this
        game, gettable from Daisy in Blue's house, and until the run has it
        the layout of Kanto is not something the player can read."""
        return "TOWN_MAP" in ((obs or {}).get("bag") or {})

    def _sealed(self, region) -> set:
        """Seams still proven uncrossable AS OF NOW.

        THE HARNESS HAS TWO RULES FOR "THIS WAY IS SHUT" AND ONLY ONE OF
        THEM EXPIRED. A shut DOOR carries `shut_at` and is offered again
        the moment the world mark differs — "a door that turned you back is
        worth one more press once you are carrying something you were not
        carrying then". A seam proof was a bare set: proven once, shut for
        ever. The live ledger holds seven of them and one is
        `ROUTE_5|1,0 south`, the Saffron guards — the seam that opens when
        the run finally has the drink, and that nothing would ever have
        offered again. Same claim, two lifetimes, and the one that never
        expired was standing on the road south.

        Cheap to be wrong about: a re-offered seam that is still shut costs
        one crossing attempt and re-proves itself at the new mark. The old
        enforcement that refused the op outright is already disabled (it
        was refusing the winning move), so nothing here can trap the run.

        Proofs written before this existed are backfilled at the CURRENT
        mark, so none of them re-open on the first boot; they become
        eligible from the next thing that happens, which is the rule
        everything else obeys.
        """
        dirs = self._no_cross.get(region) or set()
        # getattr: _sealed can be reached before the first settle has
        # set a mark, and with no mark the honest answer is the old one
        now = getattr(self, "_mark_now", None)
        if not dirs or now is None:
            return set(dirs)
        marks = self._no_cross_at.setdefault(region, {})
        out = set()
        for d in dirs:
            if d not in marks:
                marks[d] = now
            if marks[d] == now:
                out.add(d)
        return out

    def _frontier_left(self, region) -> list:
        """Exits of `region` never taken — the ONE definition.

        This arithmetic (frontier, minus what has been walked, minus seams
        proven uncrossable) existed in four places and two of them had
        drifted: they subtracted the walked exits and forgot `_no_cross`,
        so `ROUTE_5|1,0 south` — the Saffron guards, proven uncrossable and
        deliberately KEPT in the frontier so one bad proof cannot erode the
        printed map — was advertised to the model every round as a way it
        had never tried. A wall is not an unopened door.
        """
        # A SHUT DOOR IS NOT A TAKEN DOOR. `_untried_exits` has always had
        # the reopening rule — a door that turned you back carries
        # `shut_at`, and once the world mark differs it is worth another
        # press, because what turned you back may not any more. This
        # definition, the one the floor note and the escort read, subtracted
        # EVERY explored key including shut ones, so the two disagreed and
        # this one was permanently wrong.
        # Cost, live: MT_MOON_1F|3,2 tried the ladder at 5,5, could not
        # reach it, recorded it shut — and from then on reported "nothing
        # untried" across 81 arrivals, while that ladder is the only way to
        # the B1F pocket holding 27,3, the way out east. Every one of the
        # mountain's six known regions said finished with three doorways
        # never stood at.
        # Same collapse as this morning's, finishing the job: one definition
        # of untried, and it honours the mark a shut door carries.
        _now = getattr(self, "_mark_now", None)
        done = {k for k, e in self._taken_here(region).items()
                if not ((e or {}).get("shut") and _now is not None
                        and (e or {}).get("shut_at") != _now)}
        done |= set(self._spent_exits(region))
        shut = self._sealed(region)
        return [e for e in (self.frontier.get(region) or [])
                if e not in done and e not in shut]

    def _count_visit(self, region):
        """ONE ARRIVAL, ONE VISIT. Two places counted: note_transition on a
        recorded crossing, and _note on the settle that follows it — so every
        escort hop scored TWICE. That number is shown to the model ("YOU HAVE
        BEEN IN THIS EXACT AREA n TIMES") and it gates the revisit nag, whose
        threshold was therefore half what it reads. The guard against repeat
        counting already existed in _note; it just never covered the other
        writer."""
        if not region or region == getattr(self, "_last_visit_region", None):
            return
        self.visits[region] = self.visits.get(region, 0) + 1
        self._last_visit_region = region

    def _note(self, obs):
        self._mark_now = self._world_mark(obs)
        if (obs or {}).get("mode") == "overworld" and \
                ((obs or {}).get("map") or {}).get("id"):
            self._last_overworld_map = obs["map"]["id"]
            self._note_intra(obs)
        self.note_frontier(obs)
        self.note_region_anchors(obs)
        self.note_sightings(obs)
        self.note_flag_site(obs)
        m = (obs or {}).get("map") or {}
        if m.get("id") and (m.get("connections") or m.get("warps")):
            e = self.atlas.setdefault(m["id"], {})
            if m.get("connections"):
                e["edges"] = m["connections"]
            if m.get("warps"):
                # x,y only. The destination is resolved at render time
                # from what has been WALKED (see _walked_dest); keeping the
                # observed one here just meant the atlas handed the warp
                # table's answer to every escalation prompt.
                e["warps"] = [{"x": w.get("x"), "y": w.get("y")}
                              for w in m["warps"]]
        return obs

    def _note_intra(self, obs):
        """WALKING FROM ONE PART OF A MAP TO ANOTHER IS A FACT TOO.

        The graph only ever learned an edge when the MAP changed, so every
        transition WITHIN a map was thrown away — and ledge-split routes
        are exactly that. Route 9 entered from Cerulean is region |0,8, the
        component that exits east to Route 10 is |50,6, and the run has
        walked between them (down the ledges) more than once. Nothing
        recorded it, so Vermilion -> Celadon read as NO ROUTE for a chain
        the party had physically walked: Route 6, both underground paths,
        Route 5, Cerulean, Route 9, Rock Tunnel, Lavender, all of it
        walked, all of it useless because of one unrecorded step.

        Recorded ONE WAY, which is what was observed: a ledge you dropped
        off is not a ledge you can climb. If the way back is walkable it
        records itself the moment it is walked.
        """
        here = self._where(obs)
        prev = getattr(self, "_intra_prev", None)
        self._intra_prev = here
        if not prev or prev == here or "None" in prev or "None" in here:
            return
        if prev.split("|")[0] != here.split("|")[0]:
            return                       # a map change: note_transition's
        # A FAINT IS NOT A WALK. Blacking out moves the body without the
        # party walking the ground between, and the walk-back is the one
        # place that must not learn a road from it.
        if self._faint_at:
            return
        e = self.explored.setdefault(prev, {})
        k = f"walk:{here}"
        rec = e.setdefault(k, {"n": 0, "to": here, "intra": True})
        rec["n"] = int(rec.get("n") or 0) + 1
        rec["to"] = here
        rec["intra"] = True
        if rec["n"] == 1:
            self.log("intra_walk", frm=prev, to=here)
            self._save_memory()

    MEMORY = RUN / "explored.json"

    def _load_memory(self):
        """Carry the map across runs. Each attempt used to rediscover the
        same mountain from scratch: it explores outward from the entrance,
        exhausts the exits reachable from there, and never gets far enough
        to find the far-side door. Knowledge that survives the process is
        what turns N attempts into progress instead of N repetitions."""
        data, src = self._read_memory()
        if data is None:
            self._blank_memory()
            return
        if src and src.endswith(".prev"):
            print("[memory] the current ledger was unreadable; fell back "
                  "to the last good copy")
        try:
            self.explored = data.get("explored", {})
            self.dead_ends = data.get("dead_ends", {})
            self.visits = data.get("visits", {})
            self.frontier = data.get("frontier", {})
            self.sightings = data.get("sightings", {})
            self.region_anchors = data.get("region_anchors", {}) or {}
            self.searched = data.get("searched", {})
            self.contested = data.get("contested", {})
            self._bad_seam = {tuple(x) for x in data.get("bad_seam", [])
                              if len(x) == 3}
            self._battle_regions = set(data.get("battle_regions") or ())
            # Money-dependent proofs do not survive a restart. "Fully
            # worked" recorded in a shop with an empty wallet is a fact
            # about the WALLET, not the room — it sealed the Pewter Mart
            # door for item:POTION long after the money problem had
            # passed, and the run hunted a clerk in the overworld it could
            # never find there. Within a process the cant-afford ->
            # contested rule keeps this honest; across processes, item
            # proofs and their room seals expire.
            # Every other non-flag key expires with them: travel and status
            # targets minted vacuous per-target proofs before the whitelist
            # in note_searched existed (a room never contains a map, nor
            # "being healthy"), and the rooms they stamped kept re-poisoning
            # the shared "*" ledger at every load. A room genuinely worked
            # re-earns its "*" entry in play; a "*" entry recorded by the
            # current code has no per-target key behind it and survives.
            anyd = self.searched.setdefault("*", {})
            for tgt in [t for t in self.searched
                        if t != "*" and not t.startswith("flag:")]:
                for r in self.searched.pop(tgt, {}):
                    anyd.pop(r, None)
            # service buildings recorded as worked by older runs expire too
            for r in [r for r in anyd if _is_service(r)]:
                anyd.pop(r, None)
            # every surviving entry was recorded under the fully-worked
            # condition, so the union of targets joins the worked rooms
            for tgt, rooms in list(self.searched.items()):
                if tgt != "*":
                    for r in rooms:
                        anyd[r] = True
            self._tried_objs = {r: set(v) for r, v in
                                (data.get("touched") or {}).items()}
            self._touch_bag = data.get("touch_bag") or {}
            self._touch_mark = data.get("touch_mark") or {}
            self._no_cross = {r: set(v) for r, v in
                              (data.get("no_cross") or {}).items()}
            self._no_cross_at = data.get("no_cross_at") or {}
            self._exit_tries = data.get("exit_tries") or {}
            self.flag_sites = data.get("flag_sites") or {}
            # Entries written before the destination was removed still read
            # "4,11->CERULEAN_CAVE_1F (POLICEMAN is standing there)", and the
            # plan author prints this ledger verbatim — so a stale region
            # nobody revisits would keep handing the ROM's answer over for
            # the rest of the run. Strip it on the way in.
            self.shut_doors = {
                r: [_re.sub(r"^([^ ]+)->\S+", r"\1", s) for s in (v or [])]
                for r, v in (data.get("shut_doors") or {}).items()}
            self.hints = data.get("hints") or {}
            self.blockers = data.get("blockers") or {}
            # BACKFILL THE BLOCKERS FROM THE JOURNAL, once: the recorders
            # for a fenced or spoken-at way arrived mid-run, so ways that
            # turned the run back before they existed (Route 9's bush wall,
            # the first Snorlax fence) were nowhere on the list. The run's
            # own history, in the words it was told at the time.
            if not data.get("blockers_backfilled"):
                try:
                    _n0 = len(self.blockers)
                    for _l in (RUN / "executor_log.jsonl").read_text() \
                            .splitlines():
                        if '"escalate_feedback"' not in _l:
                            continue
                        try:
                            _r = json.loads(_l)
                        except ValueError:
                            continue
                        _at = str(_r.get("at") or "")
                        if not _at or "None" in _at:
                            continue
                        for _t in (_r.get("trace") or []):
                            _t = str(_t)
                            _op = _t.split("(", 1)[0]
                            if _op not in ("cross", "use_warp"):
                                continue
                            _m = (_re.match(r"cross\(dir=(\w+)\)", _t)
                                  if _op == "cross" else
                                  _re.match(r"use_warp\(x=(\d+),y=(\d+)\)", _t))
                            if not _m:
                                continue
                            _key = (_m.group(1) if _op == "cross"
                                    else f"{_m.group(1)},{_m.group(2)}")
                            _kind = "seam" if _op == "cross" else "door"
                            _hit = False
                            for tag in ("standing at its edge:",
                                        "Right where the walk stopped:"):
                                if "FAILED" in _t and tag in _t:
                                    clause = _t.split(tag, 1)[1].strip() \
                                        .split(".")[0][:160]
                                    self._note_blocker(
                                        _at, _key, _kind,
                                        f"the walk was fenced — {clause}")
                                    _hit = True
                                    break
                            if not _hit and (
                                    "GHOST appeared" in _t
                                    or "did not change, but it SPOKE" in _t):
                                said = (_t.split("it said: ", 1)[1]
                                        .strip()[:160]
                                        if "it said: " in _t else "")
                                self._note_blocker(
                                    _at, _key, _kind,
                                    said or "it spoke and did not open")
                    # a backfilled way that has since OPENED is no blocker:
                    # a walked edge on the same key clears it
                    for bk, b in list(self.blockers.items()):
                        e = (self.explored.get(b.get("where")) or {}) \
                            .get(b.get("key")) or {}
                        if e.get("to") and not e.get("shut"):
                            b["cleared"] = True
                            b["cleared_how"] = "walked since"
                    if len(self.blockers) > _n0:
                        print(f"[memory] blockers backfilled: "
                              f"{len(self.blockers) - _n0} from the journal")
                except OSError:
                    pass
            self._blockers_backfilled = True
            # the FIGHT probe against the tower's ghost is once per RUN, not
            # per attempt: its answer is already written on the blocker
            self._ghost_probed = any(
                "you pressed FIGHT" in (b.get("what") or "")
                for b in self.blockers.values() if isinstance(b, dict))
            # WHEN each line was heard: the count of event flags fired at
            # the time. A sentence re-served without its date reads as a
            # standing instruction — "Say hi to PROF.OAK for me!" was said
            # before the parcel was delivered and kept sending the run to
            # Oak for hours after. Lines recorded before this existed have
            # no stamp and are shown undated.
            self.hints_at = data.get("hints_at") or {}
            self._offered = data.get("offered") or {}
            self._cut_bushes = data.get("cut_bushes") or {}
            self._shelves = data.get("shelves") or {}
            # MEMORY THAT OUTLIVES THE ATTEMPT. The outcome ledger and the
            # plan history were per process, and every attempt is a new
            # process — so each attempt re-supposed the same thing from
            # zero ("Fresh Water at the Vermilion mart", the thirsty guard)
            # while the rewrite alone saw the counts. Keyed by TARGET, so
            # they survive a rewrite that renames the step.
            self._outcomes = data.get("outcomes") or {}
            self._plan_hist = data.get("plan_hist") or {}
            if not self._shelves:
                # BACKFILL ONCE from this world's journal: the counter's
                # "this mart sells: ..." replies are already recorded.
                try:
                    import re as _re3
                    _pat3 = _re3.compile(r"this mart sells: ([A-Z0-9_, ]+)")
                    for _l in (RUN / "executor_log.jsonl").read_text() \
                            .splitlines():
                        if "this mart sells" not in _l:
                            continue
                        try:
                            _r3 = json.loads(_l)
                        except ValueError:
                            continue
                        _at3 = str(_r3.get("at") or "").split("|")[0]
                        for _t in (_r3.get("trace") or []):
                            _m3 = _pat3.search(_t)
                            if _m3 and _at3 and _at3.endswith("MART"):
                                self._shelves[_at3] = [
                                    x.strip() for x in _m3.group(1).split(",")
                                    if x.strip()]
                    if self._shelves:
                        print(f"[memory] shelves backfilled for "
                              f"{len(self._shelves)} mart(s) from the journal")
                except OSError:
                    pass
            # ...and drop any edge already filed that contradicts a seam
            # proof on the same region (the false ROUTE_4|4,4 east edge in
            # run 12), so the live world heals at the next start without a
            # hand edit under a running executor.
            _bad = set()
            for _r, _dirs in list((self._no_cross or {}).items()):
                for _d in list(_dirs or ()):
                    if _d in (self.explored.get(_r) or {}):
                        _bad.add((_r, _d))
            # The proof itself can have been revoked BY the false edge (the
            # load rule below trusts a walked edge over a stored proof), so
            # read the journal's own BFS verdicts too: "cross(dir=east):
            # FAILED — the east seam of ROUTE_4 cannot be walked to from
            # here" recorded at a region is geometry, not weather.
            try:
                import re as _re2
                _pat = _re2.compile(r"cross\(dir=(\w+)\): FAILED — the \1 "
                                    r"seam of (\w+) .*cannot be walked to")
                for _l in (RUN / "executor_log.jsonl").read_text().splitlines():
                    if '"escalate_feedback"' not in _l or "seam of" not in _l:
                        continue
                    try:
                        _r0 = json.loads(_l)
                    except ValueError:
                        continue
                    _at = str(_r0.get("at") or "")
                    for _t in (_r0.get("trace") or []):
                        _m = _pat.search(_t)
                        if _m and _at.split("|")[0] == _m.group(2) \
                                and _m.group(1) in (self.explored.get(_at)
                                                    or {}):
                            _bad.add((_at, _m.group(1)))
            except OSError:
                pass
            for _r, _d in sorted(_bad):
                _e = (self.explored.get(_r) or {}).get(_d) or {}
                # only a CROSSING filed once — a shut record (to == self)
                # is the failure itself, and a seam crossed twice or more
                # from here is a road something merely stood in one day
                if _e.get("to") in (None, _r) or int(_e.get("n") or 0) > 1:
                    continue
                self.explored[_r].pop(_d, None)
                print(f"[memory] dropped {_r} --{_d}--> {_e.get('to')}: the "
                      f"{_d} seam is proven unwalkable from that region, so "
                      f"the crossing was filed under the wrong label")
            if not self._offered:
                # BACKFILL ONCE from this world's journal: the tally is new
                # and the encounters are not — Route 24's 87 are already
                # written down as battle_start records. Map is the last
                # escalate_feedback's `at` before each battle, which is
                # how the analysis that found the gap read them.
                try:
                    _cur = None
                    for _l in (RUN / "executor_log.jsonl").read_text() \
                            .splitlines():
                        if '"battle_start"' not in _l and \
                                '"escalate_feedback"' not in _l:
                            continue
                        try:
                            _r = json.loads(_l)
                        except ValueError:
                            continue
                        if _r.get("kind") == "escalate_feedback":
                            _cur = str(_r.get("at") or "").split("|")[0] or None
                        elif _r.get("kind") == "battle_start" and _cur \
                                and _r.get("policy") in ("catch", "traversal",
                                                         "fight"):
                            _sp = str(_r.get("foe") or "").split(" L")[0]
                            if _sp and _sp != "None":
                                bk = self._offered.setdefault(_cur, {})
                                bk[_sp] = bk.get(_sp, 0) + 1
                    if self._offered:
                        print(f"[memory] encounter tally backfilled for "
                              f"{len(self._offered)} map(s) from the journal")
                except OSError:
                    pass
            # SCRUB THE OLD ITEM NAMES (see _looks_like_item_name): the
            # sightings, touched and touch-mark ledgers, and the speaker of
            # a hint line. Dropped, not renamed — the position that would
            # make the handle is not stored, and the next visit re-sights
            # them as ITEM_x_y.
            _dropped = 0
            for _r, _names in list((self.sightings or {}).items()):
                keep = [n for n in (_names or []) if not _looks_like_item_name(n)]
                _dropped += len(_names or []) - len(keep)
                self.sightings[_r] = keep
            for _r, _names in list((self._tried_objs or {}).items()):
                keep = {n for n in (_names or set()) if not _looks_like_item_name(n)}
                _dropped += len(_names or ()) - len(keep)
                self._tried_objs[_r] = keep
            for _r, _marks in list((self._touch_mark or {}).items()):
                for _n in [n for n in (_marks or {}) if _looks_like_item_name(n)]:
                    _marks.pop(_n, None)
                    _dropped += 1
            for _r, _lines in list((self.hints or {}).items()):
                fixed = []
                for _l in (_lines or []):
                    who, sep, rest = str(_l).partition(": ")
                    if sep and _looks_like_item_name(who):
                        _dropped += 1
                        fixed.append(f"an item: {rest}")
                    else:
                        fixed.append(_l)
                self.hints[_r] = fixed
            if _dropped:
                print(f"[memory] {_dropped} item name(s) scrubbed from the "
                      f"ledgers — contents are not on the screen")
            self.map_doors = {k: set(v) for k, v
                              in (data.get("map_doors") or {}).items()}
            # Wipe counts persist: each campaign attempt is a fresh process
            # and the badge gate is one-strike, so the in-memory counter
            # reset before ever reaching 2 — the TOO-WEAK note was aimed at
            # Misty and structurally could not fire on her.
            self._blackouts = data.get("blackouts") or {}
            self._blackout_lead = data.get("blackout_lead") or {}
            # Waypoints COMPLETED this campaign stay completed across
            # attempt resumes: a resumed journey-plan re-litigated its
            # first waypoint and marched the party from the captain's
            # doorstep all the way back to Cerulean.
            # PURGE MIRAGE REGIONS: a frontier entry with no walked edges
            # and no counted visits is a label from a dead labeling era
            # (the hop-free fragments); its phantom "untried exits" pull
            # the reroute forever (ROUTE_25|12,2 was elected six times).
            for _r in [r for r in list(self.frontier)
                       if not (self.explored.get(r)
                               or self.visits.get(r))]:
                del self.frontier[_r]
            # REPAIR ROADS AN OLD PROOF STRUCK OUT. Ledgers written before
            # the rule changed still hide printed connections (ROUTE_9
            # east — the only road to Rock Tunnel and everything beyond —
            # was missing while 28 western regions held untried exits), and
            # the entry can only be rewritten by STANDING there, which the
            # run will never choose to do while the exit is hidden. Repair
            # at load so the fix is not hostage to the bug.
            # A ROAD YOU HAVE WALKED IS NOT A ROAD YOU CANNOT WALK. no_cross
            # is a CONCLUSION ("the cross op searched the whole seam and
            # failed"); the walked edge is an OBSERVATION. When they
            # disagree the observation wins. Cerulean had both "east" and
            # "south" filed as uncrossable while the ledger held south ->
            # ROUTE_5 taken 14x with 70 visits on the far side — so the
            # exits list offered only north and west, and the run could not
            # be told to go to the DAY CARE because the way there was not
            # among the ways it was shown. It was never refusing; it was
            # never asked.
            for _r, _dirs in list(self._no_cross.items()):
                _walked = self.explored.get(_r) or {}
                _drop = set()
                for _d in list(_dirs):
                    _e = _walked.get(_d) or {}
                    _to = _e.get("to")
                    if (_to and _to != _r and not _e.get("shut")
                            and (self.visits.get(_to) or 0) > 0):
                        _drop.add(_d)
                if _drop:
                    self._no_cross[_r] = set(_dirs) - _drop
                    print(f"[memory] {_r}: crossed {','.join(sorted(_drop))} "
                          f"before, so it is not uncrossable")
            for _r, _ex in list(self.frontier.items()):
                _real = MAP_EDGES.get(_r.split("|")[0]) or {}
                _add = [d for d in _real
                        if d in (self._no_cross.get(_r) or set())
                        and d not in _ex]
                if _add:
                    self.frontier[_r] = sorted(set(list(_ex) + _add))
                    # NOT self.log: _load_memory runs before logf opens
                    print(f"[memory] restored printed road(s) "
                          f"{','.join(_add)} in {_r}")
            self._rebuild_area_aliases()
            self._prune_dead_ends()
            # LAST, AND IT MAY NOT COST THE LEDGER. Placing buildings on
            # roads is a convenience; the ledger is the run's memory of a
            # whole day's walking. When this sat mid-load and raised, it
            # took every section after it down with it.
            try:
                self._learn_doorsteps()
            except Exception as e:
                self._doorsteps_learned = []
                print(f"[warn] doorstep placement skipped: {e}")
            if self._doorsteps_learned:
                print(f"[memory] placed {len(self._doorsteps_learned)} "
                      f"building(s) on the road walked out onto: "
                      + ", ".join(f"{i}->{r}"
                                  for i, r in self._doorsteps_learned[:6]))
            edges = sum(len(v) for v in self.explored.values())
            if edges:
                print(f"[memory] {len(self.explored)} areas, {edges} known "
                      f"exits from previous runs")
        except (OSError, ValueError) as e:
            # NOT SILENT. This used to reset every structure to {} without
            # a word, so a corrupt ledger and a genuinely fresh run looked
            # identical from the outside — the run simply began re-walking
            # a mountain it had already mapped, and nothing said why.
            print(f"[memory] !!! the ledger parsed but could not be loaded "
                  f"({e.__class__.__name__}: {e}). Starting EMPTY: "
                  f"everything walked so far is being rediscovered.")
            self._blank_memory()

    def _read_memory(self):
        """The ledger, or the last good copy of it. Returns (data, source).

        (None, None) means there was nothing to read, which on a first run
        is correct and silent — but a file that EXISTS and will not parse
        is a different event entirely, and it says so."""
        tried = []
        for path in (self.MEMORY, self.MEMORY.with_suffix(".json.prev")):
            if not path.exists():
                continue
            try:
                return json.loads(path.read_text()), path.name
            except (OSError, ValueError) as e:
                tried.append(f"{path.name} ({e.__class__.__name__})")
        if tried:
            print("[memory] !!! COULD NOT READ THE WALKED MAP: "
                  + ", ".join(tried) + ". Starting with an EMPTY ledger — "
                  "every area, exit and proof from previous runs is gone "
                  "and is being rediscovered from scratch.")
        return None, None

    def _blank_memory(self):
        self.explored, self.dead_ends = {}, {}
        self.visits, self.frontier, self.sightings = {}, {}, {}
        self.region_anchors = {}
        self.searched = {}
        self.contested = {}
        self._battle_regions = set()
        self._touch_mark = {}
        self._no_cross_at = {}
        self._exit_tries = {}

    def _save_memory(self):
        """TMP + RENAME, AND KEEP THE LAST GOOD ONE.

        This is the run's whole walked map — every region, every exit, every
        proof — and it was being written straight over itself about
        twenty-five times a round. `write_text` truncates first, so a kill
        landing in that window leaves a half-written file; `_load_memory`
        then fails to parse it and starts the next process with nothing,
        which reads as "a fresh run" and quietly re-walks a day's mountain.
        The pattern is already in this repo twice (bridge.py:78 writes cmd
        via tmp+rename, shim.lua does the same for obs), it just never
        reached the one file that cannot be reconstructed.
        """
        try:
            payload = json.dumps(
                {"explored": self.explored, "dead_ends": self.dead_ends,
                 "visits": self.visits, "frontier": self.frontier,
                 "sightings": self.sightings, "searched": self.searched,
                 "touch_bag": self._touch_bag,
                 "touch_mark": self._touch_mark,
                 "region_anchors": self.region_anchors,
                 "contested": self.contested,
                 "bad_seam": sorted(list(x) for x in
                                    getattr(self, "_bad_seam", set())),
                 # A TRAINER FIGHT IN A ROOM OUTLIVES THE PROCESS, same
                 # as `contested` right above it. Without this, a gym
                 # the party lost in stopped being exempt from the
                 # re-entry refusal the moment the attempt restarted —
                 # so the resumed run was told to leave the room it had
                 # come back to fight in.
                 "battle_regions": sorted(self._battle_regions),
                 # touched outlives the process so "sighted but never
                 # touched" stays computable across attempts — the Mt Moon
                 # fossils are the door east, and every restart forgot who
                 # had already been talked to
                 "touched": {r: sorted(s)
                             for r, s in self._tried_objs.items()},
                 "no_cross": {r: sorted(s)
                              for r, s in self._no_cross.items()},
                 "no_cross_at": self._no_cross_at,
                 "exit_tries": self._exit_tries,
                 "flag_sites": self.flag_sites,
                 "shut_doors": self.shut_doors,
                 "hints": self.hints,
                 "blockers": self.blockers,
                 "blockers_backfilled": bool(getattr(
                     self, "_blockers_backfilled", False)),
                 "hints_at": getattr(self, "hints_at", {}),
                 "offered": getattr(self, "_offered", {}),
                 "cut_bushes": getattr(self, "_cut_bushes", {}),
                 "shelves": getattr(self, "_shelves", {}),
                 "outcomes": getattr(self, "_outcomes", {}),
                 "plan_hist": getattr(self, "_plan_hist", {}),
                 "blackouts": self._blackouts,
                 "blackout_lead": self._blackout_lead,
                 "map_doors": {k: sorted(v)
                               for k, v in (self.map_doors or {}).items()}},
                indent=1)
            tmp = self.MEMORY.with_suffix(".json.tmp")
            tmp.write_text(payload)
            # the previous good file becomes the fallback, and only once the
            # new one is fully on disk
            if self.MEMORY.exists():
                try:
                    self.MEMORY.replace(self.MEMORY.with_suffix(".json.prev"))
                except OSError:
                    pass
            tmp.replace(self.MEMORY)
        except OSError:
            pass

    def _prune_dead_ends(self):
        """Drop proofs the MAP now contradicts.

        A dead-end proof is local — "I could not walk to it from here" — but
        it is used to refuse exits, so a destination that needs two legs got
        branded unreachable. ROUTE_2's south half accumulated
        map:PEWTER_GYM x7 and even map:VIRIDIAN_FOREST, whose gate is right
        there, and the run then refused its way out of Viridian. If a walked
        path exists from the region to the target map, the proof is false and
        goes. Flag/item proofs are left alone: the graph cannot speak to
        those.
        """
        dropped = []
        for tgt in list(self.dead_ends):
            if not tgt.startswith("map:"):
                continue
            want = tgt.split(":", 1)[1]
            dests = [r for r in set(list(self.explored) + list(self.visits))
                     if r.split("|")[0] == want]
            for region in list(self.dead_ends[tgt]):
                if any(self._route(region, d) for d in dests):
                    del self.dead_ends[tgt][region]
                    dropped.append(f"{tgt}@{region}")
            if not self.dead_ends[tgt]:
                del self.dead_ends[tgt]
        if dropped:
            print(f"[memory] dropped {len(dropped)} dead-end proof(s) the map "
                  f"contradicts: {', '.join(dropped[:4])}"
                  + (" ..." if len(dropped) > 4 else ""))
            self._save_memory()

    def _rebuild_area_aliases(self):
        """Group enclosed areas by their EXIT SIGNATURE. Two codes with the
        same exits on the same map are the same room seen before and after a
        blocker moved (the fossil), so a goal naming either should hold."""
        # Equal exit SETS is too strict: taking the fossil opened a corridor,
        # so the room went from exits {21,17} to {21,17, 5,7}. Exit keys are
        # tile coordinates on that map, so two areas that both reach the same
        # warp tile ARE the same place — share one exit, same room.
        # WARP TILES ONLY. A map-EDGE direction is not a tile: the edge
        # spans every pocket that touches that boundary, so Route 4's
        # 'south' glued the west stub to the east region and the router
        # then crossed 'east' from the stub — the walk-back replanned into
        # the same wall four times and the KNOWN-WAY advice line fed the
        # model the same impossible cross for a whole escalation.
        by_map: dict = {}
        for region, exits in (self.frontier or {}).items():
            tiles = {k for k in exits if "," in k}
            if not tiles:
                continue
            by_map.setdefault(region.split("|")[0], []).append(
                (region, tiles))
        AREA_ALIASES.clear()
        for regions in by_map.values():
            for i, (ra, ea) in enumerate(regions):
                for rb, eb in regions[i + 1:]:
                    if ea & eb:
                        AREA_ALIASES.setdefault(ra, set()).add(rb)
                        AREA_ALIASES.setdefault(rb, set()).add(ra)

    def note_flag_site(self, obs):
        """Where an event actually fired.

        A plan can order a flag subgoal before the subgoal that reaches the
        place it happens — asking for the bottom-floor fight while standing
        a floor above it, unsatisfiable where it stands. The sightings
        ledger says where a THING was seen; nothing said where an EVENT
        occurred. This is that, earned the only honest way: watch which
        flags are new and record the area the party was standing in.
        """
        flags = set((obs or {}).get("flags") or [])
        if not flags:
            return
        if self._known_flags is None:      # first observation: baseline only
            self._known_flags = flags
            return
        fresh = flags - self._known_flags
        self._known_flags = flags
        if not fresh:
            return
        here = self._where(obs)
        if "None" in here:
            return
        for f in fresh:
            if self.flag_sites.get(f) == here:
                continue
            self.flag_sites[f] = here
            self.log("flag_fired", flag=f, region=here)
        self._save_memory()

    def note_region_anchors(self, obs):
        """Remember what this world calls its places, across restarts.

        A region name is minted by standing somewhere unnamed, so without
        this the run re-learns the map's identity every relaunch: it walked
        out of the trashed house once and found that the far side of
        Cerulean is a different place, and that discovery died with the
        process. One cell per name is enough — the shim re-spreads it over
        the component on load.
        """
        m = (obs or {}).get("map") or {}
        anchors = m.get("region_anchors")
        mid = m.get("id")
        if not (anchors and mid):
            return
        store = self.region_anchors.setdefault(mid, {})
        added = {c: n for c, n in anchors.items() if store.get(c) != n}
        if added:
            store.update(added)
            self.log("region_anchors", map=mid, added=added)
            self._save_memory()

    def note_sightings(self, obs):
        """Which named things were SEEN in this region.

        The graph knows the ladder from 1F(5,5) leads to B1F|4,4 and on to
        B2F|20,5, but nothing said B2F|20,5 is where the super nerd and both
        fossils are — so a plan could not aim at it and the descent landed
        wherever chance took it. Sightings are the model's own observations,
        so re-authoring may use them."""
        m = (obs or {}).get("map") or {}
        here = self._where(obs)
        if "None" in here:
            return
        # only what is REACHABLE from here. Object lists are map-wide, so
        # B2F|23,21 "sees" the fossils that actually sit in B2F|20,5 behind
        # a wall — recording mere visibility would aim a rewrite at the
        # wrong part of the map, which is the exact mistake this data is
        # meant to prevent.
        names = sorted({o.get("name") for o in (m.get("objects") or [])
                        if o.get("name") and o.get("reachable")})
        if not names:
            return
        was = set(self.sightings.get(here) or [])
        # A THING THAT IS GONE IS NOT STILL SEEN. Sightings only ever grew,
        # so a Snorlax woken and walked off, an item picked up, a person
        # hidden by a script stayed on the record for ever — and the ledger
        # kept offering the run a thing it could not find, which reads as
        # the world lying about itself. This map is on screen: anything
        # recorded HERE that the observation no longer lists is gone. Only
        # names the ledger itself minted (never the harness's ITEM_x_y,
        # which are re-minted per position) and only when the observation
        # is real.
        live = {o.get("name") for o in (m.get("objects") or []) if o.get("name")}
        gone = {n for n in was
                if n not in live and not str(n).startswith("ITEM_")
                and not str(n).startswith("CUT_TREE")}
        if gone:
            self.log("sighting_gone", area=here, names=sorted(gone))
        keep = (was - gone) | set(names)
        if keep != was:
            self.sightings[here] = sorted(keep)
            self._save_memory()

    def note_frontier(self, obs):
        self._last_obs_dormant = ((obs or {}).get("map") or {}).get("dormant")
        # what is in the bag that the game will not let you throw away —
        # published by the shim, which reads the engine's own keyItem flag
        self._last_key_items = list((obs or {}).get("key_items") or [])
        """Every exit visible from where we stand — the inventory that makes
        'all ways out are dead' a justified conclusion rather than a guess."""
        here = self._where(obs)
        if "None" in here:
            return
        # EVERY DOORWAY THIS MAP HAS, remembered per MAP not per region.
        # The frontier is per region and only ever held doorways reachable
        # from where the run stood, so a floor whose far pocket was never
        # entered reported "frontier == taken" in every region it knew —
        # nothing left, in a cave with the way out still in it.
        _m = (obs or {}).get("map") or {}
        _mid = _m.get("id")
        if _mid:
            _all = {f"{w.get('x')},{w.get('y')}"
                    for w in (_m.get("warps") or [])}
            if _all:
                self.map_doors[_mid] = set(self.map_doors.get(_mid, ())) | _all
        # A visit is a VISIT, counted on arrival — not only on a recorded
        # transition. Regions whose transitions landed under other labels
        # (the hop-free relabeling) collected zero visits however often
        # the escort delivered the party there, so they ranked "freshest"
        # forever and the reroute elected the same mirage six times.
        self._count_visit(here)
        m = (obs or {}).get("map") or {}
        # WALKABLE ONES ONLY. Recording doorways pathfinding cannot reach
        # made every region holding one look permanently unexplored, so the
        # walk-back kept electing regions whose only "fresh" exit was a
        # ladder behind a trainer. That a blocked doorway EXISTS is told to
        # the model separately (DOORWAYS ON THIS MAP...) and computed from
        # the observation, not from this ledger.
        keys = [f"{w.get('x')},{w.get('y')}" for w in (m.get("warps") or [])
                if w.get("reachable")]
        keys += list((m.get("connections") or {}).keys())
        # DOORS THAT EXIST BUT CANNOT BE WALKED TO stay out of the frontier
        # (you cannot take them now) and are recorded separately, because
        # the PLAN AUTHOR reads this ledger and had no way to learn they
        # existed. Blocked out of Cerulean, it authored a 24-leg march back
        # to Pallet Town and round again — a brute-force search for a way
        # on, while the way on was a door with a policeman standing under
        # it, four tiles from where it was standing.
        # WHERE IT GOES IS NOT OURS TO SAY. That a doorway is there, and that
        # somebody is standing at it, are both on screen. Its destination is
        # not: it comes out of the warp table, the game's own index of every
        # door, and a door this run has never walked through has never shown
        # anyone its far side. "(4,11)->CERULEAN_CAVE_1F" is the ROM talking,
        # and it is pointing — the one thing the rule forbids. Report the
        # doorway; let walking through it be how the far side is learned.
        shut = sorted(f"{k} ({who} is standing there)"
                      for k, _dest, who in self._unopened_doors(obs))
        if shut:
            if self.shut_doors.get(here) != shut:
                self.shut_doors[here] = shut
                self._save_memory()
        elif self.shut_doors.pop(here, None) is not None:
            self._save_memory()
        # A seam proof HIDES the exit, but only where the town map says no
        # connection exists. A proof is about the terrain under the party at
        # one instant — a wanderer in the gap, a ledge, a bush not yet cut —
        # and Route 9's east edge, the ONLY road to Rock Tunnel and the whole
        # eastern half of Kanto, was struck from the frontier by one such
        # proof. Every exploration mechanism reads the frontier, so the run
        # had literally nothing east to elect and drifted west for hours.
        # Where the printed map says a connection IS there, the exit stays
        # listed (the edge line already marks it PROVEN uncrossable from
        # here, which is advice the model can weigh) — proofs may discourage
        # a direction, never delete a road the map says exists.
        _nc = self._sealed(here)
        _real = MAP_EDGES.get(here.split("|")[0]) or {}
        keys = [k for k in keys if k not in _nc or k in _real]
        if keys:
            fresh = sorted(set(keys))
            if self.frontier.get(here) != fresh:
                # persist on CHANGE, not only on transitions: the inventory
                # was accumulating in memory and the file stayed empty until
                # the first map change, so watching it showed nothing for a
                # while after the run started
                self.frontier[here] = fresh
                self._rebuild_area_aliases()
                self._save_memory()

    def dead_for(self, target: str, region: str, _seen=None, depth=4) -> int:
        """Is this region hopeless for that target — directly, or because
        every exit from it leads somewhere hopeless? Computed on demand and
        never stored: taking a fossil or shifting a boulder can open a way
        that was shut, and a cached inference outlives the wall it rests on."""
        direct = (self.dead_ends.get(target, {}) or {}).get(region, 0)
        if direct:
            return direct
        if depth <= 0:
            return 0
        _seen = _seen or set()
        if region in _seen:
            return 0
        exits = self.frontier.get(region)
        taken = self.explored.get(region, {})
        if not exits or any(k not in taken for k in exits):
            return 0          # untried ways out remain: not proven hopeless
        _seen = _seen | {region}
        for k in exits:
            dest = taken[k]["to"]
            if dest == region:
                continue
            if not self.dead_for(target, dest, _seen, depth - 1):
                return 0      # one live route out is enough
        return 1              # every way out leads somewhere hopeless

    SPATIAL = ("map:", "flag:", "item:")

    def _worked_for(self, target: str) -> dict:
        """Rooms with nothing left to find, as seen by this goal. The
        room-level "*" facts serve every goal EXCEPT the classes a fully
        worked room can still SATISFY — a mart's counter still sells and a
        Center still heals however many times the party has been inside —
        which consult only their own per-target proofs."""
        rooms = dict(self.searched.get(target) or {}
                     if (target or "").startswith(("item:", "party_healthy"))
                     else self.searched.get("*") or {})
        # A ROOM ON AN UNFINISHED FLOOR IS NOT FINISHED EITHER. "Fully
        # worked" counted a REGION's exits while the line above it counts a
        # MAP's doorways, so Mt Moon B1F|4,4 was announced as having ways
        # never taken AND as having nothing left to find, in the same
        # breath — and the second reading is what stopped the run going
        # back down to the fossils. Same test both places.
        for r in list(rooms):
            mid = r.split("|")[0]
            walked = set()
            for r2, ex2 in (self.explored or {}).items():
                if r2.split("|")[0] != mid:
                    continue
                walked |= {k for k, e in ex2.items()
                           if not (e or {}).get("shut")
                           and (e or {}).get("to") != r2}
            if set(self.map_doors.get(mid, ())) - walked:
                del rooms[r]
        return rooms

    def _map_has_unopened_doors(self, mid: str) -> bool:
        """Does this MAP still have a doorway nobody has walked through?

        Same arithmetic the fully-worked test does, lifted so the revisit
        refusal can ask it too. map_doors holds every warp SEEN on a map,
        reachable or not, keyed by map rather than by area block — so a
        ladder visible across a chasm counts, which is the whole point: a
        floor you cannot walk across is not a floor you have finished.
        """
        if not mid:
            return False
        walked = set()
        for r2, ex2 in (self.explored or {}).items():
            if r2.split("|")[0] != mid:
                continue
            walked |= {k for k, e in ex2.items()
                       if not (e or {}).get("shut")
                       and (e or {}).get("to") != r2}
        return bool(set(self.map_doors.get(mid, ())) - walked)

    @staticmethod
    def _untaken(cmap: dict, tried: set) -> set:
        """The touched set, minus items STILL LYING ON THE MAP.

        Picking an item up removes it from the world, so an item ball you
        can still see was not taken however the ledger reads — and the
        ledger can be wrong: a take-prompt answered with no, or declined by
        default, marked the Mt Moon fossils touched while both sat there in
        plain sight. That silenced the untouched-things line, so nothing
        ever prompted a retry, and the corridor east stayed gated on a
        question nobody answered. Presence on screen outranks the ledger.
        """
        present = {o.get("name") for o in (cmap.get("objects") or [])
                   if o.get("kind") == "item" and o.get("name")}
        return tried - present if present else tried

    def _key_items(self) -> list:
        return list(self._last_key_items)

    # How many times one thing may be re-offered across a whole run. A
    # sign says the same sentence for ever, and without a cap it would be
    # re-offered after every flag that fires anywhere. Three is enough for
    # anyone whose line actually changes and cheap enough to be wrong about.
    TOUCH_REOFFERS = 3

    def _mark_touch(self, region: str, name: str, obs):
        """Remember WHAT THE WORLD WAS when this thing was pressed."""
        if not (region and name) or "None" in region:
            return
        self._touch_mark.setdefault(region, {})[name] = {
            "then": self._world_mark(obs), "n": 0, "at": None}

    def _worth_another_word(self, region: str, obs, backfill=True) -> list:
        """Things pressed HERE, back when the world was something else.

        THE TOWN MAP HAS NEVER BEEN OBTAINED IN ANY RUN, and this is why.
        On leg 1, during pick_starter, the model pressed BLUESHOUSE_DAISY1
        and got "AAAAAAA is out at Grandpa's lab" — which the recomp's own
        script shows is the branch taken when EVENT_GOT_STARTER is FALSE.
        It talked to her minutes before picking the starter that unlocks
        her gift. `_tried_objs` is a LIFETIME ledger, so from that press
        onward she never appeared in "things you have not touched" again,
        and the map has been sitting in her house for every run since.

        This does not un-say the touch. The run HAS spoken to her, and
        saying otherwise would be a lie — `_stamp_touch` already refused to
        do that, and fourteen other readers depend on the lifetime ledger.
        What is added is the one fact that makes "pressed once" weaker than
        it looks: it was pressed when you were carrying different things,
        and this game's people say different things then. WHICH of them is
        worth a second word is the model's call; the harness does not know
        and must not pretend to.

        Bounded twice over: only while the world mark actually differs, and
        only TOUCH_REOFFERS times per thing per run.
        """
        now = self._world_mark(obs)
        if not backfill:
            return sorted(
                n for n, rec in (self._touch_mark.get(region) or {}).items()
                if isinstance(rec, dict) and rec.get("then") != now
                and (rec.get("n") or 0) < self.TOUCH_REOFFERS)
        # EVERYTHING ALREADY IN THE LIFETIME LEDGER JOINS FROM HERE. The
        # marks are new and the touches are not: 170 things had been pressed
        # before this existed, Daisy among them, and without a backfill they
        # would stay retired for ever — which is the bug. Backfilled at the
        # CURRENT mark rather than an empty one, so nothing floods back the
        # instant this ships; they become eligible from the next thing that
        # happens, which is the rule everything else obeys.
        marks = self._touch_mark.setdefault(region, {})
        for name in (self._tried_objs.get(region) or ()):
            if name and name not in marks:
                marks[name] = {"then": now, "n": 0, "at": None}
        if not marks:
            return []
        out = []
        for name, rec in marks.items():
            if not isinstance(rec, dict):
                continue
            if rec.get("then") == now:
                continue                      # nothing has happened since
            if (rec.get("n") or 0) >= self.TOUCH_REOFFERS:
                continue                      # it has had its chances
            out.append(name)
        return sorted(out)

    def _note_reoffer(self, region: str, names, obs) -> bool:
        """Spend a re-offer, so a thing that never changes goes quiet.

        COUNTED PER WORLD STATE, NOT PER RENDER. exploration_text runs once
        per escalation round, and a subgoal stuck in one room renders it
        over and over — counting renders would burn all three chances
        before the model had acted on the first. An offer is only spent
        when the world has moved since the last time this thing was
        offered, which is the same measure the offer itself is made on.
        """
        marks = self._touch_mark.get(region) or {}
        now = self._world_mark(obs)
        spent = False
        for n in names:
            rec = marks.get(n)
            if isinstance(rec, dict) and rec.get("at") != now:
                rec["at"] = now
                rec["n"] = (rec.get("n") or 0) + 1
                spent = True
        return spent

    def _stamp_touch(self, region: str):
        """Record WHAT WAS BEING CARRIED when this area was last pressed.

        `_tried_objs` is a lifetime ledger, so a person spoken to once is
        filtered out of "people here you have never spoken to" forever.
        The BIKE_SHOP clerk went that way: talked to before the voucher
        existed, invisible ever since, with the voucher still in the bag
        (user, twice).

        The ledger is NOT invalidated and the run is never told it has not
        spoken to someone it has — that would be a lie, and fourteen
        places read this ledger besides. All that is kept is a number, so
        the room can say something true instead: everything here has been
        pressed, and that was when you were carrying these.
        """
        if region and "None" not in region:
            self._touch_bag[region] = self._key_items()

    def note_searched(self, target: str, region: str):
        """This area has been fully worked: every exit taken, everything
        reachable touched. Distinct from a dead end — it stops the room
        being SEARCHED again without stopping the run PASSING through."""
        if not region or "None" in region or not target:
            return
        # A SERVICE is never exhausted. "Fully worked" means nothing is left
        # to FIND here, which is trivially true of a Pokemon Center or a
        # mart — and useless, because their value is a nurse and a counter
        # that keep working however many times you come back. Marked, they
        # read as "done with this place" to every consumer of the ledger,
        # which is why the door seal needed item:/party_healthy patches
        # downstream. Do not make the claim in the first place.
        if _is_service(region):
            return
        # A room where a FIGHT ran for this goal is not exhausted — losing
        # to the Mt Moon nerd marked his room worked, and the refusal then
        # blocked the ladder leading back to him. A lost fight is unfinished
        # business, not an emptied room.
        if self.contested.get(target, {}).get(region):
            return
        # A ROOM THAT CAN STILL CHANGE IS NOT FINISHED. obs.map.dormant
        # counts objects the map defines but has not shown yet — a script
        # in here has more to reveal. Bill's house certified as worked with
        # his errand unstarted, which took the one room that opens Cerulean
        # out of the search entirely (user spotted it).
        if (self._last_obs_dormant or 0) > 0:
            return
        # FULLY WORKED (every exit taken, every reachable object touched) is
        # a fact about the ROOM, not the goal, so it always lands in "*" —
        # the ledger door-refusals and route advice consult. Keying it only
        # by target fragmented the ledger: B2F's dead-end rooms were marked
        # under the nerd flag, so a later subgoal aiming at map:MT_MOON_B2F
        # saw them as untouched and walked straight back in.
        anyd = self.searched.setdefault("*", {})
        fresh = region not in anyd
        anyd[region] = True
        # The per-target claim exists only for things that can BE somewhere.
        # "The target is not in this room" is trivially true of every room
        # when the target is a map, a waypoint, or a party condition, so
        # those proofs carried no information — MT_MOON_1F was recorded as
        # searched for map:ROUTE_4 while two of its doors open onto Route 4,
        # and player_at waypoints slipped the old map:/area: prefix check by
        # arriving as subgoal: keys.
        if target.startswith(("flag:", "item:")):
            d = self.searched.setdefault(target, {})
            fresh = fresh or region not in d
            d[region] = True
        if fresh:
            self.log("room_searched", target=target, region=region)
            self._save_memory()

    def note_dead_end(self, sg_id: str, region: str,
                      shop_proof: bool = False):
        if not sg_id.startswith(self.SPATIAL):
            return          # healing/levelling are not facts about geography
        """This area could not achieve that subgoal — remember it."""
        if not region or "None" in region:
            return
        # An ITEM is not a property of a place. Standing on Route 2 without
        # a Potion proves nothing permanent — you buy one in a shop or find
        # it elsewhere — yet the spatial proof kept stamping
        # "item:POTION unreachable from ROUTE_2". Only the explicit
        # "this shop does not stock it" rule may mark an item target.
        if sg_id.startswith("item:") and not shop_proof:
            return
        # And do not record a MAP proof the walked graph already refutes:
        # pruning at load is too late, the false mark traps the run for the
        # rest of the attempt (map:PEWTER_GYM from VIRIDIAN_CITY, which is
        # plainly walkable).
        if sg_id.startswith("map:"):
            want = sg_id.split(":", 1)[1]
            dests = [r for r in set(list(self.explored) + list(self.visits))
                     if r.split("|")[0] == want]
            if any(self._route(region, d) for d in dests):
                self.log("dead_end_refused", subgoal=sg_id, region=region,
                         reason="a walked path to it already exists")
                return
        # A PLACE WITH DOORS YOU HAVE NOT OPENED IS NOT A PROVEN DEAD END.
        # This rule is already stated for the "fully worked" verdict; the
        # dead-end ledger never honoured it, so ONE failure at ROUTE_10 —
        # the mouth of Rock Tunnel, with four exits still untried and two
        # of the tunnel's own floors already walked — filed it as a KNOWN
        # DEAD END for Celadon and told the run "do NOT go back". It is the
        # only way through. A dungeon you have not finished is not a wall.
        _untried = set(self.frontier.get(region) or ()) - set(
            (self.explored.get(region) or {}))
        if _untried:
            self.log("dead_end_refused", subgoal=sg_id, region=region,
                     reason=f"{len(_untried)} exit(s) here never taken: "
                            + ",".join(sorted(_untried)[:6]))
            return
        # NOR IS A ROOM WITH UNTRIED GROUND ONE DOOR ON. The rule above
        # asks only about THIS room's exits, so every floor of a department
        # store gets branded in turn — none of them satisfies the goal, and
        # each one's exits are all walked — while the roof one door further
        # holds the only thing that does (user, 2026-08-19: "you could just
        # as easily say it about every floor of the mart"). A dead end is a
        # place with nothing untried BEYOND it either, as far as the walked
        # graph goes.
        _seen, _q = {region}, [region]
        while _q:
            _cur = _q.pop()
            for _k, _e in (self.explored.get(_cur) or {}).items():
                _nxt = (_e or {}).get("to")
                if not _nxt or _nxt in _seen or (_e or {}).get("shut"):
                    continue
                _seen.add(_nxt)
                _left = set(self.frontier.get(_nxt) or ()) - set(
                    (self.explored.get(_nxt) or {}))
                _things = [n for n in (self.sightings.get(_nxt) or [])
                           if n not in (self._tried_objs.get(_nxt) or set())]
                if _left or _things:
                    self.log("dead_end_refused", subgoal=sg_id,
                             region=region,
                             reason=(f"{_nxt} beyond it still has "
                                     f"{len(_left)} untried exit(s) and "
                                     f"{len(_things)} unpressed thing(s)"))
                    return
                _q.append(_nxt)
        d = self.dead_ends.setdefault(sg_id, {})
        d[region] = d.get(region, 0) + 1
        self.log("dead_end", subgoal=sg_id, region=region, times=d[region])
        self._save_memory()

    @staticmethod
    def _target_key(sg) -> str:
        """What this subgoal is actually trying to reach/achieve."""
        dw = sg.get("done_when") or {}
        for k in ("area", "map", "flag", "badge"):
            if dw.get(k):
                return f"{k}:{dw[k]}"
        if dw.get("has_item"):
            return "item:" + ",".join(sorted(dw["has_item"]))
        for k in ("party_size", "lead_level", "party_min_level",
                  "slot_level", "party_healthy", "knows_move",
                  "party_type", "has_species", "dex_owned"):
            if k in dw:
                return f"{k}:{dw[k]}"
        # AN any_of OF PARTY PREDICATES IS A PARTY GOAL. "the party holds a
        # WATER or GRASS type" is written {"any_of":[{"party_type":"WATER"},
        # {"party_type":"GRASS"}]}, and this fell through to "subgoal:id" —
        # so the catch leg was rendered the exploration ledger instead of
        # the training text, and never read the ball count or what the
        # grass had offered. Keyed by the alternatives, joined.
        alts = dw.get("any_of") or []
        if alts and all(isinstance(a, dict) and len(a) == 1
                        and next(iter(a)) in ("party_type", "has_species")
                        for a in alts):
            k0 = next(iter(alts[0]))
            return f"{k0}:" + "|".join(str(next(iter(a.values())))
                                        for a in alts)
        return "subgoal:" + sg.get("id", "?")

    # WHAT THIS SUBGOAL IS FOR is not always a PLACE. Everything the
    # escalation context says — prefer untried exits, you have been here 7
    # times already, these rooms still have ways you have never taken,
    # press A on things before you leave — is advice for FINDING somewhere
    # or something. Handed to a subgoal whose condition is a LEVEL, it
    # reads as an instruction to stop doing the one thing that can satisfy
    # it. Watched live: train_charmander_12 stood on Route 22, which has
    # wild Pokemon in it, was told it had been in this exact area 7 times
    # already and that untried exits "are the only way to find anything
    # new", and walked west to open doors at the Pewter museum — nine
    # escalations deep on a condition that needed it to stand in grass.
    # knows_move is NOT here: a move is known by a machine (one op), by a
    # level (fighting), or by a different Pokemon (a catch, a trade, a
    # gift — going somewhere). Under the training text a knows_move step
    # was told "walking somewhere new is not progress here; fighting is",
    # lost the whole ledger, and could not see the trade house it needed.
    PARTY_TARGETS = ("party_size:", "lead_level:", "party_min_level:",
                     "slot_level:", "party_type:",
                     "has_species:", "dex_owned:")

    @classmethod
    def _is_party_goal(cls, tgt: str) -> bool:
        """Is this subgoal satisfied by FIGHTING, not by arriving?"""
        return str(tgt or "").startswith(cls.PARTY_TARGETS)

    @staticmethod
    def _catch_target(subgoal) -> dict | None:
        """WHAT this subgoal is trying to catch, from its own done_when.

        Nothing is invented: has_species names species, party_type names
        types, and both may sit inside an any_of, which is exactly how the
        live "WATER or GRASS" objective was written. A goal that only wants
        MORE Pokemon (party_size) or more of the dex (dex_owned) is
        satisfied by anything, and returns None so the policy behaves as it
        always has.
        """
        def walk(pred):
            out = []
            for k, v in (pred or {}).items():
                if k == "any_of":
                    for alt in (v or []):
                        out += walk(alt)
                else:
                    out.append((k, v))
            return out

        species, types = set(), set()
        for k, v in walk(subgoal.get("done_when") or {}):
            vals = ([v] if isinstance(v, str)
                    else list(v) if isinstance(v, (list, tuple, set))
                    else list(v.keys()) if isinstance(v, dict) else [])
            if k == "has_species":
                species |= {str(x).upper() for x in vals}
            elif k == "party_type":
                types |= {str(x).upper() for x in vals}
        if not (species or types):
            return None
        return {"species": species, "types": types}

    @staticmethod
    def _where(obs) -> str:
        m = (obs or {}).get("map") or {}
        return f"{m.get('id')}|{m.get('region')}"

    @staticmethod
    def _world_mark(obs) -> list:
        """What the run is carrying, coarsely — badges, event flags, and
        the KINDS of item in the bag. Not a clock: a door does not care how
        long you stood elsewhere, only whether you came back with something
        you did not have. Compared, never interpreted."""
        o = obs or {}
        return [len(o.get("badges") or []), len(o.get("flags") or []),
                len(o.get("bag") or {})]

    def _twin_keys(self, before_obs, step) -> list:
        """A doorway is one door however many tiles it spans.

        Gate buildings have PAIRED warp tiles — (3,0) and (4,0) are the same
        opening — and the ledger counted them as two separate unknowns, so
        every gate cost twice the rounds to exhaust and kept "a door nobody
        has opened" true long after the doorway had been tried. use_warp has
        always known this (it retries the adjacent twin on failure); the
        bookkeeping did not.
        """
        x, y = step.get("x"), step.get("y")
        if x is None:
            return []
        warps = ((before_obs or {}).get("map") or {}).get("warps") or []
        dest = next((w.get("dest") for w in warps
                     if w.get("x") == x and w.get("y") == y), None)
        return [f"{w.get('x')},{w.get('y')}" for w in warps
                if w.get("dest") == dest
                and abs((w.get("x") or 0) - x) + abs((w.get("y") or 0) - y) == 1]

    def _goal_drift(self, sg, obs):
        """Is this subgoal getting CLOSER to what it is aimed at?

        The printed map gives a hop count between any two roads, which is
        the same number the itinerary line is built from — so "am I nearer
        Celadon than I was" is answerable every round without guessing.
        Nothing here chooses a direction; it states a distance and, when a
        subgoal has spent a long stretch getting no nearer, stops paying
        for it so the plan can be rewritten from what actually happened.
        The run toured Pewter, Route 2, Route 11 and Diglett's Cave on a
        `travel_to_celadon` subgoal — every one of them further away than
        where it started.

        WHAT THE NUMBER IS. It used to be `_goal_score`, which is a COST,
        not a distance: it prices a shut door at `4 + visits//8` so the
        ranking can choose between two walls, and falls back to 50+ or a
        bare 99 sentinel for ground the printed map has no line to. Printed
        as "the printed map puts X N step(s) from Y" that is simply untrue —
        the log has `ROUTE_9 6 step(s) from ROUTE_10` (it is one leg) and
        `GAME_CORNER 99 step(s) from CELADON_CITY` (the Game Corner is
        INSIDE Celadon; 99 means "no answer"). Worse than the wording: the
        toll grows with every visit, so the give-up test could fire on a
        party that had not moved a tile, purely because leaning on a door
        made the door dearer.

        The honest number for "am I nearer than I was" is the untolled hop
        count over the printed map plus the links this run has walked. It
        is a real distance, it does not drift while the party stands still,
        and where the map has no answer we say so instead of printing a
        sentinel. Ranking candidate destinations still uses the cost — that
        is what it is for, and it is never shown as a distance.

        Returns (note, give_up).
        """
        tgt = self._target_key(sg)
        want_map = (tgt.split(":", 1)[1].split("|")[0]
                    if tgt.startswith(("map:", "area:")) else None)
        if not want_map and tgt.startswith("badge:"):
            want_map = BADGE_GYMS.get(tgt.split(":", 1)[1])
        want_map = _doorstep(want_map) if want_map else None
        here_map = ((obs or {}).get("map") or {}).get("id")
        if not (want_map and here_map):
            return "", False
        try:
            d = static_cost(_doorstep(here_map), want_map, {},
                            self._walked_map_links())
        except Exception:
            return "", False
        if d is None:
            # No line on the printed map and no walked link either. Saying
            # "99 steps" would be inventing a distance; saying nothing hides
            # that the target is off the map you are holding.
            return (f"\nHOW FAR OFF YOU ARE: the printed map draws no road "
                    f"between {here_map} and {want_map}, so it cannot say "
                    f"how far apart they are.", False)
        st = self._drift.setdefault(sg.get("id"), {"best": d, "since": 0,
                                                   "at": here_map})
        if d < st["best"]:
            st["best"], st["since"], st["at"] = d, 0, here_map
        else:
            st["since"] += 1
        # GENEROUS, because a real route can lead AWAY first: Rock Tunnel
        # is the way to Celadon and every leg of it is further from Celadon
        # than standing in Cerulean. Only a long stretch with no improvement
        # at all counts, and only while actually further off than the best.
        give_up = st["since"] >= 14 and d > st["best"]
        note = (f"\nHOW FAR OFF YOU ARE: on the printed map {here_map} is "
                f"{d} leg(s) from {want_map}. The closest you have been "
                f"this subgoal is {st['best']} (at {st['at']})"
                + (f", and you have not improved on it for {st['since']} "
                   f"rounds." if st["since"] else "."))
        if give_up:
            self.log("goal_drift_giveup", subgoal=sg.get("id"),
                     want=want_map, here=here_map, d=d, best=st["best"],
                     since=st["since"])
        return note, give_up

    def _passage_note(self, here: str) -> str:
        """Buildings whose far side is somewhere else.

        Only walked doors count. The first version asked for TWO doors into
        the same building FROM HERE, which is weak evidence and stopped
        being true the moment one of the pair was cleared -- Cerulean's
        trashed house went quiet with the whole route through it already
        recorded. The far side is the better place to look: if a building
        this run has entered has exits reaching MORE THAN ONE area block,
        it joins them, and that is a fact about ground already walked.

        It matters because BFS walks open ground on one map, so a road that
        leaves through a door and returns on the far side is invisible to
        it -- Cerulean's way south runs through that house, and the south
        seam fails for ever with no bush to blame.
        """
        node = self.explored.get(here) or {}
        out = []
        for key, e in node.items():
            dest = (e or {}).get("to")
            if not dest or dest == here or (e or {}).get("shut"):
                continue
            far = self.explored.get(dest) or {}
            blocks = {(v or {}).get("to") for v in far.values()
                      if (v or {}).get("to") and not (v or {}).get("shut")}
            # ONLY A PASSAGE IF IT JOINS TWO PARTS OF *THIS* MAP. Without
            # this every road with two ends qualified — Route 24 "joins"
            # Route 25 — and the noise pushed the one that mattered out of
            # the list entirely.
            _mymap = here.split("|")[0]
            others = sorted(b for b in blocks
                            if b and b != here and b != dest
                            and b.split("|")[0] == _mymap)
            if others:
                out.append(f"{dest} (in at {key}) also opens onto "
                           + ", ".join(others))
        if not out:
            return ""
        return ("\nA BUILDING YOU HAVE WALKED THROUGH joins parts of this "
                "map that cannot be walked between — going in one door and "
                "out the other is how you get across, and no amount of "
                "walking will do it: " + "; ".join(out[:3]) + ".")

    def _learn_doorsteps(self):
        """A building you have walked OUT of sits on the road you landed on.

        The printed town map draws routes, towns and landmarks — it does
        not draw every doorway, so the DAY CARE is nowhere in map_doors and
        _doorstep could not place it. A subgoal aimed at DAYCARE|2,1 then
        had no anchor to steer toward: the run held "go to the day care" as
        an objective for a whole leg while never once heading for Route 5,
        because nothing connected the name to a place on the map.

        Walking out of it is not printed-map knowledge, it is something
        this run DID: it stood in the DAY CARE, stepped through the door,
        and arrived on ROUTE_5. setdefault, so anything the town map
        actually draws still wins.
        """
        self._doorsteps_learned = []
        for region, exits in (self.explored or {}).items():
            inside = region.split("|")[0]
            if not inside or inside in MAP_EDGES or inside in INTERIOR_ROAD:
                continue
            for e in (exits or {}).values():
                to = (e or {}).get("to")
                out = str(to).split("|")[0] if to else ""
                if out and out in MAP_EDGES and out != inside:
                    INTERIOR_ROAD.setdefault(inside, out)
                    # NO self.log HERE. This runs from _load_memory, which
                    # runs from __init__, before the log file is opened, so
                    # self.log raised AttributeError on logf — and since
                    # _load_memory guards only OSError/ValueError that took
                    # the WHOLE ledger load down with it. dead_ends, visits,
                    # frontier and sightings never loaded, and the next save
                    # would have written that emptiness over a day of walked
                    # map. Collect; the caller reports once there is a log.
                    self._doorsteps_learned.append((inside, out))
                    break

    def note_transition(self, before_obs, step, after_obs, reason="",
                        op_detail=""):
        """Record: from this area, that exit led there."""
        src, dst = self._where(before_obs), self._where(after_obs)
        if "None" in src or "None" in dst:
            return
        # WHERE THE OP SAYS IT ARRIVED BEATS WHERE WE ENDED UP STANDING.
        # `dst` is read after settling, so anything that moved the party
        # between the warp firing and the read is attributed to the DOOR:
        # ROUTE_7|18,2 --18,9--> SAFFRON_CITY, four times, for a door the
        # game's own table says opens into ROUTE_7_GATE. That is the door
        # west through the gate recorded as the way back east, and the
        # model — correctly reading the ledger — spent three attempts
        # reaching for the far-side doors it cannot walk to instead. The
        # op's detail names the map it landed on ("map->ROUTE_7_GATE"); if
        # that is not where we are now, this observation cannot say what
        # the door leads to. Honest ignorance beats a wrong edge, which is
        # the rule the shim already applies at the other end.
        _arr = _re.search(r"map->([A-Z0-9_]+)", str(op_detail or ""))
        if _arr and _arr.group(1) != str(dst).split("|")[0]:
            self.log("transition_dropped_moved_on", frm=src,
                     via=str((step or {}).get("x", "")) + "," +
                         str((step or {}).get("y", "")),
                     arrived=_arr.group(1), settled=dst)
            return
        # A CROSSING WHOSE DOOR WE CANNOT NAME TEACHES NOTHING ABOUT DOORS.
        # The key here is the tile the walk AIMED at, which is only the
        # right answer when the walk finished and stepped through on
        # purpose. Walking toward the Day Care door and clipping the Route
        # 5 gate on the way wrote "10,21 leads to ROUTE_5_GATE"; that
        # contradicted the true edge learned on the way in, the conflict
        # rule voided the honest one, and the way into the Day Care was
        # gone. The shim now says so when it cannot name the door. Take the
        # visit, take the region, write no edge.
        # AN ELEVATOR CAR HAS NO FIXED DOORS. Its exit warps are rewritten
        # by the panel every ride, so the ledger's one-door-one-destination
        # model is false inside one: the Celadon car taught "(1,3) -> 5F",
        # came out on 3F next ride, the edge conflicted, was deleted and
        # relearned, and the run spent 48 visits re-deriving the building.
        # Take the visit, learn no edge; the panel line already says what
        # the car offers.
        _srcmap = ((before_obs or {}).get("map") or {}).get("id") or ""
        if (str(_srcmap).endswith("_ELEVATOR")
                or ((before_obs or {}).get("map") or {}).get("lift_floors")):
            # ...but the CAR still connects to every floor it has carried
            # you to, and that is a real, walkable edge — the graph needs
            # it or a route through a department store has a hole in it
            # (`go` answered "no walked way from the car to 1F" twice).
            # Keyed by the RIDE, not by a door: "lift:<MAP>", which
            # _walk_route knows how to execute.
            self._count_visit(dst)
            node = self.explored.setdefault(src, {})
            k = f"lift:{str(dst).split('|')[0]}"
            e = node.setdefault(k, {"n": 0, "to": dst})
            e["n"] = int(e.get("n") or 0) + 1
            e["to"] = dst
            self.log("elevator_exit", frm=src, to=dst, key=k)
            self._save_memory()
            return
        _d = str(((after_obs or {}).get("result") or {}).get("detail") or "")
        # ...or straight from the op, because a caller that settles after
        # sending has already replaced result with the settle's own.
        _d += " " + str(op_detail or "")
        if "door unknown" in _d:
            self._count_visit(dst)
            self.log("crossed_door_unknown", frm=src, to=dst)
            return
        key = (f"{step.get('x')},{step.get('y')}"
               if step.get("x") is not None else step.get("dir"))
        if key is None:
            return
        if src == dst:
            # A DOORWAY YOU COULD NOT EVEN WALK TO IS NOT AN EXIT OF THIS
            # ROOM. An attempt that never reached the tile was filed against
            # whatever region the party was standing in, so Mt Moon's
            # B1F|24,14 came to own all eight of the floor's doorways —
            # five of them in pockets it cannot reach — and the room read
            # as fully accounted for. Record a refusal only for a door we
            # actually stood at.
            # COULD NOT WALK THERE IS NOT A FACT ABOUT THE DOOR. The shut
            # flag already exempts this case ("it clears on its own") — but
            # exempting the flag while still writing n=1 achieves the same
            # blacklisting by the other route, because an edge with n>=1 is
            # a TAKEN exit and drops off the untried frontier for good.
            # Mt Moon 1F's third ladder (5,5) died exactly this way: one
            # walk failed, `couldn't reach the warp tile — somebody is
            # standing by it: MTMOON1F_HIKER at (5,6)`, and the ledger
            # recorded 5,5 -> itself. The tile is open ground with all four
            # approaches walkable, so the walk should have gone round; the
            # named NPC was the nearest one, not a proven cause. After that
            # the router would never elect it again and the model was told
            # it leads back where you stand, so nothing ever retried it —
            # while B1F 5,5, its far end, sits in the unreached stretch
            # holding 23,3 (the fossils) and 27,3 (the way out to Cerulean).
            # Its twin 17,11 survived only by being re-elected and firing.
            # Record NOTHING and let it stay untried; a door that truly
            # refuses gets recorded on the attempt where we stood at it.
            if "couldn't reach" in (reason or ""):
                # ...BUT COUNT IT. Recording no EDGE is right — an attempt
                # that never reached the tile says nothing about where the
                # door goes. Recording nothing AT ALL was not: the key stays
                # out of `explored` for ever, so the room goes on calling it
                # UNTRIED, and "EXITS FROM HERE — UNTRIED (prefer these,
                # they are the only way to find anything new)" is the
                # strongest line in the prompt. The Route 5 guard house has
                # two such doors; the guard's script fires on approach, the
                # shim reports "couldn't reach the warp tile (interrupted
                # (battle or script))", and the run went back in TWENTY-TWO
                # times because the harness kept telling it there was
                # something new in there. A door tried twenty-one times is
                # not untried, whatever the ledger can prove about it.
                # Nothing is sealed: the count is keyed to the world it was
                # collected in and starts again the moment anything changes,
                # so a door that opens later still opens.
                self._note_unreached(src, str(key), before_obs)
                self.log("exit_unreached", frm=src, via=str(key),
                         why=str(reason)[:120])
                return
            _w = ((before_obs or {}).get("map") or {}).get("warps") or []
            if step.get("x") is not None and not any(
                    w.get("x") == step.get("x") and w.get("y") == step.get("y")
                    and w.get("reachable") for w in _w):
                return
            # AN EXIT THAT DOES NOT MOVE YOU IS STILL AN EXIT YOU TRIED.
            # Returning early here left it out of the taken ledger, so it
            # stayed on the untried list — which the free round reads as
            # "the only way to find anything new". At the Saffron gate it
            # elected the same door six times running, each time landing
            # back in the room it was trying to leave, while the note above
            # it insisted two ways out had never been taken. Record where
            # the door actually put you: back here. If it ever does fire
            # properly the edge-conflict check voids this and it reads
            # untried again, so nothing is lost by being honest now.
            node = self.explored.setdefault(src, {})
            for k in [key] + self._twin_keys(before_obs, step):
                e = node.setdefault(k, {"n": 0, "to": dst})
                e["n"] += 1
                e["to"] = dst
                # A BLOCKED UNKNOWN IS NOT AN EXPLORED ONE. This door was
                # walked into and refused — somebody stood in it, or a
                # script turned you back — which is a different fact from a
                # door that opened onto somewhere. Recording only "tried"
                # loses the difference, and the difference is the whole
                # question of whether coming back later is worth anything:
                # a guard wanting a drink moves, a wall does not.
                # COULD NOT REACH IT IS NOT THE SAME AS IT REFUSED. The
                # first is a fact about pathing at this instant — an NPC
                # standing on the approach, the party on the wrong side of
                # a room — and it clears on its own: Mt Moon's 17,11 ladder
                # failed twice with "couldn't reach" and warped fine on the
                # third try. Marking that shut blacklisted a working ladder
                # for ever. Only a door we STOOD AT and that did not fire
                # is shut.
                if "couldn't reach" not in (reason or ""):
                    e["shut"] = True
                    self._note_blocker(src, k, "door", reason or "")
                # WHEN it was shut, so we can tell whether anything has
                # happened since. A door that turned you back is worth one
                # more press once you are carrying something you were not
                # carrying then — the guard wanting a drink is the case
                # this whole run has been stuck behind.
                e["shut_at"] = self._world_mark(after_obs)
                # ...AND WHETHER WE COULD EVEN GET TO IT. "Being able to
                # reach it is itself the change" is the right rule and the
                # code could not apply it: it compared reachable-NOW against
                # nothing, so every reachable shut door counted as reopened
                # for ever and the shut flag meant nothing for the doors it
                # most applies to. Record the THEN, so the comparison the
                # comment describes can actually be made.
                if step.get("x") is not None:
                    _bw = ((before_obs or {}).get("map") or {}).get("warps") or []
                    e["shut_reach"] = any(
                        w.get("x") == step.get("x")
                        and w.get("y") == step.get("y")
                        and w.get("reachable") for w in _bw)
            self.log("exit_refused", frm=src, via=str(key),
                     times=node[key]["n"],
                     twins=len(self._twin_keys(before_obs, step)))
            self._save_memory()
            return
        self._count_visit(dst)
        dmap = dst.split("|")[0]
        if dmap != src.split("|")[0] and self._cur_target:
            k = f"{self._cur_target}|{dmap}"
            self._entered_map[k] = self._entered_map.get(k, 0) + 1
        ap = (after_obs or {}).get("player") or {}
        if ap.get("x") is not None:
            self._arrived = (dst, (ap["x"], ap["y"]))
            self._came_from = src
            self._reversals = 0
            # THE FAR SIDE OF A DOOR IS A DOOR YOU HAVE OPENED. An edge is
            # keyed on the tile you DEPARTED from, so walking city -> house
            # writes 27,11 on the city and house -> city writes 3,0 on the
            # house. The city-side tile of the house's back door never gets
            # an entry at all, because you only ever ARRIVE on it — so
            # Cerulean's (27,9) was still being reported as a doorway never
            # opened after the run had come out through it THIRTY-TWO times,
            # and it is the way south. Compare (9,9) at the badge house,
            # which IS recorded, purely because the run once happened to
            # leave through it.
            # Only when the tile you landed on IS a doorway AND that doorway
            # leads back where you came from: then there is no ambiguity
            # about which door you just used.
            _ak = f"{ap['x']},{ap['y']}"
            _smap = src.split("|")[0]
            for _w in ((after_obs or {}).get("map") or {}).get("warps") or []:
                if f"{_w.get('x')},{_w.get('y')}" != _ak:
                    continue
                if str(_w.get("dest") or "") != _smap:
                    continue
                _back = self.explored.setdefault(dst, {})
                if _ak not in _back:
                    # n=0, NOT 1. This edge is learned by ARRIVING
                    # through it, which proves where it goes but is not a
                    # traversal in this direction — and the count is
                    # printed to the model as "taken Nx". Seeding it at 1
                    # and then adding 1 per real departure made a room
                    # entered once report its door as taken twice, which
                    # is not a thing that can happen.
                    _back[_ak] = {"to": src, "n": 0}
                    self.log("reverse_edge", frm=dst, via=_ak, to=src)
                    self._save_memory()
                break
        # A DOOR THIS ROOM DOES NOT HAVE. The edge is keyed on the tile the
        # op AIMED at, and once — leaving the Mt Moon Pokemon Center — that
        # was 18,5, which is a ROUTE_4 tile: the Center's own two door tiles
        # (3,7 and 4,7) were left untried while a coordinate it does not
        # contain sat in its ledger as a taken exit. One occurrence in a
        # whole run, but the cost is permanent: a room whose real doors read
        # untried for ever is for ever the freshest thing on the frontier,
        # and the walk-back keeps electing it. Same rule the mid-walk case
        # already follows — honest ignorance beats a wrong edge.
        _mw = ((before_obs or {}).get("map") or {}).get("warps") or []
        if (step.get("x") is not None and _mw
                and not any(w.get("x") == step.get("x")
                            and w.get("y") == step.get("y") for w in _mw)):
            self.log("edge_key_foreign", frm=src, via=str(key), to=dst)
            return
        # A REGION WITH A SEAM PROOF DID NOT JUST CROSS THAT SEAM. Route 4
        # west (ROUTE_4|4,4) had "the east seam cannot be walked to from
        # here" proven from (9,17); minutes later a cross east filed under
        # ROUTE_4|4,4 -> CERULEAN, because the party stood on the east half
        # under a stale/mislabelled region while a harness route-walk had
        # just moved it. The router then offered Route 3 -> Route 4 west ->
        # Cerulean, a road that skips the mountain and dies at the seam.
        # A crossing and a standing seam proof cannot both be true of one
        # region: the label is the wrong one, so file nothing under it.
        if ("," not in str(key)
                and str(key) in (self._no_cross.get(src) or set())):
            self.log("edge_misattributed", frm=src, via=str(key), to=dst,
                     why="seam proven uncrossable from this region")
            return
        node = self.explored.setdefault(src, {})
        # A door's destination is deterministic, so a walk that lands
        # somewhere CONTRADICTING the recorded edge means one of the two
        # recordings is wrong (a mid-walk teleport recorded the intended
        # tile with another ladder's landing, and the overwrite severed the
        # route east of Route 3). A re-fingerprint of the same room arrives
        # as an ALIAS and may overwrite; a true conflict voids the edge —
        # honest ignorance beats a coin-flip assertion, and the door reads
        # untried again so the next clean walk re-records it.
        old = node.get(key)
        # A DOOR THAT WENT SOMEWHERE BEATS A RECORD OF IT GOING NOWHERE.
        # A self-loop means the attempt failed; a real destination means it
        # worked. Treating them as equal contradictions voided BOTH and let
        # the next transient failure re-record the self-loop — so Mt Moon's
        # 17,11 ladder read "leads back to 1F, taken 8x" even after we
        # watched it warp into B1F|14,8, and the run was left believing 1F
        # had exactly one working ladder. Failures must not overwrite
        # successes by attrition.
        if old and old.get("to") == src and dst != src:
            old = None
            node.pop(key, None)
        # A BLACKOUT IS NOT A CROSSING. Fainting teleports the party to a
        # Pokemon Center, and if that lands while a walk is in flight the
        # transition reads "ROUTE_17 south -> CELADON_CITY" — nonsense that
        # then DELETED the true edge as a conflict. Route 17 was left with
        # no exits at all, so every route through Cycling Road failed and
        # `go` answered "no walked way" for a road the run had walked twice.
        # A destination that is a Pokemon Center the party did not walk to,
        # with the party freshly healed, is a respawn.
        if (self._faint_at is not None
                and str(dst).split("|")[0].endswith("POKECENTER")):
            self.log("transition_ignored_blackout", frm=src, via=str(key),
                     to=dst)
            return
        if old and old.get("to") not in (dst,) \
                and dst not in AREA_ALIASES.get(old.get("to"), ()):
            # ...and two anchors of ONE MAP are not a contradiction. A wide
            # seam lands wherever the walk happened to reach it, so the same
            # crossing can arrive at ROUTE_18|6,0 one time and |40,8 the
            # next; deleting the edge threw away a road that plainly exists.
            if str(old.get("to") or "").split("|")[0] == str(dst).split("|")[0]:
                self.log("edge_widened", frm=src, via=str(key),
                         was=old.get("to"), now=dst)
            else:
                self.log("edge_conflict", frm=src, via=str(key),
                         was=old.get("to"), now=dst)
                del node[key]
                self._save_memory()
                return
        for k in [key] + self._twin_keys(before_obs, step):
            e = node.setdefault(k, {"n": 0, "to": dst})
            e["n"] += 1
            e["to"] = dst
            e.pop("shut", None)          # it opened; whatever shut it is gone
            e.pop("blocked_at", None)    # it landed; the block is gone
            self._clear_blocker(src, k, f"it opened — you came out at {dst}")
            # WHERE THIS DOOR PUT YOU. Only the region label was kept, and
            # a region is coarse: Cerulean's front door and the hole in the
            # trashed house's back wall both read CERULEAN_CITY|20,0, so
            # the ledger said "a room with three doors to the same place"
            # about the one building that joins the city's two halves. The
            # tile you land on is the difference between those doors, and
            # it is simply where you were standing when you came out.
            _ap = ((after_obs or {}).get("map") or {}).get("player") or {}
            if _ap.get("x") is not None and _ap.get("y") is not None:
                e["land"] = f"{_ap['x']},{_ap['y']}"
        self.log("explored", frm=src, via=str(key), to=dst,
                 times=node[key]["n"])
        self._save_memory()

    def _unopened_doors(self, obs) -> list:
        """Doors never walked through that a PERSON is standing on.

        Returns (key, dest, blocker-name). Warps are listed per MAP, not per
        region, so on a split map every region can see doors belonging to
        another part — the badge-house back yard is one exit and a patch of
        grass, and counting the whole city's shut doors against it means it
        can never be called finished. The honest signal is on screen: a door
        you cannot reach with a REACHABLE person beside it is a door someone
        is standing in front of, here, now. Cerulean's trashed house has a
        policeman one tile below it; its cave door has an unreachable NPC
        beside it and belongs to ground the party has never stood on.
        """
        here = self._where(obs)
        taken = self._taken_here(here)
        m = (obs or {}).get("map") or {}
        folk = [o for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("x") is not None]
        out = []
        for w in (m.get("warps") or []):
            k = f"{w.get('x')},{w.get('y')}"
            if k in taken or w.get("reachable"):
                continue
            # A DOORWAY YOU CANNOT WALK TO IS STILL A DOORWAY YOU CAN SEE.
            # Report the door, and name the nearest person as CONTEXT
            # rather than as the cause: what is between you and it is not
            # something this can know.
            #
            # HISTORY, CORRECTED (user, 2026-08-15): this widening used to
            # be justified here by "Mt Moon's ladder to the east exit never
            # once appeared, in any round, in any attempt". THAT EVENT NEVER
            # HAPPENED — it was invented in an earlier session and then
            # cited as precedent. The widening is kept on its own merit (a
            # door you can see is information the model should have), NOT on
            # that story. Do not treat the removed sentence as evidence.
            near = min(
                ((abs((o.get("x") or 0) - (w.get("x") or 0))
                  + abs((o.get("y") or 0) - (w.get("y") or 0)),
                  o.get("name")) for o in folk if o.get("name")),
                default=(None, None))
            out.append((k, w.get("dest"),
                        near[1] if near[0] is not None and near[0] <= 8
                        else None))
        return out

    def _untried_exits(self, obs) -> list:
        """Ways out of here never taken — doors and roads alike. Map edges
        count: a town's road out is the exit an event most often hides on."""
        m = (obs or {}).get("map") or {}
        taken = self._taken_here(self._where(obs))
        # a proven-uncrossable seam is not an exit — leaving it "untried"
        # here meant the searched proof could never fire for a stub region
        # and the escort ranked it as frontier forever
        blocked = self._sealed(self._where(obs))
        # a door reached for twice in this state of the world and never got
        # through is not untried — the same rule _frontier_left applies, and
        # it went into only one of the two definitions when it was written
        blocked = set(blocked) | set(self._spent_exits(self._where(obs)))
        seen_maps = {a.split("|")[0] for a in self.visits}
        out = []
        for w in (m.get("warps") or []):
            k = f"{w.get('x')},{w.get('y')}"
            # A SHUT DOOR IS NEITHER EXPLORED NOR UNTRIED. It stays out of
            # this list — it monopolised the "prefer a door nobody has
            # opened" rule and held the run at the Saffron gates for
            # hundreds of arrivals — but it comes BACK the moment the run
            # is carrying something it was not carrying when the door
            # refused it. Nothing is known about what lies beyond a shut
            # door, so it is never resolved, only postponed.
            was = taken.get(k) or {}
            # BEING ABLE TO REACH IT IS ITSELF THE CHANGE. A doorway that
            # refused you while pathfinding could not get there was marked
            # shut and left out for ever after — and Mt Moon ended up with
            # every one of its doorways "taken", five of which had never
            # been walked at all. If you can walk to it now and could not
            # then, that is new, whatever the bag says.
            # reachable NOW and not reachable THEN is new; reachable in
            # both is the same door refusing you again. Legacy entries have
            # no `shut_reach` and default to "it was reachable then", which
            # leaves the world mark as their only way back — the same rule
            # _frontier_left applies.
            reopened = (was.get("shut")
                        and (was.get("shut_at") != self._world_mark(obs)
                             or (w.get("reachable")
                                 and not was.get("shut_reach", True))))
            if (k not in taken or reopened) and k not in blocked:
                # A DOORWAY PATHFINDING CANNOT REACH IS NOT AUTO-EXPLORABLE.
                # It was briefly listed here so the run would try a blocked
                # ladder, and that poisoned everything downstream: this list
                # also answers "does this region still have anything left",
                # so a region with one blocked door looked unexplored for
                # ever — the frontier walk-back stopped firing and free
                # rounds burned on doors that cannot fire. Blocked doorways
                # are reported to the MODEL instead (see the DOORWAYS ON
                # THIS MAP line), which can propose one deliberately.
                if not w.get("reachable"):
                    continue
                _d = self._walked_dest(m.get("id"), k)
                _face = None if _d else self._frontage(w.get("dest"))
                out.append((bool(_d) and _d.split("|")[0] in seen_maps,
                            f"({k})->{_d or _face or 'UNKNOWN'}"))
        for d, t in (m.get("connections") or {}).items():
            if d not in taken and d not in blocked:
                # A SEAM IS A DOOR WITH NO DOORFRAME. Doors already say
                # UNKNOWN until walked; a map edge was still naming the map
                # on its far side, out of the same table, and that is the
                # Town Map's answer arriving by another route now that
                # edges_text is gated on holding one. You can SEE a road
                # leave — the seam is on screen — but not what it is called.
                _t = self._walked_dest(m.get("id"), d)
                out.append((bool(_t) and _t.split("|")[0] in seen_maps,
                            f"walk {d} -> {_t or 'UNKNOWN'}"))
        # FRONTIER FIRST: an exit into a map never visited can teach
        # something; one back into a map already seen mostly cannot. Pallet's
        # buildings kept winning over the road north purely by listing order,
        # and the road is where the trigger was.
        out.sort(key=lambda p: p[0])
        return [t for _, t in out]

    def _route(self, frm: str, to: str, avoid: set | None = None):
        """Shortest path over the LEARNED region graph, as (exit_key, dest)
        hops. Only edges actually walked count — this navigates known
        ground, it never guesses a connection."""
        from collections import deque
        if frm == to:
            return []
        _OPP = {"north": "south", "south": "north",
                "east": "west", "west": "east"}

        def edges(region):
            # An area's walked edges are split across its fingerprints: the
            # same Mt Moon 1F room is 2,2 before a blocker moves and 3,2
            # after, and the descent was only ever walked from one of them.
            # Routing that ignores the aliases cannot get back into the
            # mountain at all — the blackout walk-back reported "no route"
            # from a Pokemon Center that plainly connects.
            out = dict(self.explored.get(region) or {})
            for alias in AREA_ALIASES.get(region, ()):
                for k, v in (self.explored.get(alias) or {}).items():
                    out.setdefault(k, v)
            # A SEAM CROSSED ONE WAY IS THE SAME SEAM. The graph records a
            # crossing from the side it was walked, so a run that travelled
            # Fuchsia -> east all the way had no westward edge anywhere and
            # `go` refused to take it home — while "I walked east from A
            # into B" plainly means B's west side touches A, which is what
            # the printed map says too. Offered as a hop only; if the way
            # back is blocked (a ledge, a slope), the crossing fails and
            # _walk_route records that like any other.
            for _r2, _es in (self.explored or {}).items():
                for _k2, _e2 in (_es or {}).items():
                    if _k2 not in _OPP or (_e2 or {}).get("to") != region:
                        continue
                    _back = _OPP[_k2]
                    # A SEAM CAN LAND IN TWO DIFFERENT PLACES. Route 13's
                    # west edge is recorded as landing in ROUTE_14|16,6 (a
                    # four-cell nook), while the run also walked east OUT of
                    # ROUTE_14|5,4 — the pocket that connects on to Route 15
                    # and Fuchsia. Keyed by direction alone, the second
                    # landing was dropped and `go` refused a road the run
                    # had walked. Keep both; the alternative rides under a
                    # suffixed key that _walk_route strips before crossing.
                    if (region, _back, _r2) in getattr(self, "_bad_seam",
                                                        ()):
                        continue           # the walk refuted this one
                    if _back not in out:
                        out[_back] = {"n": 0, "to": _r2, "inferred": True}
                    elif (out[_back] or {}).get("to") != _r2:
                        # NO COMMA IN THE KEY: a door key is "x,y" and half
                        # the executor tests for a comma to tell doors from
                        # seams — "west#ROUTE_14|5,4" tripped int() and
                        # killed the leg. The destination lives in the edge.
                        _alt = f"{_back}#alt"
                        while _alt in out and (out[_alt] or {}).get("to") != _r2:
                            _alt += "x"
                        out.setdefault(_alt, {"n": 0, "to": _r2,
                                              "inferred": True})
            return out

        _now = getattr(self, "_mark_now", None)
        seen, q = {frm} | set(avoid or ()), deque([(frm, [])])
        while q:
            cur, path = q.popleft()
            for key, e in edges(cur).items():
                nxt = e.get("to")
                if not nxt or nxt in seen:
                    continue
                # a hop that failed to land in THIS world state is not
                # routed again until the world moves (see _walk_route)
                if _now is not None and e.get("blocked_at") == _now:
                    continue
                hop = path + [(key, nxt)]
                if nxt == to or nxt in AREA_ALIASES.get(to, ()):
                    return hop
                seen.add(nxt)
                q.append((nxt, hop))
        return None

    def _cross_by_recall(self, obs, sg, dirname):
        """A seam you have crossed before is not a seam you cannot cross.

        `cross` is a single-map walk: it looks for a path over open ground
        from where you stand to the map's edge, and knows nothing about
        doors. Cerulean's south seam lives in a part of the city that can
        only be entered through a building, so from the main square the
        walk genuinely fails — while the ledger plainly holds the crossing,
        made from the other side. Recall is the whole point of the ledger:
        if some block of THIS map has that compass exit walked, route there
        over known ground and take it. Nothing new is assumed; the route is
        built from edges this run has already walked.
        """
        here = self._where(obs)
        mymap = here.split("|")[0]
        for block, exits in (self.explored or {}).items():
            if block == here or block.split("|")[0] != mymap:
                continue
            e = (exits or {}).get(dirname) or {}
            to = e.get("to")
            if not to or to == block or e.get("shut"):
                continue
            path = self._route(here, block)
            if not path:
                continue
            # THE EDGE UNDER OUR FEET WAS WRONG. If this compass crossing
            # had really worked from here, the walk would not have failed.
            # Cerulean records `20,0 east -> ROUTE_9` seven times because
            # each was made while the bush was cut and the city was one
            # component; regrown, it is false, and _route keeps choosing it
            # because it is the shortest path on paper. Drop it — it is a
            # conclusion about connectivity, not an observation, and it
            # re-records itself the moment it genuinely works again.
            _mine = (self.explored.get(here) or {}).get(dirname)
            if _mine and _mine.get("to") == to:
                del self.explored[here][dirname]
                self.log("edge_dropped_wrong_block", region=here,
                         exit=dirname, to=to, was=_mine.get("n"))
                self._save_memory()
            self.log("cross_by_recall", frm=here, via=block, dir=dirname,
                     to=to, hops=len(path))
            self._walk_route(sg, path)
            cur = self.settle() or obs
            if self._where(cur) != block:
                return None            # could not get to the crossing point
            return self._send_safe("cross", dir=dirname) or cur
        return None

    def _return_from_blackout(self, obs, sg):
        """Walk back to where the party fainted, over ground already walked.

        A gen1 blackout teleports you to a Center that can be several maps
        away — one wipe inside Mt Moon dumped the run at the VIRIDIAN centre,
        and it then spent 18 escalations shuffling around Route 2 trying to
        get back. The journey is pure navigation over the learned graph, so
        the harness drives it; the subgoal's rounds are for the part that
        needs judgment.
        """
        want = self._faint_at
        if not want:
            return None
        here = self._where(obs)
        if here == want:
            self._faint_at = None
            return None
        # RE-PLAN on a surprise instead of giving up. Ladders come in pairs
        # and a warp can resolve to the other end, so a hop landing somewhere
        # unexpected is normal — aborting there cleared the marker and left
        # the run stranded (wanted MT_MOON_B1F|24,14, got MT_MOON_1F|3,2).
        total = 0
        for attempt in range(4):
            here = self._where(self.settle() or {})
            if here == want or here in AREA_ALIASES.get(want, ()):
                self._faint_at = None
                self.log("blackout_return", subgoal=sg.get("id"), to=want,
                         hops=total, replans=attempt)
                return want
            path = self._route(here, want)
            if not path:
                # A respawn can land in a FRESH fingerprint of a known room
                # (a strolling Center NPC shifts the region id), whose
                # frontier and aliases have not been recorded yet — routing
                # from it then fails while the room plainly connects. Record
                # what we are standing in, rebuild aliases, try once more.
                cur = self.b.obs() or obs
                self.note_frontier(cur)
                self._rebuild_area_aliases()
                path = self._route(self._where(cur), want)
            if not path:
                # The graph can be INCOMPLETE rather than mis-keyed: the
                # party fainted on B2F having descended inside a macro, so
                # 1F->B1F was never recorded and no path to the exact room
                # existed — while the way back to the MAP was fully known.
                # Getting to the right floor is most of the return; the
                # rest is ordinary play. Aim at the nearest region of the
                # same map before giving up.
                want_map = want.split("|")[0]
                best = None
                for region in set(list(self.explored) + list(self.visits)):
                    if region.split("|")[0] != want_map or region == want:
                        continue
                    p = self._route(here, region)
                    if p and (best is None or len(p) < len(best)):
                        best, want = p, region
                if best:
                    self.log("blackout_return_partial",
                             subgoal=sg.get("id"), to=want, hops=len(best))
                    path = best
            if not path:
                self.log("blackout_return_noroute", subgoal=sg.get("id"),
                         frm=here, want=want)
                self._faint_at = None
                return None
            for key, nxt in path:
                # A wild encounter EATS a hop: the walk stops where the
                # battle started, and counting that as a mis-landing made
                # every replan retry the same first hop into the same
                # encounter rate until the four attempts were gone. The
                # escort re-sends an eaten hop (46dba87); so does this now.
                got = None
                for _resend in range(4):
                    pre_hop = self.b.obs()
                    if _is_door_key(key):
                        x, y = key.split(",")
                        self.b.send("use_warp", x=int(x), y=int(y))
                    else:
                        self.b.send("cross", dir=key)
                    o = self.settle()
                    fought = False
                    if o and o.get("mode") == "battle":
                        fought = True
                        o = self.handle_battle(sg, o)
                        o = self.settle()
                    # the walk back is real walking: record the doors used
                    if o and pre_hop and ((pre_hop.get("map") or {}).get("id")
                                          != (o.get("map") or {}).get("id")):
                        self.note_transition(
                            pre_hop,
                            {"x": int(key.split(",")[0]),
                             "y": int(key.split(",")[1])} if _is_door_key(key)
                            else {"dir": key}, o)
                    total += 1
                    got = self._where(o)
                    if got == nxt or got in AREA_ALIASES.get(nxt, ()):
                        break
                    if fought and got == self._where(pre_hop):
                        continue      # battle ate the hop: same room, retry
                    break             # a real mis-landing: leave the loop
                if got != nxt and got not in AREA_ALIASES.get(nxt, ()):
                    self.log("blackout_return_replan", subgoal=sg.get("id"),
                             wanted=nxt, got=got, attempt=attempt)
                    break          # re-plan from wherever we actually are
        self.log("blackout_return_lost", subgoal=sg.get("id"),
                 want=want, gave_up_after=total)
        self._faint_at = None
        return None

    def _uncork_seam(self, obs, sg, dirname):
        """A SEAM IS A ROW, NOT A DOOR: try another cell of the one we came
        in by.

        Crossing puts you on ONE cell of the far map's edge, and which cell
        decides what you can reach from it. Route 13's west crossing always
        landed on Route 14 row 6 — a one-tile corridor with a trainer whose
        movement is STAY parked four cells along it — so the reachable
        ground was four cells and the only way on was back the way we came.
        Ignoring people that map is one 486-cell area, and rows 4 and 8 of
        that same seam are open end to end. The run re-crossed into the
        pocket 93 times and read it as "the south is unreachable without
        FLY".

        Nothing here picks a destination. The direction stays the model's;
        which cell of a seam to walk to is pathfinding, like the route to
        it. Only fires from a pocket: one walked way out, and it is not the
        way the model asked to go.
        """
        _OPP = {"north": "south", "south": "north",
                "east": "west", "west": "east"}
        here = self._where(obs)
        mymap = here.split("|")[0]

        def _no(why, **kw):
            self.log("uncork_declined", where=here, asked=dirname, why=why,
                     **kw)
            return None
        if getattr(self, "_uncorking", False):
            return _no("already uncorking")
        key = (here, dirname)
        if key in getattr(self, "_uncorked", set()):
            return _no("tried once already this process")
        ways = {k: v for k, v in (self.explored.get(here) or {}).items()
                if (v or {}).get("to") and not (v or {}).get("shut")}
        if len(ways) != 1:
            return _no("not a pocket", ways=sorted(ways))
        back = next(iter(ways))
        if back not in _OPP or back == dirname:
            return _no("the one way out is not a compass seam to come back "
                       "through", back=back)
        self._uncorked = getattr(self, "_uncorked", set()) | {key}
        self._uncorking = True
        final = obs
        try:
            for skip in (1, 2, 3):
                cur = self.b.obs() or final
                if self._where(cur) != here:
                    break
                try:
                    o = self.b.send("cross", dir=back)
                except TimeoutError:
                    o = self.b.obs()
                o = self.settle() or o
                self.note_transition(cur, {"dir": back}, o, reason="uncork")
                final = o
                if self._where(o) == here:
                    break                      # could not even step out
                try:
                    o2 = self.b.send("cross", dir=_OPP[back], skip=skip)
                except TimeoutError:
                    o2 = self.b.obs()
                o2 = self.settle() or o2
                self.note_transition(o, {"dir": _OPP[back]}, o2,
                                     reason="uncork")
                final = o2
                land = self._where(o2)
                self.log("seam_cell_retried", frm=here, back=back, skip=skip,
                         landed=land, asked=dirname)
                if land.split("|")[0] != mymap:
                    break                      # the way back did not take
                if land != here:
                    return o2                  # a different landing: free
        finally:
            self._uncorking = False
        return final if self._where(final) != here else None

    def _route_to_frontier(self, obs, sg, patient: bool = False):
        """Walk back to the NEAREST region that still has exits never taken.

        Knowing where the unopened ladders are is useless if you cannot get
        there: reaching MT_MOON_1F from deep in B2F is several legs and
        escalation authors ONE leg per macro, so the model could never spend
        the knowledge. Navigation over already-walked ground is harness work
        (same as walk_to pathfinding inside a map) — the model still decides
        what to do on arrival."""
        here = self._where(obs)
        cur_map = (obs.get("map") or {}).get("id")
        # The walk-back OWNS the journey home. With a faint marker pending
        # the escort stole the trip — dragged the party two hops into the
        # mountain, the round then sat through a full inference mid-march,
        # and the walk-back finally armed from the wrong room. Defer.
        if self._faint_at:
            return None
        # Never walk out of a room that is still doing something. A gym has
        # ONE door, so "no untried exits" is true there every time — without
        # these guards the router would drag the run out of the Brock fight
        # mid-goal, which is the same mistake the revisit guard made.
        if f"{self._cur_target}|{here}" in self._battle_regions:
            return None
        # TRANSIT IS NOT WANDERING. This walk-back exists for searches;
        # for a travel goal, moving through fully-explored corridor rooms
        # IS the plan. Dragging the run back to a frontier every time it
        # crossed into ROUTE_3 pinned it to the Route 4 stub — 38
        # crossings, 38 walk-backs — with Pewter reachable the whole time.
        tgt = self._cur_target or ""
        # A TRAINING GOAL HAS NOWHERE TO WALK BACK TO. The frontier escort
        # exists to carry a search to unopened ground; a subgoal that needs
        # a level is not searching, and being dragged to the nearest room
        # with an untried door is being dragged out of the grass. Same
        # reasoning as the transit exemption directly below.
        if self._is_party_goal(tgt):
            return None
        if tgt.startswith(("map:", "area:")):
            dest = tgt.split(":", 1)[1]
            if "|" in dest:
                if self._route(here, dest):
                    return None
            else:
                for region in set(list(self.explored) + list(self.visits)):
                    if (region.split("|")[0] == dest
                            and self._route(here, region)):
                        return None
        # An untouched thing gets FIRST REFUSAL, not a veto. This gate
        # exists because a thing in a passage can be the blockage — but
        # Mt Moon's floors always hold a trainer or an item, so the escort
        # could never fire there and the run picked the wrong ladder round
        # after round with the right one named in its context. After a few
        # rounds in the same room the objects have had their chance.
        if not patient:
            tried_here = self._tried_objs.get(here, set())
            if [o for o in ((obs.get("map") or {}).get("objects") or [])
                    if o.get("reachable") and o.get("name") not in tried_here]:
                return None
        # LEAST-VISITED first, not nearest. Nearest is goal-blind: from the
        # Route 4 stub the closest region with unopened doors is PEWTER
        # CITY (six of them, two hops, and visited a dozen times), so the
        # escort marched AWAY from the frontier that mattered. Fresh ground
        # is where new ground is; distance only breaks ties.
        tgt = self._target_key(sg)
        # area: targets steer the same as map: — the region suffix is
        # dropped, the MAP is the compass
        want_map = (tgt.split(":", 1)[1].split("|")[0]
                    if tgt.startswith(("map:", "area:")) else None)
        if not want_map and tgt.startswith("badge:"):
            want_map = BADGE_GYMS.get(tgt.split(":", 1)[1])
        want_map = _doorstep(want_map) if want_map else None
        blocked = self._impassable()
        best = None
        for region, exits in self.frontier.items():
            if region == here:
                continue
            # A PROVEN SEAM IS NOT FRONTIER. The frontier deliberately
            # keeps a printed road after a failed crossing so one bad proof
            # cannot erode the map, but counting those as "never taken"
            # sends the walk-back to a region whose only opening is a wall
            # it has already bounced off — the same mistake 773bbc3 fixed
            # for the remote-region note and left standing here.
            fresh = self._frontier_left(region)
            if not fresh:
                # A FLOOR WITH DOORWAYS NOBODY HAS WALKED IS NOT FINISHED,
                # even when every ROOM in it reports its own exits taken.
                # Mt Moon's regions each said "nothing left" while two of
                # the eight doorways on B1F had never been used, so the
                # walk-back went to Pewter's shop doors instead of back
                # into the cave the run was trying to cross. Compare the
                # map's whole doorway list against every key taken anywhere
                # on it; the ferry ledger stops this being a loop.
                # A DOORWAY THAT REFUSED YOU IS NOT A DOORWAY YOU WALKED.
                # Attempts that went nowhere are recorded so they stop being
                # re-elected, but counting them here marked Mt Moon's east
                # EXIT (27,3, attempted once, went nowhere) as walked — the
                # one doorway that matters, hidden by the record of having
                # failed at it. Only a doorway that actually led somewhere
                # else counts as used.
                rmap0 = region.split("|")[0]
                seen_keys = set()
                for r2, ex2 in (self.explored or {}).items():
                    if r2.split("|")[0] != rmap0:
                        continue
                    seen_keys |= {k for k, e in ex2.items()
                                  if not (e or {}).get("shut")
                                  and (e or {}).get("to") != r2}
                # A ROOM WITH THINGS YOU HAVE NEVER TOUCHED IS ALSO
                # UNFINISHED. This walk-back only ever looked for untried
                # EXITS, so Mt Moon's fossil room — one exit, taken, and
                # five things nobody has pressed, including both fossils
                # and the trainer guarding them — was invisible to it. A
                # thing you have seen and not touched is exactly as good a
                # reason to walk somewhere as a door you have not opened.
                _seen_objs = set(self.sightings.get(region) or ())
                _done_objs = set(self._tried_objs.get(region) or ())
                if not (_seen_objs - _done_objs) and not (
                        set(self.map_doors.get(rmap0, ())) - seen_keys):
                    continue
            # ONE WASTED TRIP IS NOT A VERDICT. Excluding a region the
            # moment a single delivery went unused was too strong: the
            # harness ferried the run into Mt Moon, the model's next macro
            # walked it straight back out, and the cave — the best-scoring
            # candidate, with two ladders never taken — was then refused
            # for ever. Give it a second and third go before writing the
            # ground off; the count still stops the six-trip loop.
            been = (self._ferried.get(self._cur_target) or {}).get(region)
            if been and been[0] == frozenset(fresh) and been[1] >= 3:
                continue      # brought here 3x and nothing was ever used
            path = self._route(here, region)
            if path is None:
                continue
            # GOAL-WARD OUTRANKS FRESH. Least-visited alone drifts to the
            # periphery once the graph is dense: Route 25 read "fresh"
            # while the south pocket of Cerulean — visited constantly,
            # holding an untried south edge whose map connection IS the
            # target — read "stale", and the run walked to Bill's house
            # instead of Route 5. When a region's untried directional
            # edge leads to the target map per the atlas (geography this
            # run has itself observed), it comes first.
            # DISTANCE, not adjacency: score each untried exit by how many
            # printed-map legs remain after taking it, so the FIRST hop of
            # a long journey outranks a door that goes nowhere near.
            goalward = 99
            if want_map:
                rmap = region.split("|")[0]
                redges = dict((self.atlas.get(rmap) or {}).get("edges") or {})
                for d, m2 in (MAP_EDGES.get(rmap) or {}).items():
                    redges.setdefault(d, m2)
                goalward = self._goal_score(rmap, want_map, blocked)
                for e in fresh:
                    dest_m = redges.get(e)
                    if dest_m:
                        goalward = min(
                            goalward,
                            self._goal_score(dest_m, want_map, blocked))
            # WHEN THE GOAL IS SEALED, EVERY CANDIDATE SCORES THE SAME.
            # goalward is the primary key, but with Saffron unreachable
            # _goal_score returns its fallback for every region alike, so
            # the ranking collapsed to least-visited and the run toured
            # Route 22 and Route 23 while the goal sat east. Break that tie
            # with the tolled cost from HERE to the region: ground on the
            # way to the goal beats ground in the opposite corner, and
            # a shut door on the path is priced, not forbidden.
            toll = {b2: 4 + min(self._map_visits().get(b2[0], 0) // 8, 40)
                    for b2 in blocked}
            reach = static_cost(here.split("|")[0], region.split("|")[0],
                                toll, self._walked_map_links())
            # AMONG EQUALS, GO WHERE MOST IS LEFT UNDONE. The tiebreak
            # was path length, so a room one hop away with nothing in it
            # beat the fossil room three hops away with five untouched
            # things in it — both fossils and the trainer guarding them —
            # every single time. How much is left to do somewhere is a
            # better reason to walk there than how close it is.
            _undone = len(set(self.sightings.get(region) or ())
                          - set(self._tried_objs.get(region) or ()))
            rank = (goalward, reach if reach is not None else 99,
                    -_undone, self.visits.get(region, 0), len(path))
            if best is None or rank < best[2]:
                best = (region, path, rank)
        if not best or not best[1]:
            return None
        region, path = best[0], best[1]
        for key, nxt in path:
            # A wild encounter EATS the hop: the walk to the ladder is
            # interrupted, the battle resolves, and the party is standing
            # where it started with the op already spent. Mt Moon's
            # encounter rate meant the escort never completed a single leg
            # — every attempt logged reroute_lost from 1F wanting B1F|4,4.
            # Re-send while a battle keeps interrupting; give up only when
            # a clean pass still lands somewhere unexpected.
            o = None
            for _ in range(4):
                pre_hop = self.b.obs()
                if _is_door_key(key):
                    x, y = key.split(",")
                    self.b.send("use_warp", x=int(x), y=int(y))
                else:
                    self.b.send("cross", dir=key)
                o = self.settle()
                # A hop the ESCORT walked is still a door taken. Neither
                # this nor the blackout walk-back recorded anything, so
                # every exit they used stayed "untried" in the graph and
                # rooms they had shuttled through could never be finished.
                if o and pre_hop and ((pre_hop.get("map") or {}).get("id")
                                      != (o.get("map") or {}).get("id")):
                    self.note_transition(
                        pre_hop,
                        {"x": int(key.split(",")[0]),
                         "y": int(key.split(",")[1])} if _is_door_key(key)
                        else {"dir": key}, o)
                fought = False
                while o and o.get("mode") == "battle":
                    o = self.handle_battle(sg, o)
                    o = self.settle()
                    fought = True
                if self._where(o) == nxt or not fought:
                    break
            if self._where(o) != nxt:
                self.log("reroute_lost", subgoal=sg["id"], wanted=nxt,
                         got=self._where(o))
                return None
        # DELIVERING SOMEBODY SOMEWHERE CONSUMES THE TRIP, NOT THE GROUND.
        # A region stays maximally fresh however many times you are walked
        # into it — only TAKING one of its exits changes that — so Mt Moon,
        # with four unopened ladders, won this election six times in one
        # attempt while the party was ferried in and wandered back out.
        # Record which regions this target has already been delivered to,
        # keyed by what was untried when we arrived: if that set is
        # unchanged next time, the trip taught nothing and the region is
        # not a candidate again.
        _left = frozenset(
            e for e in (self.frontier.get(region) or [])
            if e not in set((self.explored.get(region) or {}).keys()))
        _seen = self._ferried.setdefault(self._cur_target, {})
        _prev = _seen.get(region)
        _seen[region] = (_left, (_prev[1] + 1) if _prev
                         and _prev[0] == _left else 1)
        # AND OPEN THE DOOR IT WAS BROUGHT FOR. Delivering the party to a
        # room with untried exits and stopping there achieved nothing: the
        # model's next macro walked straight back out to the road, nothing
        # was refused so no free round fired, and the walk-back simply did
        # it again. Choosing WHICH room to walk to is already the harness's
        # call; taking the exit that was the whole reason for the trip is
        # the same act finished, not a new decision.
        o_arr = self.settle()
        left = self._frontier_left(region)
        if left and o_arr:
            key = sorted(left)[0]
            pre = o_arr
            # A WILD ENCOUNTER IS NOT A CLOSED DOOR. walk_to gives up the
            # moment the game leaves the overworld, so in a cave with Mt
            # Moon's encounter rate a single-shot warp reports "couldn't
            # reach the warp tile" whenever a Zubat interrupts the walk —
            # and that got written down as a shut ladder. Fight what
            # interrupts and try the same door again, the way _walk_route
            # already does for routed hops.
            step = ({"x": int(key.split(",")[0]), "y": int(key.split(",")[1])}
                    if _is_door_key(key) else {"dir": key})
            r, o2 = None, None
            for _try in range(4):
                if _is_door_key(key):
                    r = self._send_safe("use_warp", **step)
                else:
                    r = self._send_safe("cross", dir=key)
                o2 = self.settle()
                fought = False
                while o2 and o2.get("mode") == "battle":
                    o2 = self.handle_battle(sg, o2)
                    o2 = self.settle()
                    fought = True
                det = str(((r or {}).get("result") or {}).get("detail") or "")
                if self._where(o2) != self._where(pre):
                    break
                if not (fought or "not in overworld" in det):
                    break
            _res0 = (r or {}).get("result") or {}
            if o2:
                self.note_transition(pre, step, o2,
                                     reason=str(_res0.get("detail") or ""))
            # WHY it did not fire, not just that it did not. These ops go
            # through _send_safe, which never reaches the trace builder, so
            # a door that refused the walk-back was invisible.
            # send() returns the OBSERVATION; the op's outcome is nested
            # under "result". Reading ok/detail off the observation gave
            # ok=False, detail=None for every attempt — a diagnostic that
            # reported failure whatever happened.
            _res = (r or {}).get("result") or {}
            self.log("reroute_opened", subgoal=sg["id"], via=key,
                     to=self._where(o2), ok=bool(_res.get("ok")),
                     detail=str(_res.get("detail"))[:140])
            region = self._where(o2) or region
        self.log("rerouted", subgoal=sg["id"], to=region, hops=len(path))
        return region

    @staticmethod
    def _through_buildings(cur) -> str:
        """A building with a door you can reach and a door you cannot IS
        a passage — the eye-fact a human reads off the screen (the
        trashed house straddling Cerulean's fence) stated from data the
        observation already carries: two warp tiles, same destination,
        different sides. No route knowledge, just the warp table."""
        by_dest: dict = {}
        for w in ((cur or {}).get("map") or {}).get("warps") or []:
            if w.get("dest"):
                by_dest.setdefault(w["dest"], []).append(w)
        out = ""
        for dest, ws in by_dest.items():
            r = [w for w in ws if w.get("reachable")]
            u = [w for w in ws if not w.get("reachable")]
            if r and u:
                out += (f"\nNOTE: {dest} has a door you can walk to "
                        f"({r[0].get('x')},{r[0].get('y')}) AND a door you "
                        f"cannot ({u[0].get('x')},{u[0].get('y')}) — a "
                        f"building with a far door is a way THROUGH: go in "
                        f"the near door and out the other side.")
        return out

    @staticmethod
    def _knows_move(obs, move: str) -> bool:
        """Does anyone in the party know that move? (party is on screen)"""
        for m in (obs or {}).get("party") or []:
            for mv in (m.get("moves") or []):
                if str(mv.get("id") if isinstance(mv, dict) else mv) == move:
                    return True
        return False

    def _walk_route(self, sg, path, _replans=0):
        """Replay a fully-walked route hop by hop (the escort's pattern):
        send the edge, settle, fight through interruptions, record the
        transition. Returns where the walk ended."""
        o = None
        # WHERE A WIDE SEAM LANDS DEPENDS ON WHERE YOU CROSS IT, so a hop
        # can put you in a different pocket of the right map than the path
        # expected. Keep the destination and re-plan from where we actually
        # are rather than declaring the road lost.
        _final = path[-1][1] if path else None
        # A ROUTE STEP BELONGS TO THE PLACE IT WAS COMPUTED FROM. `pre` is
        # re-read every hop, so it always says where the party ACTUALLY is,
        # while `key` still names a tile from where the party WAS — and
        # nothing checked the two agree. Twice in one run that fired a
        # step at the map the party had just left, from inside the room it
        # had just entered: MT_MOON_POKECENTER got Route 4's door (18,5)
        # and UNDERGROUND_PATH_ROUTE_5 got Route 5's (10,29). Both bounced
        # straight back out, both recorded their exit under a foreign key,
        # and both ended with NO exits in the ledger at all — so the
        # Underground Path, the only road to Vermilion that is not gated
        # behind the Saffron guards, reads as a room that goes nowhere.
        # Distilled macros already carry `when: {map}` for exactly this,
        # "so a diverged trajectory SKIPS misplaced ops instead of
        # misfiring them"; route walking had no such guard.
        for key, nxt in path:
            _now = self.b.obs() or {}
            _m = (_now.get("map") or {})
            # A LIFT HOP: ride the panel to that floor, then walk out of the
            # car. The label is the floor's own (5F, B4F, ROOF), which is
            # how the panel lists it and how the elevator op takes it.
            if str(key).startswith("lift:"):
                _want_map = key.split(":", 1)[1]
                _lab = _re.search(r"(B?\d+F|ROOF)$", _want_map)
                _lab = _lab.group(1) if _lab else None
                if not _lab:
                    self.log("route_abandoned", subgoal=sg.get("id"),
                             step=str(key), standing=self._where(_now),
                             why="no floor label in that map id")
                    return o if o is not None else _now
                self._send_safe("elevator", floor=_lab)
                o = self.settle() or _now
                # out of the car by whichever of its doors is reachable
                for _w in ((o.get("map") or {}).get("warps") or []):
                    if _w.get("reachable"):
                        self._send_safe("use_warp", x=_w.get("x"),
                                        y=_w.get("y"))
                        o = self.settle() or o
                        break
                if self._where(o) != nxt and (o.get("map") or {}).get("id") \
                        != _want_map:
                    self.log("route_abandoned", subgoal=sg.get("id"),
                             step=str(key), standing=self._where(o),
                             why="the lift did not put us on that floor")
                    return o
                continue
            # AN INTRA-MAP HOP IS A WALK, not a door and not a seam. It
            # is recorded by _note_intra when the party walks from one
            # component of a map into another (down a ledge, through a
            # gap), and it is the only way a ledge-split route like Route 9
            # is connected at all.
            if str(key).startswith("walk:"):
                _want = str(key).split(":", 1)[1]
                try:
                    _ax, _ay = (int(v) for v in
                                _want.split("|", 1)[1].split(","))
                except (ValueError, IndexError):
                    self.log("route_abandoned", subgoal=sg.get("id"),
                             step=str(key), standing=self._where(_now),
                             why="that walked-to area has no anchor cell")
                    return o if o is not None else _now
                self._send_safe("walk_to", x=_ax, y=_ay)
                o = self.settle() or _now
                while o and o.get("mode") == "battle":
                    o = self.handle_battle(sg, o)
                    o = self.settle()
                if self._where(o) != nxt:
                    self.log("route_abandoned", subgoal=sg.get("id"),
                             step=str(key), standing=self._where(o),
                             why="the walk across this map did not arrive")
                    return o
                continue
            if _is_door_key(key):
                _x, _y = (int(v) for v in key.split(","))
                _has = any(w.get("x") == _x and w.get("y") == _y
                           for w in (_m.get("warps") or []))
            else:
                _has = str(key).split("#", 1)[0] in (_m.get("connections") or {})
            if _m.get("id") and not _has:
                self.log("route_abandoned", subgoal=sg.get("id"),
                         step=str(key), standing=self._where(_now),
                         why="this map has no such way out")
                return o if o is not None else _now
            # A WILD BATTLE IS NOT A FAILED HOP. Four tries was the cap and
            # a wild encounter spent one: in Mt Moon the walk to the fossil
            # room's ladder was jumped by a Paras and three Zubat in a row,
            # fled each, and on the fourth the hop was declared lost — and
            # the edge voided (see below). Each retry resumes from where the
            # party stands, so an interrupted walk is only more walk. Retry
            # while a battle was the interruption and the party is still
            # getting somewhere; give up after two tries that moved nothing.
            _stuck = 0
            _last_pos = None
            for _ in range(12):
                pre = self.b.obs()
                _sf = bool(getattr(self, "_go_surf", False))
                if _is_door_key(key):
                    x, y = key.split(",")
                    _res = self._send_safe("use_warp", x=int(x), y=int(y))
                    step = {"x": int(x), "y": int(y)}
                else:
                    _dirk = str(key).split("#", 1)[0]
                    _res = (self._send_safe("cross", dir=_dirk, surf=True)
                            if _sf else self._send_safe("cross", dir=_dirk))
                    step = {"dir": _dirk}
                o = self.settle()
                # KEEP THE OP'S OWN VERDICT. settle() overwrites result with
                # its own, so "crossed mid-walk (door unknown)" was thrown
                # away here and the walk filed an edge for a tile it never
                # stood on — the Day Care door recorded as leading to the
                # Route 5 gate, seven times in a row, from the lane that
                # cannot reach that tile at all.
                _det = ((_res or {}).get("result") or {}).get("detail") or ""
                # A REGROWN BUSH ON A ROAD YOU HAVE WALKED IS NOT A NEW
                # OBSTACLE. Bushes come back whenever the game reloads, so a
                # route recorded through one fails on the way back and the
                # run "abandons" a road it opened itself. Cutting it is
                # re-opening a walked way — the same class as re-walking a
                # walked door. An unwalked bush somewhere new is untouched.
                if ("CUT_TREE" in _det and self._where(o) != nxt
                        and self._knows_move(o or {}, "CUT")):
                    _mm = _re.search(r"CUT_TREE[^()]*\((\d+),(\d+)\)", _det)
                    if _mm:
                        self.log("route_cut", subgoal=sg.get("id"),
                                 at=f"{_mm.group(1)},{_mm.group(2)}",
                                 step=str(key))
                        self._send_safe("field_move", move="CUT",
                                        x=int(_mm.group(1)),
                                        y=int(_mm.group(2)))
                        o = self.settle() or o
                        continue
                if o and pre and ((pre.get("map") or {}).get("id")
                                  != (o.get("map") or {}).get("id")):
                    self.note_transition(pre, step, o, op_detail=_det)
                fought = False
                while o and o.get("mode") == "battle":
                    o = self.handle_battle(sg, o)
                    o = self.settle()
                    fought = True
                if self._where(o) == nxt or not fought:
                    break
                _pos_now = (self._where(o), self._pos(o))
                _stuck = _stuck + 1 if _pos_now == _last_pos else 0
                _last_pos = _pos_now
                if _stuck >= 2:
                    break                    # fought, and went nowhere twice
            if self._where(o) != nxt and "," not in key:
                # A directional edge can be TRUE from one part of a region
                # and unwalkable from another (Cerulean's south is crossed
                # from the strip beyond the fence, not from the north
                # city). Before declaring the hop lost, walk THROUGH a
                # passage building — one with a door we can reach and a
                # door we cannot — and press the cross again from its far
                # side. Same eye-fact as the through-building note, made
                # into legs.
                o = self._passage_retry(sg, key, o)
            if (self._where(o) != nxt and _final and _replans < 2
                    and str(nxt).split("|")[0]
                    == str(self._where(o)).split("|")[0]):
                # ...ONCE, AND NEVER BACK INTO THE SAME HOP. The budget
                # has to travel with the recursion or the walk ping-pongs
                # (983 re-plans in one leg: mislanded, re-planned, drew the
                # same route, mislanded again). A re-plan whose first hop is
                # the one that just mislanded from here is the loop itself.
                _rest = self._route(self._where(o), _final)
                if (_rest and _replans < 1
                        and not (self._where(o) == self._where(pre)
                                 and _rest[0][0] == key)):
                    self.log("route_replanned", subgoal=sg.get("id"),
                             landed=self._where(o), wanted=nxt,
                             legs=len(_rest))
                    return self._walk_route(sg, _rest, _replans + 1)
            if self._where(o) != nxt:
                # A hop that fails to land even after the passage retry
                # CONTRADICTS the recorded edge: void it, or the router
                # re-picks the phantom forever (a blackout walk-back
                # minted a phantom and fifteen straight walks died on it).
                frm = self._where(pre)
                rec = (self.explored.get(frm) or {}).get(key)
                if rec and rec.get("to") == nxt:
                    if int(rec.get("n") or 0) >= 1:
                        # A WALKED EDGE IS NOT A PHANTOM. Voiding was written
                        # for edges minted by a blackout walk-back that never
                        # existed; applied to an edge the run had actually
                        # walked, one failed hop (a wanderer in the corridor,
                        # a script, a battle mid-walk) deleted the route —
                        # four true edges in one morning, including the
                        # fossil room's way out, and the auto-walk to
                        # Cerulean stopped existing. Blocked for NOW: the
                        # router skips it while the world mark stands, and
                        # it is a road again the moment anything changes.
                        rec["blocked_at"] = self._world_mark(o)
                        self.log("edge_blocked", frm=frm, via=key, to=nxt,
                                 n=rec.get("n"))
                    else:
                        del self.explored[frm][key]
                        self.log("edge_voided", frm=frm, via=key, to=nxt)
                elif not rec:
                    # ...BUT FIRST, TRY ANOTHER CELL OF THAT SEAM. Landing
                    # on the wrong pocket of the right map is the seam-row
                    # problem, not a false connection: Route 11's east
                    # crossing lands in ROUTE_12|0,61, a pocket whose only
                    # exit is back west, while the component that reaches
                    # Lavender and everything past it is further along the
                    # same edge. Step back out and re-cross elsewhere; only
                    # if that finds nothing is the inference itself wrong.
                    # ...ONLY FOR A SEAM. This branch fires for any hop,
                    # and a door key ("18,9") is not a direction to re-cross
                    # at another cell: the first decline logged was exactly
                    # that, Saffron's door asked of a seam routine.
                    _dk = str(key).split("#", 1)[0]
                    _un = (self._uncork_seam(o, sg, _dk)
                           if _dk in ("north", "south", "east", "west")
                           else None)
                    if _un is not None and _replans < 1:
                        _rest2 = self._route(self._where(_un), _final)
                        if _rest2:
                            self.log("route_after_uncork",
                                     subgoal=sg.get("id"),
                                     frm=self._where(_un), legs=len(_rest2))
                            return self._walk_route(sg, _rest2, _replans + 1)
                    # AN INFERENCE THE WORLD JUST REFUTED. Reverse-seam and
                    # wide-seam alternates are SYNTHESIZED in _route.edges()
                    # on every call, so there is no record here to void —
                    # and the router re-minted "cross west from Route 13
                    # into ROUTE_14|5,4" every round while every walk landed
                    # in the nook at 16,6 instead. `go` failed identically
                    # for as long as the leg ran. An inference is a
                    # conclusion about connectivity, not an observation:
                    # when the walk contradicts it, drop it for good. The
                    # crossing itself stays walkable and re-records the
                    # moment it genuinely lands there.
                    self._bad_seam.add(
                        (frm, str(key).split("#", 1)[0], str(nxt)))
                    self.log("inference_refused", frm=frm, via=key, to=nxt,
                             landed=self._where(o))
                    self._save_memory()
                self.log("route_walk_lost", subgoal=sg["id"], wanted=nxt,
                         got=self._where(o))
                return self._where(o)
        self.log("route_walked", subgoal=sg["id"], to=self._where(o),
                 hops=len(path))
        return self._where(o)

    def _passage_retry(self, sg, key, o):
        """Walk through a passage building (reachable door + unreachable
        door, same destination) and press the failed directional cross
        again from the far side. Mechanics only: the building and its
        doors are in the observation; which cross to press was already
        decided by the route being walked."""
        m = (o or {}).get("map") or {}
        by_dest = {}
        for w in m.get("warps") or []:
            if w.get("dest"):
                by_dest.setdefault(w["dest"], []).append(w)
        gate = None
        for dest, ws in by_dest.items():
            r = [w for w in ws if w.get("reachable")]
            u = [w for w in ws if not w.get("reachable")]
            if r and u:
                gate = r[0]
                break
        if not gate:
            self.log("passage_retry", subgoal=sg["id"], result="no gate")
            return o
        self.log("passage_retry", subgoal=sg["id"], gate=gate.get("dest"),
                 door=f"{gate['x']},{gate['y']}", result="trying")
        outer = m.get("id")
        self._send_safe("use_warp", x=gate["x"], y=gate["y"])
        o2 = self.settle()
        inner = ((o2 or {}).get("map") or {})
        if inner.get("id") == outer:
            self.log("passage_retry", subgoal=sg["id"],
                     result="never entered")
            return o2
        doors = [w for w in inner.get("warps") or [] if w.get("reachable")]
        for w in doors:
            # every test exits the building, so RE-ENTER before trying the
            # next interior door — the first version pressed interior
            # coordinates while standing outside and silently did nothing
            cur = ((self.b.obs() or {}).get("map") or {}).get("id")
            if cur == outer:
                self._send_safe("use_warp", x=gate["x"], y=gate["y"])
                o2 = self.settle()
                if (((o2 or {}).get("map") or {}).get("id")) == outer:
                    break
            self._send_safe("use_warp", x=w["x"], y=w["y"])
            o3 = self.settle()
            if ((o3 or {}).get("map") or {}).get("id") == outer:
                pre2 = o3
                self._send_safe("cross", dir=key)
                o4 = self.settle()
                while o4 and o4.get("mode") == "battle":
                    o4 = self.handle_battle(sg, o4)
                    o4 = self.settle()
                if ((o4 or {}).get("map") or {}).get("id") != outer:
                    self.log("passage_crossed", subgoal=sg["id"],
                             via=f"{gate['dest']}+{key}",
                             to=self._where(o4))
                    self.note_transition(pre2, {"dir": key}, o4)
                    return o4
                o2 = o4 or o2
        self.log("passage_retry", subgoal=sg["id"],
                 result="no far side worked")
        return o2

    def _map_visits(self) -> dict:
        out: dict = {}
        for r, n in self.visits.items():
            m = r.split("|")[0]
            out[m] = out.get(m, 0) + n
        return out

    def _impassable(self) -> frozenset:
        """EDGES we have hammered and never crossed, as (from, to) pairs.

        Saffron is the case: stood in Route 6 and Route 5 (and their
        gates, 86 and 8 times) and SAFFRON_CITY still has zero visits —
        the thirsty guards, whose own words are in the hint ledger. This
        is CURRENT evidence, not the stale failure tallies, and it clears
        itself the moment the road opens.

        EDGE-level, not map-level, and the difference decides the run:
        marking whole MAPS shut sealed Lavender (Snorlax blocks it from
        Route 12) and the ranking then preferred the giant western
        Cycling-Road loop as "shorter". Route 12 cannot reach Lavender;
        ROUTE_10 reaches it fine, and only an edge-shaped fact can say
        both. Route 9 -> Route 10 stays open because Route 9 has barely
        been walked — the whole difference between 'shut' and 'not tried'.
        """
        vis = self._map_visits()
        return frozenset(
            (m, nb) for m, edges in MAP_EDGES.items()
            for nb in edges.values()
            # A ROAD SPLIT BY A CAVE CANNOT BE JUDGED THIS WAY. Standing on
            # Route 4's west side a hundred times says nothing about its
            # east seam, which is past Mt Moon — and calling that edge shut
            # tolled the whole area so heavily that Pewter's shop doors
            # outranked the cave the run was trying to cross.
            if m not in SPLIT_ROADS
            and vis.get(m, 0) >= 8 and not vis.get(nb))

    def _goal_score(self, from_map: str, want: str, blocked) -> int:
        """What it COSTS to get to the goal from here — one number, always.

        This used to answer on three scales: a bare hop count when an open
        road existed, 50+ for "nearest ground never set foot on" when it
        did not, and 80+ for a tolled route. Every one of them degenerated
        the same way — with the goal sealed, every candidate got the same
        fallback and the ranking became a coin flip, which is how a run
        aiming at Saffron toured Route 22 and Route 23 in the far west.

        A tolled route never needs a fallback. A shut door is expensive,
        not impassable, so there is always an answer and it always
        discriminates: the cheapest way to a sealed city is the door it
        has leaned on least, and ground on the way there scores better
        than ground in the opposite corner. With nothing shut on the path
        the toll is zero and this is exactly the old hop count — verified
        equal for all 36x36 printed-map pairs.
        """
        vis = self._map_visits()
        toll = {b: 4 + min(vis.get(b[0], 0) // 8, 40) for b in blocked}
        # An interior is not a node on the printed map, so asking its
        # distance returned the worst score for everywhere alike — the
        # inside of a cave rated worse than the road outside it, whichever
        # way the run was going. Score it as the road it opens off.
        from_map = _doorstep(from_map)
        h = static_cost(from_map, want, toll, self._walked_map_links())
        if h is not None:
            return h
        # Not on the printed map at all (an interior with no doorstep, or
        # a map id this run has never had an edge for): fall back to the
        # nearest unvisited ground, which is the honest "go and look".
        best = None
        for m in MAP_EDGES:
            if vis.get(m):
                continue
            hh = static_cost(from_map, m, toll, self._walked_map_links())
            if hh is not None and (best is None or hh < best):
                best = hh
        return 50 + best if best is not None else 99

    def _walked_map_links(self) -> dict:
        """Map-to-map connections this run has personally walked.

        The learned graph is region-to-region and includes every door;
        collapsed to map level it is the printed map PLUS the tunnels the
        town map does not draw — which is how the underground path reaches
        the ranking at all.
        """
        out: dict = {}
        for region, exits in (self.explored or {}).items():
            src = region.split("|")[0]
            for e in (exits or {}).values():
                dst = str((e or {}).get("to") or "").split("|")[0]
                if dst and dst != src:
                    out.setdefault(src, set()).add(dst)
        return out

    def _fought_at(self, tgt: str, obs, step, dest_map: str) -> bool:
        """Did a fight happen in the REGION this exit leads to?

        Battle rooms are exempt from the revisit refusal, but keying that
        exemption to the MAP meant one Rocket fight anywhere in Mt Moon B2F
        exempted every region of B2F — so the run was free to keep dropping
        back into the dead-end rooms instead of the ladder it had never
        opened. The learned graph knows which region the door leads to; use
        it when it does, and fall back to the coarse test when it does not.
        """
        known = (self.explored.get(self._where(obs), {}) or {}).get(
            f"{step.get('x')},{step.get('y')}")
        dest_region = (known or {}).get("to")
        if dest_region:
            return f"{tgt}|{dest_region}" in self._battle_regions
        return any(k.startswith(f"{tgt}|{dest_map}|")
                   for k in self._battle_regions)

    def _leave_ui(self, obs, sg, tries: int = 6):
        """Back out of a UI the goal never asked for.

        Pressing A on everything is how blocking objects get found, but it
        also walks into menus with no bearing on the goal — the Cable Club
        receptionist opens "we have to save the game" and campaign attempt 1
        sat in that prompt for 23 escalations. Telling the model to answer it
        did not work; backing out is harness hygiene, like settle().
        """
        # PATIENCE FIRST. A prompt the model has not had a turn to answer
        # may be the one it WANTS — pressing B on "Do you want the DOME
        # FOSSIL?" answers No and silently loses the item that opens Mt
        # Moon's corridor. Only back out of a UI that survived a round with
        # the model already told a prompt is open.
        text = (obs or {}).get("recent_text")
        self.log("ui_seen", subgoal=sg.get("id"), text=str(text)[:160],
                 pending=self._ui_pending)
        # A LEVEL-UP MOVE LIST NEEDS NO PATIENCE: it is unambiguous, it is
        # the model's choice, and every round it stays open is a round of
        # ops failing "a box was up". Put it to the model at once.
        _ui0 = (obs or {}).get("ui") or {}
        if ((obs or {}).get("mode") == "ui"
                and _ui0.get("screenId") == "MoveLearnMenu"
                and _ui0.get("selecting")):
            obs = self._maybe_forget(obs, sg)
            if (obs or {}).get("mode") != "ui":
                self._ui_pending = 0
                return obs
        if self._ui_pending < 1:
            self._ui_pending += 1
            return obs
        # ASK THE ONE WHO IS PLAYING. Backing out is safe for a menu nobody
        # asked for, but a yes/no box is a DECISION, and pressing B is an
        # answer — "No" to the Dome Fossil, "No" to a gift, "No" to a gate
        # opening. It went the other way too: `answer="yes"` rode along on
        # 302 of 560 interacts as boilerplate (it was attached to signposts
        # and to a CUT_TREE), and on the DAY-CARE MAN that reflex boarded a
        # level 40 CHARIZARD. Neither a blind yes nor a blind no is the
        # model's judgement. The words are on screen; hand them over and
        # use whatever comes back. Measured cost: a question box is rare —
        # 2 in 15,347 records of a full day's run — so this is a handful of
        # calls per playthrough, not a tax on every step.
        if self._is_question(obs):
            ans = self._ask_question(obs, sg, text)
            if ans is not None:
                self.b.send("tap", btn=("a" if ans else "b"))
                obs = self.settle() or obs
                self.log("question_answered", subgoal=sg.get("id"),
                         text=str(text)[:200], answer=("yes" if ans else "no"),
                         mode=(obs or {}).get("mode"))
                self._ui_pending = 0
                obs = self._maybe_forget(obs, sg)
                return obs
        n = 0
        while obs and obs.get("mode") == "ui" and n < tries:
            self.b.send("tap", btn="b")
            obs = self.settle() or obs
            n += 1
        if n:
            self.log("ui_dismissed", subgoal=sg.get("id"), presses=n,
                     text=str(text)[:160], mode=(obs or {}).get("mode"))
        self._ui_pending = 0
        return obs

    FORGET_SYS = (
        "You are playing Pokemon Red. One of your Pokemon has levelled up "
        "and is trying to learn a new move, but it already knows four. The "
        "game is asking WHICH move to forget. Choose the way the player you "
        "are would, given what you are trying to do. HM moves (CUT, FLY, "
        "SURF, STRENGTH, FLASH) cannot be forgotten. Reply with a JSON "
        "object and nothing else: {\"why\":\"<one short sentence>\","
        "\"forget\":\"<one of the moves it knows>\"} — or "
        "{\"why\":\"...\",\"forget\":null} to keep its four moves and "
        "not learn the new one.")

    def _maybe_forget(self, obs, sg):
        """A level-up move list on screen: ask the model which move goes,
        press it, and return the settled observation. The choice is the
        model's; the harness only carries it. Falls back to keeping the
        old moves (abandon) if the model cannot be understood, and says so.
        """
        ui = (obs or {}).get("ui") or {}
        if not ((obs or {}).get("mode") == "ui"
                and ui.get("screenId") == "MoveLearnMenu"
                and ui.get("selecting")):
            return obs
        moves = [str(m) for m in (ui.get("moves") or [])]
        new = str(ui.get("new_move") or "?")
        who = str(ui.get("learner") or "your Pokemon")
        user = (f"{who} is trying to learn {new}. It knows: "
                + ", ".join(f"{i}={m}" for i, m in enumerate(moves, 1))
                + f".\nWHAT YOU ARE TRYING TO DO RIGHT NOW: "
                  f"{sg.get('goal_text') or sg.get('id') or 'make progress'}\n"
                  "Which move should be forgotten for it, if any?")
        choice = None
        why = ""
        try:
            reply = brock_probe.chat(
                [{"role": "system", "content": self.FORGET_SYS},
                 {"role": "user", "content": user}], self.model)
            m = _re.search(r"\{.*\}", reply or "", _re.S)
            d = json.loads(m.group(0)) if m else {}
            why = str(d.get("why") or "")[:200]
            f = d.get("forget")
            if f is not None:
                f = str(f).upper().replace(" ", "_")
                choice = f if f in moves else None
                if choice is None:
                    self.log("forget_unparsed", subgoal=sg.get("id"),
                             said=str(f)[:60], moves=moves)
            else:
                choice = None
        except Exception as e:
            self.log("forget_chat_error", subgoal=sg.get("id"), err=str(e))
        self.log("move_forget", subgoal=sg.get("id"), learner=who, new=new,
                 forget=choice, why=why)
        if choice:
            idx = moves.index(choice) + 1
            r = self.b.send("menu", index=idx)
            cur = self.settle() or r or obs
            # an HM refusal leaves the list open with the game's line up
            _u2 = (cur or {}).get("ui") or {}
            if _u2.get("screenId") == "MoveLearnMenu" and _u2.get("selecting"):
                self.log("move_forget_refused", subgoal=sg.get("id"),
                         forget=choice)
                self.b.send("menu", index=len(moves) + 1)     # CANCEL
                cur = self.settle() or cur
                if self._is_question(cur):                    # abandon? yes
                    self.b.send("tap", btn="a")
                    cur = self.settle() or cur
            return cur
        # keep the old moves: CANCEL, then "Abandon learning X?" -> yes
        self.b.send("menu", index=len(moves) + 1)
        cur = self.settle() or obs
        if self._is_question(cur):
            self.b.send("tap", btn="a")
            cur = self.settle() or cur
        return cur

    @staticmethod
    def _is_question(obs) -> bool:
        """A yes/no box, as opposed to a menu or an info screen.

        Same shape the shim tests with ui_is_choice: a cursor index and no
        item list. A menu (bag, party, the PC) carries items and is NOT a
        question — those the model opened on purpose and drives itself.
        """
        if (obs or {}).get("mode") != "ui":
            return False
        ui = (obs or {}).get("ui") or {}
        # the shim decides this now: `items` is a table and never survived
        # into the observation, so "no items" was true of every screen.
        return bool(ui.get("is_choice"))

    QUESTION_SYS = (
        "You are playing Pokemon Red. The game has stopped on a YES/NO "
        "question and is waiting for your answer. Answer it the way the "
        "player you are would answer it, given what you are trying to do. "
        "Reply with a JSON object and nothing else: "
        "{\"why\":\"<one short sentence>\",\"answer\":\"yes\"} "
        "or {\"why\":\"...\",\"answer\":\"no\"}."
    )

    def _ask_question(self, obs, sg, text):
        """Put the open question to the model and return True/False/None.

        None means it could not be asked or could not be understood — the
        caller then falls back to backing out, which is what happened
        before this existed.
        """
        words = str(text or "").strip()
        if not words:
            return None
        cur = obs or {}
        party = ", ".join(
            f"{m.get('species')} L{m.get('level')}"
            for m in (cur.get("party") or [])) or "no Pokemon"
        bag = ", ".join(sorted((cur.get("bag") or {}).keys())) or "an empty bag"
        dc = cur.get("daycare") or {}
        where = ((cur.get("map") or {}).get("id")
                 or (cur.get("map") or {}).get("name") or "somewhere")
        user = (
            f"THE QUESTION ON SCREEN:\n\"{words}\"\n\n"
            f"WHERE YOU ARE: {where}\n"
            f"WHAT YOU ARE TRYING TO DO RIGHT NOW: "
            f"{sg.get('goal_text') or sg.get('id') or 'make progress'}\n"
            f"YOUR PARTY: {party}\n"
            f"YOUR BAG: {bag}\n"
            + (f"AT THE DAY CARE: {dc.get('species')} L{dc.get('level')}, "
               f"costs {dc.get('cost')} to collect\n" if dc.get("species")
               else "")
            + "\nSaying yes and saying no both DO something and neither can "
              "be taken back by walking away. Answer it.")
        try:
            reply = brock_probe.chat(
                [{"role": "system", "content": self.QUESTION_SYS},
                 {"role": "user", "content": user}], self.model)
        except Exception as e:
            self.log("question_chat_error", subgoal=sg.get("id"), err=str(e))
            return None
        m = _re.search(r"\{.*\}", reply or "", _re.S)
        if not m:
            self.log("question_unparsed", subgoal=sg.get("id"),
                     reply=str(reply)[:300])
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            self.log("question_unparsed", subgoal=sg.get("id"),
                     reply=str(reply)[:300])
            return None
        a = str(d.get("answer") or "").strip().lower()
        if a not in ("yes", "no"):
            self.log("question_unparsed", subgoal=sg.get("id"),
                     reply=str(reply)[:300])
            return None
        self.log("question_asked", subgoal=sg.get("id"), text=words[:200],
                 answer=a, why=str(d.get("why") or "")[:200])
        return a == "yes"

    def _fired_text(self, obs, sg) -> str:
        """The events this run has watched fire, when it is stuck on one.

        author.py already settles the principle — "the only flags the
        PROMPT volunteers are the ones this run has watched fire" — and the
        LEG AUTHOR gets them under WHERE EVENTS ACTUALLY FIRED. The
        escalation, which is the thing actually deciding what to do next
        while a flag refuses to set, was shown none of them: `EVENT_` did
        not appear once in a 5,570-character prompt.

        It cost a leg. Stuck on EVENT_GOT_POKEBALLS_FROM_OAK, the run's own
        history already held

            EVENT_ROUTE22_RIVAL_WANTS_BATTLE   fired in OAKS_LAB|4,1

        which is the game's own record that somebody is waiting on Route 22
        — and the flag that gates the balls is exactly "beat that rival".
        This is recall, not a walkthrough: every line is something this run
        did and was told about at the time, and no flag is named that has
        not fired. What any of them MEANS stays the model's own knowledge,
        which is the same line author.py draws.

        Only rendered when the subgoal is waiting on a flag; otherwise it
        is noise, and space in this prompt is the budget.
        """
        if "flag" not in pred_keys(sg.get("done_when") or {}):
            return ""
        # ...AND ONLY WHAT IS STILL TRUE. flag_sites is persisted memory and
        # the SAVE CAN ROLL BACK under it: an attempt that reloads an
        # earlier save leaves the ledger holding events the current world
        # has not seen. Measured minutes after this block first shipped —
        # five of ten, including GOT_POKEDEX and OAK_GOT_PARCEL, recorded
        # as fired while the live save had neither. Volunteering those
        # would tell the run it holds a Pokedex it does not have, which is
        # the same shape as the deed ledger outliving its world.
        # The live observation is the authority on what is SET; flag_sites
        # only supplies where it happened.
        live = set((obs or {}).get("flags") or [])
        rows = [f"  {f} (fired in {where})"
                for f, where in reversed(list(
                    (self.flag_sites or {}).items()))
                if f in live]
        if not rows:
            return ""
        return ("\n\nEVENTS THIS RUN HAS ALREADY WATCHED FIRE, newest "
                "first — the condition you are waiting on has not, and one "
                "of these may be what it is waiting BEHIND:\n"
                + "\n".join(rows[:12]))

    def _logged_exploration(self, obs, sg) -> str:
        txt = self.exploration_text(obs, self._target_key(sg), sg) \
            + self._fired_text(obs, sg)
        self.log("escalate_context", subgoal=sg["id"],
                 target=self._target_key(sg), memory=txt[:6000])
        return txt

    def training_text(self, obs, target: str = "") -> str:
        """What to say when the condition is satisfied by FIGHTING.

        Everything exploration_text says is advice for finding a place or a
        thing, and handed to a level goal it argues against the only action
        that can succeed — see PARTY_TARGETS. This says the opposite, out
        of the same evidence: what the party is, how far off the condition
        is, and that standing still and battling is the move.

        No map knowledge is smuggled in. Where the grass is on this floor
        is not stated because the observation does not carry it; the grind
        op walks to it, which is mechanics the run already owns.
        """
        dw_val = target.split(":", 1)[1] if ":" in target else ""
        kind = target.split(":", 1)[0]
        party = (obs or {}).get("party") or []
        # ...and for a CATCHING goal, where you stand decides what you
        # meet, so "walking somewhere new is not progress" is false of it.
        if kind in ("party_size", "has_species", "party_type", "dex_owned"):
            lines = [f"\nTHIS IS NOT SOMEWHERE TO GO — IT IS SOMETHING TO "
                     f"BECOME. The condition is {kind} {dw_val}, and no "
                     f"door satisfies it. But WHERE YOU STAND DECIDES WHAT "
                     f"YOU MEET: the wild ground on this floor (grass, or "
                     f"a cave's every tile) holds what it holds, and if it "
                     f"never offers the right creature, the answer is "
                     f"different ground, not more of this."]
            # AND YOU CANNOT CATCH ANYTHING WITHOUT A BALL. The harness's
            # own catch policy already refuses to throw one it does not
            # have, so this is not game knowledge being handed over — it is
            # the harness stating a rule it is already enforcing, at the
            # only moment the run can act on it.
            # Watched live: a clean-room run met twelve wilds under the
            # catch policy carrying OAK'S PARCEL, 3,175 money and no balls.
            # With no ball and no named species it falls through to move
            # scoring and KOs everything, so the condition can never come
            # true however long it grinds — and nothing said so.
            _bag = (obs or {}).get("bag") or {}
            _balls = sum(n for k, n in _bag.items() if k.endswith("_BALL"))
            if not _balls:
                lines.append(
                    f"YOU ARE CARRYING NO BALLS OF ANY KIND. A wild "
                    f"Pokemon is caught by throwing one; with none in the "
                    f"bag every battle can only end in the thing fainting, "
                    f"so this condition cannot come true however long you "
                    f"stay here. You have {(obs or {}).get('money')} money. "
                    f"Where balls come from, and whether something has to "
                    f"happen first, is yours to work out.")
        else:
            lines = [f"\nTHIS IS NOT SOMEWHERE TO GO — IT IS SOMETHING TO "
                     f"BECOME. The condition is {kind} {dw_val}, and no "
                     f"door satisfies it. Walking somewhere new is not "
                     f"progress here; fighting is."]
        if party:
            lines.append("YOUR PARTY RIGHT NOW: " + "; ".join(
                f"{i}. {m.get('species')} L{m.get('level')} "
                f"{m.get('hp')}/{m.get('max_hp')}hp"
                + (f" [{m.get('status')}]" if m.get("status") else "")
                for i, m in enumerate(party, 1)))
            # WHAT THE CONDITION COUNTS, AND HOW FAR OFF THE WORST IS. The
            # predicate is the harness's own, so saying what it measures is
            # not game knowledge: "every party member" counts the SIX in
            # the party, and a Pokemon in the PC is not in the party. Two
            # L22 Safari catches turned an upkeep leg into eighteen levels
            # of grinding, and nothing said which mon the condition was
            # actually waiting on.
            _kind = str(kind or "")
            if _kind in ("party_min_level", "lead_level", "slot_level"):
                try:
                    _need = int(dw_val if not isinstance(dw_val, dict)
                                else dw_val.get("min") or 0)
                except (TypeError, ValueError):
                    _need = 0
                _short = sorted(
                    ((int(m.get("level") or 0), m.get("species"), i)
                     for i, m in enumerate(party, 1)
                     if int(m.get("level") or 0) < _need))
                if _kind == "party_min_level" and _short:
                    lines.append(
                        "WHAT THIS CONDITION COUNTS: every Pokemon IN YOUR "
                        f"PARTY ({len(party)} of them). Still short of "
                        f"L{_need}: "
                        + ", ".join(f"slot {i} {sp} L{lv} (+{_need - lv})"
                                    for lv, sp, i in _short)
                        + ". A Pokemon in the PC is not in the party, and "
                          "one in the party is counted however it got there.")
        else:
            lines.append("YOUR PARTY IS EMPTY.")
        # ...AND THE WAYS OUT, WHICH THIS PROMPT USED TO HIDE. A training
        # goal still has to WALK: the grass may be past a gate, and while
        # grinding the model was shown no doors at all — it sat in Route
        # 15's west pocket, whose only way east is the gate's far doors,
        # with a prompt that said "walking somewhere new is not progress".
        # Progress toward a LEVEL is fighting; getting to ground that
        # offers fights is still walking, and the ledger is how that is
        # seen. Same block the exploration prompt uses, under its own head.
        try:
            _cands = ledger.build(self, obs, target,
                                  outcomes=self._outcomes_here(obs))
            _blk = ledger.render(_cands, self, obs, target)
            if _blk:
                lines.append(
                    "WAYS OUT OF HERE — if this ground offers no fights, "
                    "the ground that does is through one of these:\n"
                    + _blk + (getattr(ledger, "LAST_PASS_NOTE", "") or ""))
        except Exception as _e:          # a prompt must never die of this
            self.log("training_ledger_error", err=str(_e)[:120])
        # WHAT SOMEBODY TOLD YOU SOMEWHERE ELSE. exploration_text returns
        # this function EARLY for a party goal, which drops the whole
        # exploration context — including the remote-hints block built this
        # afternoon for exactly this failure. So the channel existed and was
        # closed for the one class of goal that most needs it: a catch goal
        # that cannot proceed is nearly always waiting on something a person
        # already said out loud. The clerk's "Say hi to PROF.OAK for me!" is
        # the case in hand.
        # Nothing about maps or exits comes with it — this is people's words.
        _here = self._where(obs)
        _away = []
        for _rg, _ls in (self.hints or {}).items():
            if _rg == _here or not _ls:
                continue
            _p = self._route(_here, _rg)
            if _p is None:
                continue
            _away.append((len(_p), _rg, list(_ls)))
        if _away:
            _away.sort(key=lambda t: (t[0], t[1]))
            _body = []
            for _n, _rg, _ls in _away:
                for _l in _ls:
                    _body.append(f"  ({_rg}, {_n} leg(s) away) {_l}")
                if len(_body) >= 6:
                    break
            lines.append(
                "WHAT YOU WERE TOLD ELSEWHERE — this game explains its own "
                "gates out loud, and a condition that will not come true is "
                "often waiting on something somebody already said:\n"
                + "\n".join(_body[:6]))
        hurt = [m for m in party
                if (m.get("hp") or 0) <= 0.34 * (m.get("max_hp") or 1)]
        if hurt:
            lines.append(
                "SOME OF THEM ARE IN NO STATE TO FIGHT: "
                + ", ".join(f"{m.get('species')} at {m.get('hp')}hp"
                            for m in hurt)
                + ". A Pokemon Center heals the party for nothing; a wipe "
                  "costs the walk back from wherever you last healed.")
        # WHICH INSTRUCTIONS, though. Both kinds are satisfied by walking
        # into grass, and NOTHING ELSE about them is alike — one wants
        # experience and the other wants the creature itself. Handing a
        # catching goal the levelling paragraph ("every wild battle is
        # experience... to level ONE Pokemon, put it in slot 1") told it to
        # grind, and it ground. The catching line that followed was worse
        # than useless: "set battle_policy catch" names a PLAN field, and
        # the escalation writes macros, not plans — advice it had no op to
        # act on.
        # WHETHER THIS IS A HUNT AT ALL is decided ONE place up, at the
        # exploration_text routing (_hunted). Not re-asked here: a second
        # copy of the rule would have to pick a paragraph when it says no,
        # and the only paragraph on offer is the LEVELLING one, which is
        # just as wrong for a shop clerk as the hunting one was.
        if kind in ("party_size", "has_species", "party_type", "dex_owned"):
            lines.append(
                "HOW TO DO IT: {\"op\":\"grind\"} walks onto this floor's "
                "wild ground (tall grass outdoors; in a cave or tower, any "
                "floor tile) and paces until something appears. YOU DO NOT "
                "FIGHT THESE BATTLES — the balls are thrown for you, at "
                "what this subgoal asked for, and anything else is run "
                "from. Your part is being somewhere that offers the right "
                "creature and carrying enough balls to keep trying. Grind "
                "fails plainly where nothing wild lives, and a floor whose "
                "wilds never include one is a floor to leave.")
            # ...AND THE BOX IS PART OF THE BUDGET NOW. Until today a
            # party could only grow by catching, so "go to the grass" was
            # the whole truth. It is not any more: a Pokemon in storage is
            # one op away from the party, and the run had just put two
            # PIDGEYs in a box while carrying a party_size goal it could
            # no longer reach — it made its own subgoal harder with the
            # ops it had been given and nothing said so. This restates
            # obs.pc_mons, which is already in front of it; whether to
            # withdraw or to catch something better stays its call.
            stored = (obs or {}).get("pc_mons") or []
            if stored:
                who = ", ".join(
                    f"{m.get('species')} L{m.get('level')} "
                    f"(box {m.get('box')}, #{m.get('index')})"
                    for m in stored[:6])
                lines.append(
                    "YOU ALREADY HAVE POKEMON IN STORAGE, and a boxed one "
                    "does NOT count toward this condition: " + who
                    + ". {\"op\":\"pc_withdraw\",\"index\":N,\"box\":B} "
                    "at any Pokemon Center puts one back in the party, "
                    "which is faster than catching if one of them already "
                    "suits.")
            lines.append(
                "BALLS ARE THE BUDGET: every throw spends one and a failed "
                "throw spends it too. A mart counter sells more "
                "({\"op\":\"buy\"}), and running out mid-hunt means walking "
                "back for them.")
            # THE COUNT, WHEN IT IS ZERO. Four balls thrown at a Paras and
            # lost, and the next round said "continue using grind" with a
            # bag that held none: the policy then flees everything and the
            # grind cannot end. A fact, beside the budget line.
            _bag = (obs or {}).get("bag") or {}
            _balls = sum(int(v or 0) for k, v in _bag.items()
                         if str(k).endswith("BALL"))
            if _balls == 0:
                lines.append(
                    "BALLS: NONE in the bag. Nothing can be caught without "
                    "one — every wild battle here will end in a flee until "
                    "you carry some.")
            # WHAT THE GRASS HERE HAS OFFERED, counted from the battles you
            # have had on this map. Evidence about the ground; whether the
            # thing you want is in it is yours to read.
            _mid = ((obs or {}).get("map") or {}).get("id")
            _off = (getattr(self, "_offered", {}) or {}).get(_mid) or {}
            if _off:
                _tot = sum(_off.values())
                _top = sorted(_off.items(), key=lambda kv: -kv[1])[:10]
                lines.append(
                    f"WHAT THE WILD GROUND HERE HAS OFFERED, in {_tot} wild "
                    f"encounter(s) on {_mid}: "
                    + ", ".join(f"{sp} x{n}" for sp, n in _top)
                    + ". A floor whose wilds never include the thing you "
                      "want is a floor to leave, or ground of a different "
                      "kind — water, for one — to reach.")
        else:
            lines.append(
                "HOW TO DO IT: {\"op\":\"grind\"} walks onto this floor's "
                "wild ground (tall grass outdoors; in a cave or tower, any "
                "floor tile) and paces until something appears, and every "
                "wild battle is experience for whoever you send out. It "
                "fails plainly if nothing wild lives on this floor, and then "
                "somewhere wild is where to go. To level ONE Pokemon, "
                "put it in slot 1 first ({\"op\":\"party_swap\"}) — the lead "
                "is who gets sent out, and only what fights, earns.")
        # the ONE navigational fact that still matters: a run with no
        # healing behind it is one wipe from losing the walk as well
        rs = (obs or {}).get("respawn") or {}
        if rs.get("map"):
            lines.append(self._respawn_line(obs))
        return "\n".join(lines)

    BAG_SLOTS = 20          # gen 1's bag is twenty distinct items

    def _bag_line(self, obs, sg) -> str:
        """A FULL BAG REFUSES A GIFT, and only an op failing ever said so.
        20/20 has blocked three legs this run (the Lift Key, the Silph
        Scope, HM02) and each time the run learned by being refused. When
        this step is FOR an item, say the count before it costs a round —
        and name what can go, which is the game's own rule (key items
        cannot be tossed), never which one to pick."""
        bag = (obs or {}).get("bag") or {}
        n = len(bag)
        if n < self.BAG_SLOTS - 1:
            return ""
        wants_item = "has_item" in pred_keys(sg.get("done_when") or {})
        if not wants_item:
            _subs = ((self.plan or {}).get("subgoals") or [])
            wants_item = any("has_item" in pred_keys(s2.get("done_when") or {})
                             for s2 in _subs if isinstance(s2, dict))
        if not wants_item:
            return ""
        keys = set((obs or {}).get("key_items") or [])
        spare = sorted(k for k in bag if k not in keys)
        return ("\nYOUR BAG HOLDS " + f"{n}/{self.BAG_SLOTS}"
                + " KINDS OF THING"
                + (" — IT IS FULL" if n >= self.BAG_SLOTS else "")
                + ". A gift or a pickup is REFUSED when it is full, and this "
                  "step is for an item. What you can get rid of ({\"op\":"
                  "\"toss\",\"item\":X} throws it away, {\"op\":\"sell\"} "
                  "at a shop counter turns it into money; key items can be "
                  "neither): "
                + (", ".join(spare[:10]) if spare else "nothing — every "
                   "single thing you carry is a key item")
                + ".")

    def _respawn_line(self, obs) -> str:
        """WHERE you wake, and the RULE that moves it. The place was stated
        (training text, the author's start line) and the rule never was —
        so the run walked from Cerulean to Route 24 with Viridian still its
        respawn, wiped, and woke a whole map away. Manual tier: a blackout
        returns you to the last Pokemon Center you healed at.

        ...AND WHERE THE NEAR ONES ARE. "The last Center you healed at" was
        read as "the Center you must heal at": standing on Route 8, a leg
        from Lavender, the run marched back across Kanto to Vermilion 'to
        heal'. The Centers this run has walked into are its own history;
        name them, nearest first by walked legs."""
        rs = (obs or {}).get("respawn") or {}
        if not rs.get("map"):
            return ""
        here = self._where(obs)
        cents = []
        for r in set(self.visits or {}) | set(self.explored or {}):
            m = r.split("|")[0]
            if not m.endswith("POKECENTER"):
                continue
            p2 = self._route(here, r)
            if p2 is not None:
                cents.append((len(p2), m))
        near = ""
        if cents:
            cents.sort()
            seen, rows = set(), []
            for n, m in cents:
                if m in seen:
                    continue
                seen.add(m)
                rows.append(f"{m} ({n} leg(s))" if n else f"{m} (here)")
            near = (" ANY Center heals; the ones you have walked into, "
                    "nearest first over walked ground: "
                    + ", ".join(rows[:3]) + ".")
        return (f"IF THE PARTY FAINTS you wake at {rs['map']} — the last "
                f"Pokemon Center you HEALED at, which is only where you "
                f"WAKE, not where you must go to heal.{near} Healing at any "
                f"Center ({{\"op\":\"heal\"}}) makes THAT Center the "
                f"place you wake, so a heal before a hard stretch is also "
                f"a shorter walk back.")

    def _hunted(self) -> bool:
        """Is the creature this subgoal wants to be CAUGHT, or handed over?

        THE SAME DISCRIMINATOR AS choose_battle_policy, and it was missed
        here, which is the half that actually talks to the model. A
        party_size subgoal was answered with the hunting paragraph on the
        strength of its predicate alone, so run 8 stood at the Viridian
        counter holding 15 balls and read this, under a subgoal whose
        goal_text was "Talk to the clerk in the Viridian Mart to retrieve
        the Pokemon":

            THIS IS NOT SOMEWHERE TO GO — IT IS SOMETHING TO BECOME. The
            condition is party_size 2, and no door satisfies it. ... the
            grass on this floor holds what it holds ...
            BALLS ARE THE BUDGET ... A mart counter sells more.

        The word "clerk" was not in that prompt. Neither were the exits,
        nor the clerk object, nor anything else about the room it was
        standing in. Buying pokeballs at a mart is not a confused
        inference from that text. It is the instruction, followed.

        Defaults to True, so a subgoal that says nothing either way keeps
        today's behaviour exactly and real catch goals are untouched. Only
        words that name somebody to get it FROM turn the hunt off.
        """
        words = _subgoal_words(getattr(self, "_cur_sg", None) or {})
        if words & set(_CATCH_WORDS):
            return True
        return not (words & set(_GIVEN_WORDS))

    def exploration_text(self, obs, target: str = "", sg: dict | None = None) -> str:
        """Untried vs already-taken exits from where we stand."""
        # A LEVEL IS NOT A PLACE. Everything below answers "where do I go
        # next", which is the wrong question for a subgoal satisfied by
        # battling — and answered loudly enough that a training leg walked
        # out of the grass to open doors at a museum.
        # ...UNLESS THE POKEMON IS BEING HANDED OVER, in which case where
        # you stand is the whole question and the exits are the answer.
        sg_for_bag = sg or {"done_when": {}}
        if self._is_party_goal(target) and self._hunted():
            return self.training_text(obs, target)
        here = self._where(obs)
        move_head = ""
        if str(target or "").startswith("knows_move:"):
            _mv = str(target).split(":", 1)[1]
            _party = ", ".join(
                f"{m.get('species')} L{m.get('level')} knows "
                + "/".join(str(mv.get('id') if isinstance(mv, dict) else mv)
                           for mv in (m.get('moves') or []))
                for m in (obs.get("party") or []))
            move_head = (
                f"THE CONDITION IS A MOVE KNOWN ({_mv}). A Pokemon comes to "
                f"know a move three ways, and each is a different kind of "
                f"step: (1) a MACHINE — one op, {{\"op\":\"use_item\","
                f"\"item\":\"HM_...\",\"slot\":N}} (forget=MOVE if it "
                f"knows four); the game says on screen, the moment you try, "
                f"whether that species can take it, and a refusal is final "
                f"for that species; (2) a LEVEL, by fighting "
                f"({{\"op\":\"grind\",\"intent\":\"train\"}}); (3) a "
                f"DIFFERENT POKEMON that can — caught ({{\"op\":\"grind\","
                f"\"intent\":\"catch\",\"want\":...}}), traded, or given, "
                f"which is a place to go, and the ledger below is for that. "
                f"Which way is yours to judge; the party now: {_party}.\n")
        # THE LEDGER (EXPLORE_DESIGN §3): one ranked block for everything
        # LOCAL — exits, things, people, each with its status and what
        # happened last time this subgoal did it. It replaces the exits
        # block, the shut-doors line, the untouched / pressed / worth-a-
        # word / never-spoken lines and the edge line below; the REMOTE
        # and target-level sections (unfinished floors, the known way,
        # what was said elsewhere, rooms elsewhere with things left,
        # places with ways never taken) stay, after it.
        ledger_block = ""
        if USE_LEDGER:
            _cands = ledger.build(self, obs, target,
                                  outcomes=self._outcomes_here(obs))
            ledger_block = ledger.render(_cands, self, obs, target)
            # the room's own geometry (doors on both sides = a corridor),
            # set by the build above
            ledger_block += getattr(ledger, "LAST_PASS_NOTE", "") or ""
        taken = self._taken_here(here)
        m = (obs or {}).get("map") or {}
        # candidates are DOORS *and* MAP EDGES. Listing only warps meant a
        # town's road out never appeared as untried, so the run kept
        # re-entering the same building instead of walking north (pure4).
        warps = [{"key": f"{w.get('x')},{w.get('y')}", "dest": w.get("dest"),
                  "reachable": w.get("reachable")}
                 for w in (m.get("warps") or [])]
        # dest resolved from what has been WALKED, never from the table
        warps += [{"key": d, "dest": self._walked_dest(m.get("id"), d),
                   "reachable": True}
                  for d in (m.get("connections") or {})]
        # A FLOOR YOU CANNOT WALK ACROSS IS NOT A FLOOR YOU HAVE FINISHED.
        # The frontier is built from warps in regions the run has STOOD in,
        # so a part of a map it has never entered contributes nothing and
        # every known region reports "nothing untried" — which reads as a
        # finished dungeon. Mt Moon B1F has eight doorways; the run used
        # six, and the two it never saw were the way out east, sitting in a
        # fourth pocket of the same floor. This is arithmetic on the
        # doorway list the observation already carries, plus which ones
        # this run has walked: it says a part exists, never where it is or
        # how to get in.
        mid = m.get("id")
        here_keys = {w["key"] for w in warps if w.get("reachable")}
        # UNFILTERED ON PURPOSE, and it looks like a bug. The three other
        # places that walk `explored` this way subtract shut edges, because
        # they are asking "is this doorway still UNOPENED" and a door that
        # turned you back is not opened. THIS one asks a different question:
        # "is that part of the floor somewhere I have never STOOD" — and
        # walking into a door that refused you means you stood at it. A key
        # is only ever recorded here for a door the party actually reached
        # (note_transition refuses to file one otherwise), so filtering shut
        # edges out would have the note claim the run has never been to a
        # spot it has demonstrably been to. Same arithmetic, different
        # question; leave it alone.
        ever = set()
        for reg, ex in (self.explored or {}).items():
            if reg.split("|")[0] == mid:
                ever |= set(ex.keys())
        allw = {f"{w.get('x')},{w.get('y')}" for w in (m.get("warps") or [])}
        # DOORS YOU HAVE STOOD BESIDE BUT NEVER OPENED ARE NOT "PARTS YOU
        # HAVE NEVER STOOD ON". A region's frontier holds the doors seen
        # from ground actually walked, so the Route 16 gate's upper
        # corridor — walked once, its two west doors never taken, the only
        # way to the Fly house — was reported as unreachable ground whose
        # "way there is not known" while it was a room the run had been in.
        _stood_keys = set()
        for reg2, fr2 in (self.frontier or {}).items():
            if reg2.split("|")[0] == mid and reg2 in (self.visits or {}):
                _stood_keys |= {k for k in fr2 if "," in str(k)}
        open_here = (allw & _stood_keys) - here_keys - ever
        unseen = allw - here_keys - ever - _stood_keys
        floor_note = ""
        if open_here:
            floor_note += (
                f"\nDOORS ON THIS FLOOR YOU HAVE STOOD BESIDE AND NEVER "
                f"OPENED: {', '.join(sorted(open_here))} — in a part of "
                f"{mid} you have already walked, just not reachable from "
                f"the spot you are on now. Going back to that part and "
                f"taking one is walking, not searching.")
        if unseen:
            floor_note += (
                f"\nTHIS FLOOR IS NOT FINISHED. {mid} has {len(allw)} "
                f"doorway(s) in total and {len(unseen)} of them "
                f"({', '.join(sorted(unseen))}) are on part of it you have "
                f"never stood on — not reachable on foot from any spot "
                f"you have stood in SO FAR. How to get there is not known: "
                f"it may be further walking on this floor from a corner you "
                f"have not tried, or another doorway from somewhere else. "
                f"What is certain is that this floor has more to it than "
                f"you have seen, so every region you know here can report "
                f"nothing left to try and this still be true.")
        # ...AND THE FLOOR BELOW YOU. The note above describes only the map
        # under your feet, so standing on MT_MOON_1F — whose five doorways
        # are all walked — it says nothing, while MT_MOON_B1F one ladder
        # down has EIGHT and the run has stood at four. The four it has not
        # include 27,3, the way out east to Route 4 and Cerulean. Every
        # region of B1F reports "nothing untried" because a region only
        # knows its own pocket, so the frontier is empty, the escort has
        # nowhere to send anyone, and the only ways-never-taken the model is
        # shown are back in Pewter. It leaves the mountain.
        # Same arithmetic as the local note, asked of maps already walked:
        # doorways seen on that map, minus the ones stood at. It says a part
        # exists and how many, never where it is or how to get in.
        floor_away = ""
        _rows = []
        for _mid, _doors in (self.map_doors or {}).items():
            if _mid == mid or not _doors:
                continue
            _stood = set()
            for _r2, _e2 in (self.explored or {}).items():
                if _r2.split("|")[0] == _mid:
                    _stood |= set(_e2.keys())
            _left = set(_doors) - _stood
            if not _left:
                continue
            _p = None
            for _r2 in (self.explored or {}):
                if _r2.split("|")[0] != _mid:
                    continue
                _c = self._route(here, _r2)
                if _c is not None and (_p is None or len(_c) < len(_p)):
                    _p = _c
            if _p is None:
                continue
            # NEVER TAKEN IS NOT NEVER STOOD BESIDE. This line called every
            # untaken door "on parts you have never stood on … how to reach
            # the rest is not known" — including Route 5's underground-path
            # door, which sat on the frontier of the very region the run had
            # stood in four times. Split them: doors on the frontier of a
            # walked part are plain untried doors to go back for; only the
            # rest are on ground never reached.
            _fr = set()
            _open_dist = None
            for _r2, _keys in (self.frontier or {}).items():
                if _r2.split("|")[0] != _mid or _r2 not in (self.visits or {}):
                    continue
                _mine = {k for k in _keys if "," in str(k)} - _stood
                if not _mine:
                    continue
                _fr |= _mine
                # DISTANCE TO THE ROOM THAT HOLDS THE DOOR, not to the
                # nearest room of that floor. The Route 16 gate's upper
                # corridor was "1 leg away" while reaching it means going
                # out to Route 16 and back in — two legs — because the
                # gate's OTHER corridor was the nearest region of the map.
                _pr = self._route(here, _r2)
                if _pr is not None and (_open_dist is None
                                        or len(_pr) < _open_dist):
                    _open_dist = len(_pr)
            _open = sorted(_left & _fr)
            _far = sorted(_left - _fr)
            _rows.append((_open_dist if (_open and _open_dist is not None)
                          else len(_p), _mid, len(_doors), _open, _far))
        if _rows:
            # A FLOOR WITH A DOOR YOU CAN GO BACK AND OPEN OUTRANKS ONE
            # WHOSE UNFINISHED PART IS UNREACHABLE. Sorted by distance
            # alone and cut at three, ROUTE_16_GATE_1F — two never-taken
            # doors on ground already stood in, the only way to the Fly
            # house — was crowded out by floors whose only "unfinished"
            # part cannot be walked to at all, for four attempts.
            _rows.sort(key=lambda r: (0 if r[3] else 1, r[0], r[1]))
            def _floor_row(_n, _m, _t, _open, _far):
                parts = []
                if _open:
                    parts.append(f"{len(_open)} never taken and on ground you "
                                 f"have stood on ({', '.join(_open[:4])}) — "
                                 f"plain untried doors, {_n} leg(s) away")
                if _far:
                    parts.append(f"{len(_far)} on parts you have never stood "
                                 f"on ({', '.join(_far[:4])})")
                return f"{_m} has {_t} doorway(s): " + "; ".join(parts)
            floor_away = ("\nFLOORS YOU HAVE WALKED THAT ARE NOT FINISHED: "
                          + "; ".join(_floor_row(*r) for r in _rows[:3])
                          + ". A door never taken on ground you have stood "
                            "on is reached by going back there; how to reach "
                            "a part never stood on is not known.")
        # A seam PROVEN uncrossable from this region is not an exit. A map
        # connection belongs to the whole map, so the stub side of a split
        # route still lists the far side's edge — and advertising it as
        # preferred-untried held the run on the Route 4 stub for twenty
        # rounds while the real door was named two lines below.
        blocked = self._sealed(here)
        # Doors reached for and never got through: they belong with the
        # TRIED, said plainly, not in a list headed "prefer these, they are
        # the only way to find anything new".
        spent = self._spent_exits(here)
        untried, tried = [], []
        for w in warps:
            if not w.get("reachable") or w["key"] in blocked:
                continue
            k = w["key"]
            if k not in taken and k in spent:
                tried.append(
                    f"({k}) you have reached for this {spent[k]}x and never "
                    f"once got through — something stops you before the "
                    f"doorway, and nothing about where it leads is known. "
                    f"If that changes, it is worth another go")
                continue
            if k in taken:
                dest = taken[k]["to"]
                bad = self.dead_for(target, dest)
                # A door you have used before is still the way ON if what
                # lies beyond it has unopened exits. Route 2 is split: its
                # north half is only reachable THROUGH the forest, so the
                # forest door (taken 6x) was the correct move while the text
                # told the model retaking it showed nothing new.
                beyond = ""
                if not bad:
                    # NEVER ATTEMPTED IS NOT THE SAME AS ATTEMPTED AND
                    # FAILED. The frontier deliberately keeps a printed road
                    # even after a seam proof, so the map cannot be eroded
                    # by one bad crossing — but counting those proofs as
                    # "exits never taken" advertises a wall as unopened
                    # ground. Route 10's only such exit is its SOUTH seam,
                    # which is past Rock Tunnel and proven uncrossable from
                    # the northern half, so the run was told over and over
                    # that Route 10 had somewhere new to go, and the door
                    # that actually leads there read as already used.
                    left = self._frontier_left(dest)
                    if left:
                        beyond = (f"; BUT {dest} still has {len(left)} exit(s) "
                                  f"never taken, so going back through here "
                                  f"is how you reach them")
                # SHUT is not the same as SEEN. A door that turned you back
                # says nothing about what is behind it, so it stays worth
                # returning to when the thing that shut it might have
                # changed — which a door you have simply walked through
                # does not. Both used to read "taken Nx".
                if taken[k].get("shut"):
                    tried.append(
                        f"({k}) SHUT — walked into {taken[k]['n']}x and "
                        f"turned back every time; nothing is known about "
                        f"what is beyond it, and it may open when whatever "
                        f"holds it changes")
                else:
                    tried.append(
                        f"({k}) -> {dest} ["
                        + (f"taken {taken[k]['n']}x"
                           if (taken[k].get('n') or 0) > 0 else
                           # the honest description of a door you have only
                           # ever come IN through
                           "you arrived through it; never taken from this "
                           "side")
                        + (f"; that area is a KNOWN DEAD END for this goal, "
                           f"failed there {bad}x — do NOT go back"
                           if bad else beyond)
                        + "]")
            else:
                # A MAP EDGE keeps its destination: which roads touch is
                # drawn on the Town Map. A DOOR does not: until this run has
                # walked through it, nobody has seen the far side.
                if not k[0].isdigit():
                    _wd = w.get("dest")
                    untried.append(
                        (bool(_wd) and _wd.split("|")[0] in {
                            a.split("|")[0] for a in self.visits},
                         f"walk {k} out of here -> {_wd or 'UNKNOWN'}"))
                else:
                    _d = self._walked_dest(m.get("id"), k)
                    _face = None if _d else self._frontage(w.get("dest"))
                    untried.append(
                        (bool(_d) and _d.split("|")[0] in {
                            a.split("|")[0] for a in self.visits},
                         f"({k})->{_d or _face or 'UNKNOWN'}"))
        # FRONTIER FIRST here too. _untried_exits (used by the refusal text)
        # was ordered but THIS list is the one the model reads every round,
        # and it was emitting doors in map order — which is how Pallet's
        # houses kept out-ranking the road north for ~20 escalations.
        seen_maps = {a.split("|")[0] for a in self.visits}
        untried.sort(key=lambda p: p[0])
        untried = [t for _, t in untried]
        # THE KNOWN WAY THERE. Frontier-first is right when nothing is known,
        # but on ROUTE_2 the only untried exit ran SOUTH to Viridian while
        # the way to Mt Moon lay north through Pewter — a door already taken
        # 44 times. The graph can answer "which exit starts the journey", so
        # say it rather than leaving the model to infer it from visit counts.
        route_line = ""
        want_area = target.split(":", 1)[1] if target.startswith("area:") else ""
        want_map = target.split(":", 1)[1] if target.startswith("map:") else ""
        if want_area and want_area != here:
            path = self._route(here, want_area)
            if path:
                first_key, first_dest = path[0]
                step = (f"walk {first_key}" if not first_key[0].isdigit()
                        else f"the door at ({first_key})")
                route_line = (
                    f"\nTHE KNOWN WAY TO {want_area} FROM HERE: take {step} "
                    f"to {first_dest} — {len(path)} leg(s) over ground you "
                    f"have already walked ({{\"op\":\"go\",\"to\":"
                    f"\"{want_area}\"}} walks all of them in one op). Take "
                    f"it even if you have used it "
                    f"before; an untried exit that leads somewhere else is "
                    f"not progress toward this goal. That area is a SPECIFIC "
                    f"ROOM, not the whole floor; arriving elsewhere on the "
                    f"same floor is not arriving.")
        elif want_map and want_map != (m.get("id") or ""):
            best = None
            for region in set(list(self.explored) + list(self.visits)):
                if region.split("|")[0] != want_map:
                    continue
                path = self._route(here, region)
                if path and (best is None or len(path) < len(best)):
                    best = path
            if best:
                first_key, first_dest = best[0]
                step = (f"walk {first_key}" if not first_key[0].isdigit()
                        else f"the door at ({first_key})")
                route_line = (
                    f"\nTHE KNOWN WAY TO {want_map} FROM HERE: take {step} "
                    f"to {first_dest} — that is the first leg of a route you "
                    f"have already walked ({len(best)} legs total), and "
                    f"{{\"op\":\"go\",\"to\":\"{want_map}\"}} walks the "
                    f"whole of it for you in one op. Take it even if you have "
                    f"used it before; an untried exit that leads somewhere "
                    f"else is not progress toward this goal.")
            else:
                # NOTHING WALKED IS ON THAT MAP — which is not the same as
                # "no door you have ever taken leads there", the sentence
                # this used to fall through to. Aimed at Vermilion from
                # Cerulean the run HAD walked ROUTE_5 and stepped into the
                # underground path one door south of it; what it had never
                # done was come out the far end. The old wording sent it
                # door-hunting in the city it was standing in, for hours.
                #
                # The truest thing available is the EDGE OF WHAT IT KNOWS in
                # that direction: of the ground already walked, which does
                # the printed map put nearest? Both halves are already
                # permitted — the walked ledger is its own, the distance is
                # the Town Map's — and it names no door beyond ground the
                # run has covered. Getting past the edge is still its
                # problem.
                _links = self._walked_map_links()
                _goal = _doorstep(want_map)
                _pick = None
                for region in set(list(self.explored) + list(self.visits)):
                    _d = static_cost(_doorstep(region.split("|")[0]),
                                     _goal, {}, _links)
                    if _d is None:
                        continue
                    _p = [] if region == here else self._route(here, region)
                    if _p is None:
                        continue
                    _r = (_d, len(_p), region)
                    if _pick is None or _r < _pick[0]:
                        _pick = (_r, region, _p, _d)
                if _pick and not _pick[2]:
                    route_line = (
                        f"\nYou are STANDING on the closest ground you have "
                        f"walked to {want_map} — the printed map puts it "
                        f"{_pick[3]} leg(s) from here, and nothing else you "
                        f"have covered gets nearer. The way on is not on "
                        f"walked ground: it is through something here you "
                        f"have not been through yet.")
                elif _pick:
                    _fk, _fd = _pick[2][0]
                    _st = (f"walk {_fk}" if not _fk[0].isdigit()
                           else f"the door at ({_fk})")
                    route_line = (
                        f"\nNothing you have walked is ON {want_map}. The "
                        f"closest ground you HAVE walked to it is "
                        f"{_pick[1]}, which the printed map puts {_pick[3]} "
                        f"leg(s) from {want_map}; the way there from here is "
                        f"{_st} to {_pick[2][0][1]}, {len(_pick[2])} leg(s) "
                        f"over ground you have already covered. What lies "
                        f"beyond that edge you have not seen.")
        # Rooms already fully worked: nothing left to find in them, but you
        # may still walk through — that distinction is why they are not
        # dead ends. Read the ROOM-level ledger, not the per-target one:
        # travel goals never earn per-target entries, so keying the advice
        # by target meant the model was never told a room was finished
        # during exactly the legs where it cycled through worked rooms.
        # FULLY WORKED IS A CLAIM WITH A DATE ON IT. note_searched means
        # "every exit taken, everything touched" AS OF WHEN IT WAS CHECKED,
        # and the whole point of the re-offer ledger is that a room stops
        # being finished when the world moves — a person with nothing to say
        # in the morning hands you the TOWN MAP in the afternoon. Saying
        # both in one prompt ("nothing is left to find here" beside "worth
        # another word") is the harness contradicting itself, and the model
        # has to pick one. So the worked claim yields: where there is
        # something worth another word, it is not made.
        # The searched LEDGER is untouched — dead ends, the revisit refusal
        # and the escort all still read it, and it stays monotone.
        again = self._worth_another_word(here, obs)
        worked = self._worked_for(target)
        done_rooms = [r for r in worked if r != here
                      and not self._worth_another_word(r, obs, backfill=False)]
        searched_line = ""
        if worked.get(here) and not again:
            searched_line = ("\nYou have ALREADY fully worked this exact "
                             "area — every exit taken, everything touched. "
                             "Do not search it again; pass through or go "
                             "somewhere new.")
        elif worked.get(here):
            searched_line = ("\nYou had fully worked this exact area — every "
                             "exit taken, everything touched — but that was "
                             "before what has happened since; see below.")
        elif done_rooms:
            searched_line = ("\nAlready fully worked (walk through if you "
                             "must, but nothing is left to find in them): "
                             + ", ".join(sorted(done_rooms)[:5]) + ".")
        # DOORS YOU HAVE NEVER OPENED AND CANNOT REACH RIGHT NOW. The exits
        # list above only offers warps you can currently walk to, so a door
        # with someone standing on its approach silently vanishes from the
        # model's options — and the one place it needed to go stopped being
        # mentioned at all. Say it, and say why it might be shut.
        shut = self._unopened_doors(obs)
        shut_line = ""
        if shut:
            shut_line = (
                "\nDOORWAYS ON THIS MAP YOU HAVE NEVER OPENED AND CANNOT "
                "WALK TO FROM HERE: "
                + ", ".join(
                    f"({k})" + (f", nearest person {who}" if who else "")
                    for k, _d, who in shut[:4])
                + ". A doorway does not move, so something between you and "
                "it does not want you through yet — a person to talk to or "
                "fight, a thing to shift, a way round. WHAT is not recorded. "
                "Doing whatever there is to do nearby, and then trying the "
                "doorway again, is how that is found out.")
        # WHAT YOU HAVE BEEN TOLD HERE. Grouped as hints and shown when the
        # room is not yielding — the answer to "why can I not get past" is
        # usually a sentence somebody already said out loud.
        said_here = self.hints.get(here) or []
        hint_line = ""
        if said_here and self.visits.get(here, 0) >= 2:
            hint_line = ("\nWHAT PEOPLE HERE HAVE TOLD YOU (their words, in "
                         "the order you heard them — a gate in this game is "
                         "usually explained out loud by whoever is standing "
                         "at it):\n  "
                         + "\n  ".join(self._dated(here, l, obs)
                                        for l in said_here[-6:]))
        been = self.visits.get(here, 0)
        warned = ""
        # A ROOM YOU KEEP LOSING IN IS THE RIGHT ROOM. Coming back is the
        # only way to win a fight, so the revisit nag is exactly backwards
        # here — and it was the loudest line in the prompt: standing in
        # Misty's gym the model read "you have been in this exact area 19
        # times, take a different exit" with the only untried exits being
        # the doors OUT, while the wipe note below told it to come back
        # stronger. It obeyed the concrete instruction and left, 19 times.
        # The law is already written for the stuck note: a party wipe
        # outranks an exhausted room.
        if been >= 2 and not USE_LEDGER \
                and not self.contested.get(target, {}).get(here):
            # COUNT IT, DO NOT COMMAND. "Take a different exit" is a
            # strategy claim the harness cannot support, and it is loudest
            # in exactly the rooms that matter: it fired ten times over in
            # Mt Moon's fossil room, three tiles from the Super Nerd and
            # both fossils this run needs, telling the party to leave. The
            # battle-region guard was written for this after Misty's gym
            # cost 19 attempts; a room can matter without a fight in it.
            # The count is the evidence — what it means is the model's.
            warned = (f"\nYOU HAVE BEEN IN THIS EXACT AREA {been} TIMES "
                      f"ALREADY ({here}).")
        for tgt, regions in self.dead_ends.items():
            if here in regions:
                warned = (f"\nNOTE: earlier attempts failed to reach "
                          f"'{tgt}' from this exact area "
                          f"({regions[here]}x). Whatever you need is NOT "
                          f"reachable from here — leave first.")
                break
        # Ways never taken ELSEWHERE. exploration_text only ever described
        # the room you stand in, so a run deep in Mt Moon B2F could not know
        # three ladders on 1F had never been opened — pure17 ended with its
        # frontier unexhausted and the super nerd's region never entered.
        elsewhere = []
        near_hint = ""
        # A DOOR SOMEONE IS STANDING ON belongs in this list too. It is
        # built from untried EXITS, and a door nobody can reach is not one —
        # so a city whose only way onward is held shut by a policeman reads
        # as finished from everywhere else, and the run was told the places
        # with ways never taken were Pallet Town and its own bedroom. It
        # believed us and walked there.
        # ONLY DOORS WITH SOMEBODY ON THEM. _unopened_doors reports an
        # unreachable door even when no one is near it — but on a SPLIT map
        # that
        # means every block inherits the whole city's unreachable doors, and
        # this list turns them into "ways you have NEVER taken". Cerulean's
        # badge-house back yard is one door and a patch of grass, and it was
        # advertising eight of main city's doorways; the run visited it 801
        # times. A door with nobody named is not a door held shut HERE, it
        # is a door somewhere else. The model still hears about it in the
        # doorways line, which is where it belongs.
        held = {r: [f"{k}({who})" for k, who in
                    [(x.split(" (")[0],
                      x.split("(")[-1].rstrip(") ").replace(
                          " is standing there", ""))
                     for x in v]
                    if who and who != "None"]
                for r, v in (self.shut_doors or {}).items() if r != here}
        held = {r: v for r, v in held.items() if v}
        for region, exits in list(self.frontier.items()) + \
                [(r, []) for r in held if r not in self.frontier]:
            if region == here:
                continue
            left = self._frontier_left(region)
            left += held.get(region, [])
            if not left:
                continue
            # Naming a destination without its first leg loses to local
            # exits (the ROUTE_2 lesson) — but naming only the NEAREST
            # was goal-blind: it sold a Route 2 gate door while the way
            # to Cerulean waited on B2F. Distance and first leg for EVERY
            # candidate; which door matters is the model's judgment.
            path = self._route(here, region)
            # SORTED BY NAME AND CUT AT SIX. The comment above says every
            # candidate gets its distance and first leg, and then the list
            # was joined with sorted(elsewhere)[:6] — sorted on the rendered
            # STRING, so alphabetically by region id. Standing in Cerulean
            # aimed at Vermilion there were TWELVE candidates and the six
            # that survived were the ones beginning C, M and P: Mt Moon's
            # Pokemon Centre and Viridian's museum, neither of them
            # reachable. UNDERGROUND_PATH_ROUTE_5 — two legs away over
            # walked ground, three exits never taken, and the road to
            # Vermilion — sorted tenth and was cut. The one room that
            # mattered was dropped by its initial letter.
            #
            # Reachable before unreachable, then nearest first, then most
            # left to do. All three are mechanical facts about walked
            # ground; WHICH of them matters is still the model's call, and
            # every candidate that fits the cap is still shown.
            rank = (path is None, len(path or ()), -len(left), region)
            if path:
                fk, fd = path[0]
                leg = (f"walk {fk}" if not fk[0].isdigit()
                       else f"door ({fk})")
                elsewhere.append(
                    (rank,
                     f"{region} ({', '.join(sorted(left))} — {len(path)} "
                     f"leg(s) away, first: {leg} to {fd})"))
            else:
                elsewhere.append(
                    (rank,
                     f"{region} ({', '.join(sorted(left))} — no walked "
                     f"route from here)"))
        # FIELD ITEMS within reach. Computed BEFORE the early return: a
        # dead-end room with no listed exits is exactly where a blocking
        # item sits. pure30 beat the Mt Moon nerd beside two reachable
        # fossils, left without touching either, and the corridor stayed
        # shut. Picking one up costs a turn and can never hurt.
        # ATTACKING PP, stated while it still matters. The party's move PP
        # is in the observation and the journal reports a dry lead after a
        # wipe, but nothing said it during the run that was dying: a lead
        # with no damaging PP left fights everything with 0-power moves
        # until it faints. Only a Pokemon Center restores PP, so this is a
        # fact worth acting on — whether to walk back for it is the
        # model's call.
        # Which moves are attacks is the MODEL's knowledge, not the
        # harness's — so state the PP and let it judge. It is shown only
        # when something is already empty, so it stays quiet until it
        # matters.
        pp_line = ""
        lead = ((obs or {}).get("party") or [None])[0] if obs else None
        moves = (lead or {}).get("moves") or []
        if moves and any((mv.get("pp") or 0) == 0 for mv in moves):
            pp_line = (f"\nPP of your lead ({lead.get('species')}): "
                       + ", ".join(f"{mv.get('id')} {mv.get('pp')}"
                                   for mv in moves)
                       + ". A move at 0 cannot be used; only a Pokemon "
                         "Center restores PP.")
        taken_objs = self._untaken(m, self._tried_objs.get(here, set()))
        # WITH COORDINATES. A player sees where things sit relative to each
        # other; the list said only their names, so anything whose solution
        # is about ARRANGEMENT was unanswerable from what we showed. The
        # Vermilion gym is the pure case: its own text tells you when the
        # first electric lock opens and when a wrong guess resets both, and
        # the second switch is always in a can beside the first — but
        # "beside" cannot be reasoned about from a bare list of fifteen
        # names. Where they are is on screen; the deduction stays the
        # model's.
        def _named(o):
            n, x, y = o.get("name"), o.get("x"), o.get("y")
            return f"{n} ({x},{y})" if x is not None and y is not None else n
        # THE PANEL IS THE WAY OUT OF A LIFT. A car's two warp tiles both
        # lead back to the floor you got on at, because gen1 rewrites them
        # from the floor menu — so the doorway count says a five-floor lift
        # has nothing unopened in it, and the run rode CELADON_MART_ELEVATOR
        # four times and left four times. Once the panel has been pressed
        # the floors are known (obs.map.lift_floors, learned from the menu
        # on screen, never read ahead), and a car that says what it serves
        # is not an empty room.
        lift = (m.get("lift_floors") or [])
        lift_line = ""
        if lift:
            lift_line = ("\nThe panel in this car offers: "
                         + ", ".join(str(f) for f in lift)
                         + ". Riding it is the only way to those floors — "
                           "the doors in here lead back where you got on.")
        loot = [_named(o) for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("name")
                and o.get("name") not in taken_objs]
        reach = [_named(o) for o in (m.get("objects") or [])
                 if o.get("reachable") and o.get("name")]
        loot_line = pp_line + lift_line
        # LOCAL vs REMOTE. Under the ledger the four local lines below
        # (untouched things, everything pressed + what was carried, worth
        # another word, people never spoken to) are entries in the block;
        # they are still composed for the legacy renderer and dropped at
        # assembly. The remote lines (rooms elsewhere with things never
        # touched / people worth another word) stay either way.
        remote_line = ""
        if loot:
            loot_line += (f"\nTHINGS within reach here you have NOT touched "
                         f"yet: {', '.join(loot[:12])}. Press A on them before "
                         f"you leave — it is free, and a thing sitting in a "
                         f"passage can be exactly what is blocking it, so "
                         f"interacting with it may open the way.")
        elif reach:
            # A room where everything has been pressed once used to say only
            # that — a dead end in words. But WHERE the things are is still
            # on screen and still unsaid, and some rooms are puzzles about
            # arrangement rather than about finding one more thing. State
            # the layout and stop; what to make of it is the model's.
            loot_line += (f"\nWHAT IS HERE AND WHERE, all of it pressed at "
                          f"least once: {', '.join(reach[:16])}.")
            # ...BUT PRESSED WHEN? What someone says can depend on what you
            # are carrying, and this ledger is for a lifetime. The BIKE_SHOP
            # clerk was spoken to before the BIKE_VOUCHER existed and has
            # been filtered out of every prompt since, voucher still in the
            # bag. Nothing here is re-opened and nothing is un-said — the
            # room simply states the one fact that makes "pressed once" a
            # weaker claim than it looks, and what to make of that is the
            # model's, exactly as with the layout line above.
            then = self._touch_bag.get(here)
            now = self._key_items()
            fresh = [k for k in now if k not in (then or [])]
            if then is not None and fresh:
                loot_line += (f"\nThat was when you were carrying "
                              f"{len(then)} key item(s); you now carry "
                              f"{len(now)}, having picked up "
                              f"{', '.join(sorted(fresh)[:6])} since.")
        # ...AND NAME THEM. The line above counts KEY ITEMS, which is the
        # narrowest possible reading of "the world changed" — it cannot see
        # a badge, and it cannot see the starter, which is the one thing
        # Daisy's line turns on. Per-object marks can. Same rule as above:
        # nothing is un-said, the touch stands, and which of these is worth
        # a second word is the model's call.
        if again:
            if self._note_reoffer(here, again, obs):
                self._save_memory()
            loot_line += (
                f"\nWORTH ANOTHER WORD: you pressed {', '.join(again[:6])} "
                f"here when you were carrying different things, before "
                f"things had happened that have happened since. People in "
                f"this game say different things once the world moves — the "
                f"same person can have nothing to say one day and hand you "
                f"something the next. You HAVE pressed them; that is not in "
                f"doubt. Whether any of them is worth a second word now is "
                f"yours to judge.")
        # ...AND WHAT YOU WERE TOLD SOMEWHERE ELSE. The hint block above is
        # keyed on the room you are STANDING IN, so an instruction is
        # readable exactly once and then filed where it can never be read
        # again. Watched live: the clean-room run forced its way into the
        # Viridian mart, swept the room, took OAK'S PARCEL, and was told
        # "Okay! Say hi to PROF.OAK for me!" — the whole gate, since the
        # parcel is the only thing that moves the old man off the road
        # north. It walked out, and from that moment the sentence was
        # invisible: it bounced between Route 1 and the city border
        # carrying the answer in its bag.
        # The PLAN AUTHOR has had the remote version of this for weeks
        # ("WHAT PEOPLE HAVE SAID, and where they said it"). The escalation
        # loop, which is the half actually walking around, never did.
        # Nearest first over walked ground, and bounded — this is a prompt
        # that already lives near a truncation cliff.
        said_away = []
        for _rg, _lines in (self.hints or {}).items():
            if _rg == here or not _lines:
                continue
            _p = self._route(here, _rg)
            if _p is None:
                continue
            said_away.append((len(_p), _rg, list(_lines)))
        if said_away:
            # DO NOT PICK WHICH SENTENCE MATTERS. Two goes at ranking got
            # it wrong in opposite directions: last-two-lines-of-three-rooms
            # gave the Pokemon Centre nurse's boilerplate and dropped the
            # mart entirely; one-line-per-room reached the mart and took
            # "No! POTIONs are all sold out" over the clerk's "Say hi to
            # PROF.OAK for me!", because the clerk spoke FIRST. There is no
            # mechanical way to tell which sentence is the gate — that is
            # exactly the judgment this harness is not supposed to make.
            # So rank ROOMS by distance, which is mechanical, and inside a
            # room say everything, bounded by a total line count.
            said_away.sort(key=lambda t: (t[0], t[1]))
            _body = []
            for _n, _rg, _ls in said_away:
                for _l in _ls:
                    _body.append(f"  ({_rg}, {_n} leg(s) away) "
                                 f"{self._dated(_rg, _l, obs)}")
                if len(_body) >= 8:
                    break
            _body = _body[:8]
            hint_line += ("\nWHAT YOU WERE TOLD ELSEWHERE, nearest first. "
                          "People say a thing once and this game explains "
                          "its own gates out loud, so a sentence you heard "
                          "in another room is often the reason this one is "
                          "not working:\n" + "\n".join(_body))
        # ASK SOMEBODY. When a room stops yielding, the cheapest move left is
        # the one a person makes: talk to whoever is standing around. This
        # game states its own rules in dialogue, every line gets kept (see
        # WHAT PEOPLE HERE HAVE TOLD YOU), and the run has walked past the
        # same unspoken-to NPCs for whole attempts while re-taking doors.
        folk = [o.get("name") for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("name")
                and o.get("kind") in ("npc", "trainer")
                and o.get("name") not in taken_objs]
        if folk and self.visits.get(here, 0) >= 2:
            loot_line += (f"\nPEOPLE HERE YOU HAVE NEVER SPOKEN TO: "
                          f"{', '.join(folk[:6])}. You have been in this area "
                          f"before and it has not opened up. Talk to them — "
                          f"in this game a locked way is normally explained "
                          f"out loud by somebody standing near it, and what "
                          f"they say is written down for you.")
        # ...and the same fact about ROOMS YOU ARE NOT IN. When every
        # frontier exit is taken, the only thing that still changes the
        # geometry is an untouched object (the Mt Moon fossils are the door
        # east), and the loot line above only fires when standing beside
        # one. Sightings + the touched ledger earned this across runs.
        # A sighting can go stale once a thing is taken — the obs on
        # arrival is the truth — so this is a pointer, not a promise.
        held = []
        for region, names in self.sightings.items():
            if region == here:
                continue
            got = self._tried_objs.get(region, set())
            left = [n for n in names if n not in got]
            if not left:
                continue
            # nearest first, by the walked graph: a fresh touched ledger
            # lists every room since Pallet, and Mom's house must not
            # out-rank the fossil room when the run is standing at Mt Moon
            path = self._route(here, region)
            if not path:
                continue
            held.append((len(path),
                         f"{region} ({', '.join(sorted(left)[:4])} — "
                         f"{len(path)} leg(s) away)"))
        if held:
            held.sort(key=lambda p: p[0])
            remote_line += ("\nRooms you have SEEN things in that you have "
                          "never touched: "
                          + "; ".join(t for _, t in held[:4])
                          + ". A thing in a passage can BE the blockage — "
                          "going back and pressing A on it can open ground "
                          "no exit reaches.")
        # ...AND ROOMS WHOSE PEOPLE ARE WORTH ANOTHER WORD. The re-offer
        # line only ever fired for the room being stood in, which is the
        # half that cannot reach the case it was built for: Daisy is in
        # PALLET TOWN and the run has no reason to go back there, so the
        # TOWN MAP would have stayed in her house for ever anyway. The
        # untouched-rooms list right above already solves the same problem
        # for things never pressed; this is the same list for things pressed
        # when the world was different.
        # Nothing is un-said and nothing is pointed at: it names rooms, not
        # people, and says only that the world has moved since. Whether any
        # of it is worth the walk is the model's.
        aloud = []
        for region in list(self._touch_mark):
            if region == here:
                continue
            names = self._worth_another_word(region, obs, backfill=False)
            if not names:
                continue
            path = self._route(here, region)
            if not path:
                continue
            aloud.append((len(path),
                          f"{region} ({', '.join(names[:3])} — "
                          f"{len(path)} leg(s) away)"))
        if aloud:
            aloud.sort(key=lambda p: p[0])
            remote_line += ("\nROOMS WHERE SOMEBODY IS WORTH ANOTHER WORD — "
                          "you pressed these when you were carrying "
                          "different things, before things had happened "
                          "that have happened since: "
                          + "; ".join(t for _, t in aloud[:4])
                          + ". People in this game hand over what they would "
                          "not hand over yesterday.")
        # A destination in NO walked region deserves saying so out loud.
        # Silence here left the model hunting Cerulean on the west stub of
        # Route 4 three attempts running: it had visit counts and dead
        # ends, but nothing stating the atlas simply does not contain the
        # place — so walking known ground cannot reach it, and only
        # something never DONE (an untouched thing, a person, an obstacle)
        # can open the way. Paired with the untouched-rooms list this
        # makes the fossil inference one step instead of a leap.
        if (want_map and not route_line
                and not any(r.split("|")[0] == want_map for r in
                            set(list(self.explored) + list(self.visits)))):
            if elsewhere:
                route_line = (
                    f"\n{want_map} is NOWHERE in your atlas: no door you "
                    f"have ever taken leads there. The only doors never "
                    f"opened are listed here — one of them, or something "
                    f"never touched, is how it opens.")
            else:
                route_line = (
                    f"\n{want_map} is NOWHERE in your atlas, and EVERY "
                    f"door of every room you know is mapped to somewhere "
                    f"else. Walking known ground cannot reach it — "
                    f"something you have never DONE must open the way: an "
                    f"untouched thing, a person to talk to, an obstacle "
                    f"to clear. Start with the rooms below still holding "
                    f"things you have never touched.")
        # THE TOWN MAP knows what a place hangs off, and route NUMBERS lie
        # about adjacency: plans wrote route_4 -> route_5 because the
        # numbers are consecutive, but neither touches the other — both
        # attach to Cerulean — and the walker paced the seam for cycles
        # trying to make geography obey numbering. Static map connections
        # are printed on the pamphlet's own map; say them.
        if want_map and want_map in MAP_EDGES:
            att = ", ".join(f"its {d} side touches {m}"
                            for d, m in sorted(MAP_EDGES[want_map].items()))
            # THE SAME ARTIFACT, UNDER ITS OWN NAME. author.py now gates
            # its two printed-map blocks on the TOWN MAP being in the bag;
            # handing the identical adjacency over here, at escalation time,
            # would gate one door and leave the other open.
            if self._holding_town_map(obs):
                # THE WHOLE MAP, NOT THE ONE ENTRY. Printing only the
                # target's neighbours ("LAVENDER attaches to ROUTE_10,
                # ROUTE_12, ROUTE_8") was still hiding the map: standing on
                # Route 11 the run could not see that ROUTE_10 hangs off
                # ROUTE_9 off CERULEAN, and spent a leg on Snorlax and the
                # thirsty guard. The Town Map on screen shows every road and
                # town; say all of it (1.7k chars) — unranked, no route
                # drawn, which is the line the rule draws.
                _all = "; ".join(
                    f"{m}: " + ", ".join(f"{d} {t}" for d, t in sorted(v.items()))
                    for m, v in sorted(MAP_EDGES.items()))
                route_line += (f"\nTHE TOWN MAP (every road and town it shows, "
                               f"and what each touches — caves, tunnels and "
                               f"buildings are doors, not shown here): {_all}.")
            # AND NOTHING FURTHER. There used to be a TOWN-MAP ITINERARY
            # here: a BFS over the printed adjacencies, from where the party
            # stands to the target, printed as "ROUTE_5 -> SAFFRON_CITY ->
            # ROUTE_7 -> CELADON_CITY". That is a solved route handed over
            # whole, which is the one thing the rule forbids — we may stop
            # hiding the map, we may not walk the model's finger along it.
            # A player holding the Town Map sees the same adjacencies and
            # works the journey out; working it out is the game.
            #
            # It was also WRONG as often as it was over the line: the BFS
            # spans outdoor maps only, so any journey through a tunnel, a
            # gate or a building — the Underground Path, Rock Tunnel, Diglett
            # 's Cave — was printed as a road that does not exist.
            #
            # What it carried that was legitimate — that a leg has been
            # leaned on and never opened — is walked evidence, and survives
            # in the ranking (which prices exactly those legs) and in the
            # visit counts the model is already shown. Do not reinstate the
            # path in order to hang that annotation off it.
        if USE_LEDGER:
            # LOCAL FIRST, IN ONE BLOCK; then the target line and the
            # remote lists. searched_line for THIS area is the header's
            # FULLY WORKED verdict now; the "already fully worked
            # elsewhere" variant is remote and stays.
            _remote_worked = searched_line if "Already fully worked" in \
                searched_line else ""
            _elsewhere_str = ""
            if elsewhere:
                _elsewhere_str = (
                    "\nPlaces you have already been that still have ways "
                    "you have NEVER taken: "
                    + "; ".join(t for _r, t in sorted(elsewhere)[:6])
                    + "." + near_hint)
            _rs_line = self._respawn_line(obs)
        # THE SAFARI CLOCK, while it is running: steps left and balls left
        # are both on screen in the game and neither was ever said.
        _sf = (obs or {}).get("safari") or {}
        if _sf.get("steps") is not None:
            _rs_line = (f"THE SAFARI GAME IS RUNNING: {_sf.get('steps')} "
                        f"step(s) left and {_sf.get('balls')} SAFARI BALL(s). "
                        f"When the steps run out you are shown the door, and "
                        f"walking out of the zone ends the game too — what "
                        f"you have caught you keep.\n") + _rs_line
            # (the blockers list rides here too — it had been appended
            # only to the legacy renderer's return, i.e. never shown)
            # DOORS ON THIS MAP NEVER OPENED. The ledger lists them, but a
            # door you cannot walk to from this pocket reads as dead ("you
            # cannot walk to it from where you stand") and the one line
            # that says the map still HAS unopened ways — shut_line — was
            # built and then dropped on this path. Route 16 sat on three
            # never-opened doors for an attempt with nothing saying so.
            return (move_head + warned + "\n" + ledger_block + pp_line
                    + lift_line
                    + ("\n" + _rs_line if _rs_line else "")
                    + floor_note + floor_away + route_line + _remote_worked
                    + shut_line
                    + hint_line + remote_line + _elsewhere_str
                    + self._bag_line(obs, sg_for_bag)
                    + self.blockers_text(obs))
        loot_line += remote_line
        if not (untried or tried):
            if elsewhere:
                return (warned + route_line
                        + "\nNothing here is new, but these places "
                        "you have already been still have ways you have "
                        "NEVER taken: " + "; ".join(t for _r, t in sorted(elsewhere)[:6])
                        + ". Go back to one and take it." + near_hint
                        + loot_line)
            return (warned + route_line + searched_line + shut_line
                    + hint_line + loot_line)
        # WHICH DIRECTIONS THIS MAP EVEN HAS. A seam that does not exist
        # appears in NEITHER list — not untried, not taken — so from the
        # text there is no way to tell "east is already walked" from "this
        # map has no east side". Measured over 1,752 recorded decisions
        # (planner/decisions.py): 128 proposed a compass direction the room
        # does not have, and they are one shape — MT_MOON_1F "east" because
        # the printed map puts Cerulean east, while the exits block offered
        # south. That is the model reasoning correctly from the map and
        # colliding with the room's topology, with nothing reconciling them.
        # The room's own seams are on screen: you can see where a road
        # leaves. Say which sides exist and the collision cannot happen.
        _sides = sorted((m.get("connections") or {}).keys())
        _edge_line = ""
        if _sides:
            _pretty = (_sides[0] if len(_sides) == 1
                       else " and ".join([", ".join(_sides[:-1]),
                                          _sides[-1]]))
            _edge_line = (f"\nTHIS MAP HAS AN EDGE ON ITS {_pretty} "
                          f"side{'' if len(_sides) == 1 else 's'} and "
                          f"nowhere else — crossing any other way is not "
                          f"something this map can do, however the printed "
                          f"map is laid out.")
        else:
            _edge_line = ("\nTHIS MAP HAS NO EDGES AT ALL — it is indoors. "
                          "The only ways out are its doors; there is no "
                          "direction to cross.")
        out = warned + _edge_line + "\nEXITS FROM HERE — "
        out += ("UNTRIED (prefer these, they are the only way to find "
                f"anything new): {', '.join(untried)}. " if untried
                else "none untried. ")
        if tried:
            out += (f"Already taken from here: {'; '.join(tried)} — retaking "
                    "one returns you where it says. That is still the right "
                    "move if the note says there is unopened ground beyond "
                    "it, or if nothing here is untried.")
        # ORDER IS THE BUDGET, NOT LENGTH. Measured over 3,535 decisions
        # where two or more untried exits were offered: the model took the
        # FIRST-listed one 54% of the time against a ~8% chance rate, and
        # the median position of whatever it acted on was 14% of the way
        # through the prompt. (The list is ranked, so some of that 54% is
        # the ranking being right rather than position deciding — but the
        # depth figure does not care.) Whatever else is true, a fact at 60%
        # depth is close to not having been said.
        #
        # So this was backwards. The remote-hints block landed at 51% and
        # the untouched-things list at 68%, while "places you have already
        # been that still have ways you have never taken" — an invitation to
        # LEAVE — sat at 22%. LOCAL BEFORE REMOTE: what is here, and what
        # was said, are things to act on now; the elsewhere lists are
        # suggestions to go away, and they belong after.
        _elsewhere_str = ""
        if elsewhere:
            _elsewhere_str = (
                "\nPlaces you have already been that still have ways "
                "you have NEVER taken: "
                + "; ".join(t for _r, t in sorted(elsewhere)[:6])
                + "." + near_hint)
        out += (floor_note + floor_away + route_line + searched_line + shut_line
                + hint_line + loot_line + _elsewhere_str
                + self._bag_line(obs, sg_for_bag)
                + self.blockers_text(obs))
        return move_head + out

    # Every map the run has ever entered, in one line of the escalation
    # prompt, growing all game — 39 maps was already 910 tokens at leg 8 of
    # 38, and Kanto has some 250. The escalation prompt has no budget of any
    # kind, and ollama drops the FRONT of an oversized one, which is where
    # the op vocabulary lives. Bound it the same way the author's evidence
    # is bounded, and by the same rule: keep what is NEAR, say how much went.
    ATLAS_BUDGET = 4000

    def _dated(self, region: str, line: str, obs) -> str:
        """A hint line with WHEN it was heard, if that is known: how many
        events have fired since. Said before the world moved is a fact the
        reader needs to weigh a sentence; whether it still applies is the
        model's."""
        then = ((getattr(self, "hints_at", {}) or {}).get(region) or {}).get(line)
        if then is None:
            return line
        now = len((obs or {}).get("flags") or [])
        if now > then:
            return (f"{line}  (said before {now - then} event(s) that have "
                    f"fired since)")
        return line

    def _atlas_text(self, here: str | None = None) -> str:
        parts = []
        # seam names come from the printed map: shown only while the run
        # holds it; otherwise a seam is named by where the run came OUT
        _held = self._holding_town_map(self._st.get("obs") or {})
        for mid, e in self.atlas.items():
            bits = []
            if e.get("edges"):
                bits.append(", ".join(
                    f"{d}->{t if _held else (self._walked_dest(mid, d) or 'UNKNOWN')}"
                    for d, t in e["edges"].items()))
            if e.get("warps"):
                dd: dict = {}
                for w in e["warps"]:
                    k = f"{w['x']},{w['y']}"
                    dd.setdefault(self._walked_dest(mid, k) or "UNKNOWN",
                                  []).append(f"({k})")
                bits.append("doors: " + ", ".join(
                    f"{d} at {'/'.join(v[:2])}" for d, v in dd.items()))
            parts.append((mid, f"{mid}: " + "; ".join(bits)))
        if here:
            links = self._walked_map_links()
            start = _doorstep(here)

            def _far(mid):
                if mid == here:
                    return -1
                c = static_cost(start, _doorstep(mid), {}, links)
                return c if c is not None else 999
            parts.sort(key=lambda kv: _far(kv[0]))
        out, used, dropped = [], 0, 0
        for _mid, line in parts:
            if out and used + len(line) + 3 > self.ATLAS_BUDGET:
                dropped += 1
                continue
            out.append(line)
            used += len(line) + 3
        text = " | ".join(out)
        if dropped:
            text += (f" | ...and {dropped} more map(s) further from here, "
                     f"not shown")
        return text

    def status(self, **kw):
        """Keep run/status.txt current: what is it TRYING to do right now.
        Watching the window shows behaviour; this shows intent. Pair them:
          watch -n1 cat ~/Developer/red-recomp/run/status.txt
        """
        self._st.update({k: v for k, v in kw.items() if v is not None})
        st = self._st
        def _wrap_status(txt: str, width: int = 100, indent: str = " " * 9):
            """One long sentence over several lines, indented under its
            label — nothing dropped."""
            words, out, line = str(txt).split(), [], ""
            for w in words:
                if line and len(line) + 1 + len(w) > width:
                    out.append(line)
                    line = w
                else:
                    line = f"{line} {w}".strip()
            if line:
                out.append(line)
            return ("\n" + indent).join(out) if out else ""

        obs = st.get("obs") or {}
        pl = obs.get("player") or {}
        party = ", ".join(
            f"{m.get('species')} L{m.get('level')} {m.get('hp')}/"
            f"{m.get('max_hp')}" for m in (obs.get("party") or []))
        lines = [
            f"PLAN     {st.get('plan','?')}",
            f"SUBGOAL  {st.get('subgoal','?')}  [{st.get('phase','')}]",
            "GOAL     " + _wrap_status(st.get("goal_text") or ""),
            f"DONE_WHEN{json.dumps(st.get('done_when') or {})}",
            # what it is THINKING: its own plan from the last reply (the
            # plan echo), so the status line shows intent in its words.
            # NOT TRUNCATED (user, 2026-08-19): the cut fell mid-sentence
            # exactly where the reasoning turns — "…because the path is
            # blocked by" — and the one line worth reading was the one
            # being thrown away. Wrapped instead, so a long thought stays
            # readable in a terminal.
            "THINKS   " + _wrap_status(
                getattr(self, "_plan_said", "") or ""),
            f"DOING    {st.get('doing','')}",
            # LAST is where the harness's own answer lands — the refusals,
            # the "the game says:" quotes, the ledge/slope explanations —
            # and 150 characters cut every one of them mid-reason.
            "LAST     " + _wrap_status(st.get("last") or ""),
            f"WHERE    {(obs.get('map') or {}).get('id')} "
            f"({pl.get('x')},{pl.get('y')}) mode={obs.get('mode')}",
            f"PARTY    {party}",
            # the slot count beside the bag: 20/20 has blocked three legs
            # this run and the number was only ever visible by counting
            f"MONEY    {obs.get('money')}   "
            f"BAG {len(obs.get('bag') or {})}/{self.BAG_SLOTS} "
            f"{json.dumps(obs.get('bag') or {})}",
            f"t+{round(time.time() - self.t0)}s",
        ]
        try:
            (RUN / "status.txt").write_text("\n".join(lines) + "\n")
        except OSError:
            pass

    def log(self, kind, **kw):
        self.logf.write(json.dumps(
            {"dt": round(time.time() - self.t0, 1), "kind": kind, **kw}) + "\n")
        self.logf.flush()

    def handle_battle(self, subgoal: dict, obs: dict) -> dict:
        # traversal (spec-rule wild fleeing) is the DEFAULT: journey
        # subgoals that fought every Route 1 wild kept wiping and halving
        # the wallet (brock37 died shopping at L8 with 93 money). Trainers
        # are fought under either policy; grind/catch subgoals declare
        # their fight/catch intent explicitly.
        # INFER the intent from what the subgoal is actually for. The catch
        # logic (weaken to the throw threshold, then throw) only runs under
        # intent="catch", and author.py never emits a battle_policy field —
        # so catch_backup ran the TRAVERSAL policy, which fights and flees
        # but never throws a ball. It KO'd every wild it met and the goal
        # could not be satisfied at all.
        # ...AND EVERY CONDITION A BALL CAN SATISFY, THROUGH any_of. This
        # listed party_size alone, so the three predicates added later —
        # party_type, has_species, dex_owned — fell through to the
        # traversal policy and the run KO'd its way across Route 24 with 13
        # balls in the bag and "the party holds a WATER or GRASS type"
        # unsatisfiable by anything it was doing. Worse, the test was `in
        # dw`, which cannot see into an either/or: the live subgoal read
        # {"any_of":[{"party_type":"WATER"},{"party_type":"GRASS"}]} and
        # would have missed party_size there too. pred_keys exists for
        # exactly this and recurses into any_of.
        # ...AND FROM THE SUBGOAL'S OWN SENTENCE, not the predicate alone.
        # See choose_battle_policy: party_size is satisfied by catching one
        # OR by being handed one, and only the words say which.
        name, why = choose_battle_policy(subgoal)
        _oi = getattr(self, "_op_intent", None)
        if _oi and _oi.get("intent"):
            name = {"catch": "catch", "train": "default", "fight": "default",
                    "pass": "traversal", "traversal": "traversal"}[_oi["intent"]]
            why = "the op said so"
        if name not in BATTLE_POLICIES:          # never crash on a bad key
            name = "traversal"
        if why.startswith("the predicate"):
            # SAY IT, do not just do it. The harness has declined the
            # reading the numbers alone would have given, and the subgoal
            # may well fail because of that. A silent policy switch is the
            # kind of thing that gets debugged twice.
            self.log("battle_policy_conflict", subgoal=subgoal["id"],
                     chose=name, why=why)
        # Name the combatants: three Misty wipes reached the re-author as
        # bare FAILED lines, so every rewrite fixed the route and never the
        # matchup — species and levels are on screen the whole fight.
        b0 = (obs or {}).get("battle") or {}
        foe, me = b0.get("foe") or {}, b0.get("me") or {}
        self.log("battle_start", subgoal=subgoal["id"], policy=name,
                 foe=f"{foe.get('species')} L{foe.get('level')}",
                 me=f"{me.get('species')} L{me.get('level')} "
                    f"{me.get('hp')}/{me.get('maxhp')}hp")
        # WHAT THE GRASS OFFERED, COUNTED. A catch goal on Route 24 ground
        # through 87 encounters (Oddish 22, Kakuna 18, Weedle 16, Pidgey
        # 15, Abra 14 ...) hunting a WATER type the grass never holds, and
        # nothing showed it the tally the journal already had. Kept per
        # map, persisted, and said in the training text; what it means
        # (this grass has no Water types; a rod is needed) is the model's.
        if b0.get("kind") == "wild" and foe.get("species"):
            _m = getattr(self, "_last_overworld_map", None) or "?"
            book = self._offered.setdefault(_m, {})
            book[str(foe["species"])] = book.get(str(foe["species"]), 0) + 1
        # THE GHOST CANNOT BE FOUGHT, AND ONLY TRYING SHOWS IT. The policy
        # flees the tower's fixed GHOST without a word, so the model was
        # left planning to "fight the Ghost to completion" — a thing the
        # screen would have refused on the first press of FIGHT ("X is too
        # scared to move!"). Press FIGHT once per run, read what the screen
        # says, write it on the blocker, then flee as before. One turn of
        # exposure, once; the sentence is the game's own.
        if (b0.get("ghost") and b0.get("noCatch")
                and not getattr(self, "_ghost_probed", False)):
            self._ghost_probed = True
            try:
                o2 = self.b.send("battle_move", index=1)
                det = str(((o2 or {}).get("result") or {}).get("detail")
                          or "")
                said = ""
                if "the screen says: " in det:
                    said = det.split("the screen says: ", 1)[1].strip(
                        ' "')
                line = ("you pressed FIGHT: "
                        + (f'"{said[:120]}"' if said else
                           f"no move list opened ({det[:80]})"))
                self.log("ghost_probe", subgoal=subgoal["id"], said=said[:160],
                         detail=det[:120])
                for bk, bl in self.blockers.items():
                    if "GHOST" in (bl.get("what") or "") \
                            and not bl.get("cleared") \
                            and "FIGHT" not in (bl.get("what") or ""):
                        bl["what"] = (bl["what"] + " — " + line)[:220]
                self._save_memory()
                obs = self.settle() if (o2 or {}).get("mode") != "battle" \
                    else o2
            except Exception as e:      # a probe must never cost the fight
                self.log("ghost_probe_error", err=str(e)[:120])
        # LEAD WITH THE POKEMON THE PLAN IS TRAINING. A slot_level goal is
        # unsatisfiable otherwise: only the mon that FIGHTS earns, battles
        # always opened with slot 1, and nothing outside a faint prompt can
        # reorder the party — so train_backup_rattata sent a L32 Charmeleon
        # to every battle and the L11 Rattata it was written for gained two
        # levels in an hour, most of them from being thrown in after a
        # faint. Switching the trainee in executes the plan's stated intent;
        # whether it survives where the model chose to train is the model's
        # problem, and the journal will say.
        dw0 = subgoal.get("done_when") or {}
        want_slot = (dw0.get("slot_level") or {}).get("slot")
        # WILD BATTLES ONLY. Training is something you do to weak wild
        # Pokemon; a trainer fight is not an opportunity you control, and
        # you cannot flee it. A plan that put the grind inside the gym sent
        # a L7 MAGIKARP in against MISTY's STARMIE, where it used SPLASH
        # twice and died — a free knockout handed over, and the lead came
        # back to finish the fight at half HP. The plan said "in the wild";
        # this makes the switch obey it.
        if want_slot and ((obs or {}).get("battle") or {}).get("kind") != "wild":
            want_slot = None
        if want_slot and (obs or {}).get("mode") == "battle":
            party = (obs or {}).get("party") or []
            act = ((obs or {}).get("battle") or {}).get("me") or {}
            alive = (len(party) >= want_slot
                     and (party[want_slot - 1].get("hp") or 0) > 0)
            if not alive:
                # A FAINTED TRAINEE EARNS NOTHING. Silently skipping the
                # switch left the lead soaking every battle while the goal
                # waited on a Pokemon that could not be sent out at all.
                self.log("train_switch_blocked", subgoal=subgoal["id"],
                         slot=want_slot, reason="fainted")
            if alive and act.get("species") != party[want_slot - 1].get("species"):
                r = (self._send_safe("battle_switch", slot=want_slot) or {})
                self.log("train_switch_in", subgoal=subgoal["id"],
                         slot=want_slot,
                         ok=(r.get("result") or {}).get("ok"),
                         detail=(r.get("result") or {}).get("detail"))
                obs = self.settle() or obs
        self.status(doing=f"BATTLE ({name} policy)", obs=obs)
        obs = BATTLE_POLICIES[name](self.b, obs, self.log,
                                    self.max_battle_turns,
                                    (_oi.get("want") if _oi and _oi.get("want")
                                     else self._catch_target(subgoal)))
        # spec-rule field cure/heal after the battle (no turn cost) for the
        # neediest party mon: the model's rules decide when an item beats
        # walking on. Cure first — poison keeps chipping until it is.
        pick = battle_policy.should_field_cure(obs, ACTIVE_SPEC)
        if pick:
            self.log("field_cure", subgoal=subgoal["id"], item=pick[0],
                     slot=pick[1])
            obs = self._send_safe("use_item", item=pick[0],
                                  slot=pick[1]) or obs
        pick = battle_policy.should_field_heal(obs, ACTIVE_SPEC)
        if pick:
            self.log("field_heal", subgoal=subgoal["id"], item=pick[0],
                     slot=pick[1])
            obs = self._send_safe("use_item", item=pick[0],
                                  slot=pick[1]) or obs
        return obs

    def _send_safe(self, op, **kw):
        """Bridge send that degrades a timeout to None instead of raising —
        for recovery paths (settle, checkpoints) where an uncaught
        TimeoutError killed brock19's whole run."""
        try:
            return self.b.send(op, **kw)
        except TimeoutError as e:
            self.log("send_timeout", op=op, err=str(e))
            return None

    def seed_regions(self):
        """Hand the game back the place-names this world already learned.

        Called once the bridge is up. Without it the names live only in the
        game process and die with it, so every relaunch re-discovers that
        the far side of a passage is a different place.
        """
        if not self.region_anchors:
            return
        r = self._send_safe("seed_regions", regions=self.region_anchors)
        self.log("seed_regions",
                 maps=len(self.region_anchors),
                 detail=str(((r or {}).get("result") or {}).get("detail"))[:80])

    def settle(self) -> dict:
        """Resolve to a clean decision state before checking guards/predicates.
        A step can leave the game mid-dialogue (e.g. the 'got the PARCEL!' box,
        after which the event flag sets only once it closes), where map reads
        None and map-keyed when-guards would wrongly skip. A `wait` triggers
        the shim's auto-advance, which rides plain text to the next decision.

        NEVER None. Forty-odd callers assign this and roughly half of them go
        straight on to `obs.get(...)`; the ones that do not are the ones that
        happened to be written after a bug. A failed read is an EMPTY state,
        not a missing one — `{}` is just as falsy for every `if obs:` guard,
        `or {}` and `or obs` still work, and an AttributeError deep in a leg
        kills a run that is meant to play unattended for hours."""
        try:
            obs = self.b.obs()
        except TimeoutError as e:
            self.log("send_timeout", op="obs", err=str(e))
            return {}
        for _ in range(12):
            if not obs or obs.get("mode") != "dialog":
                return self._note(obs) or {}
            obs = self._send_safe("wait", frames=6)
        return self._note(obs) or {}

    MACRO_AUTHOR_SYS = """You AUTHOR a macro — an ordered list of ops — to
achieve one Pokemon Red subgoal, then the executor RUNS it. You do NOT pilot
live; you write the whole sequence up front, reading the observation for exact
coordinates. Read:
  obs.map.warps      doors/stairs as {x,y} — use_warp their x,y to exit.
    Where a door leads is not written on it: a door you have walked
    carries walked_to; any other leads to UNKNOWN until you take it.
  obs.map.objects    interactables as {kind,name,x,y} — interact by name
  obs.map.connections which SIDES of this map have a road out (a seam),
    by direction — cross that direction. The road's name is on the TOWN
    MAP if you hold one; otherwise it is "?" until you have crossed it.
    ROUTE: pick the direction that leads toward the goal, using the
    ATLAS of edges you have already walked. ONE LEG PER MACRO: your macro may
    contain at most ONE map-changing op (cross, or use_warp through a door)
    and it must be the LAST op — anything after it is DISCARDED, because you
    cannot know coordinates on a map you are not standing in. You will be
    re-prompted with a fresh observation after arriving.
    The warp tile AT OR NEXT TO your position is the door you came IN by —
    use_warp on it goes BACKWARD. To go forward, pick a warp elsewhere on
    the map (the ledger says which are untried and where the walked ones
    go), or cross an edge.
Ops: {"op":"walk_to","x":N,"y":N} (within-map; when a building splits the
map and you have already walked through it, you are taken round through the
doors you actually used, and told that is what happened), {"op":"cross","dir":"north|
south|east|west"} (to the adjacent map; if that seam cannot be reached from
where you stand but another part of this map you have walked HAS crossed it,
you are taken there first through the doors you used, and told so), {"op":"use_warp","x":N,"y":N} (a
door/stairs; add "map":"MAP_ID" when the door belongs to a map you are NOT
standing on — you are first walked there over ground you have walked, by
the exits you actually took; an unwalked map is refused. walk_to takes
"map" the same way),
{"op":"interact","name":"OBJECT_NAME","answer":"yes"} OR
{"op":"interact","x":N,"y":N,"answer":"yes"} — press A on a TILE rather than
a listed object. Not everything you can press A on is in obs.map.objects:
machines, computers, statues, bookshelves and trash cans are part of the
scenery and are never listed, so a coordinate is the only way to reach one.
If a room's listed objects are exhausted and something in it must still be
operated, press A at the tile it occupies. (answer
accepts a yes/no question the thing asks — taking an item it offers needs
"yes"; with no answer given the question is DECLINED; when the thing then
asks WHICH POKEMON — a trade, a hand-over — say slot=N on the same interact
or it is backed out of, which the game takes as a no), {"op":"menu","index":N}
(1-based: 1=YES/first, 2=NO/second), {"op":"grind"} (pace this map's wild
ground — tall grass outdoors, ANY floor tile in a cave or tower; each battle
is fought and the op repeats until the subgoal's DONE_WHEN is met, whatever
it is — levels, or party size. Add "surf":true to pace the WATER instead of
the land — water has its own encounter table and its own species, and the
harness gets you onto it (SURF must be known).
What the battles are FOR follows the step's
condition (a level → fight; a catch → balls; anything else → wilds are
fled) unless the op says otherwise: "intent":"catch" with "want":"ODDISH"
or a type like "GRASS" or a list (balls thrown at what you name, the rest
fled), "intent":"train" (fight them), "intent":"pass" (flee them). Wild
Pokemon appear by WALKING on such ground, never by standing still, so this
is the
op for TRAINING *and* for finding something to CATCH; {"op":"wait"} will
never produce an encounter),
{"op":"buy","item":"POTION","count":N} (own N total of the item, buying
the difference from THIS map's mart clerk — it talks to the clerk ITSELF,
no interact needed first; obs.money is your budget),
{"op":"use_item","item":"POTION","slot":N} (use a bag item on party slot
N COUNTING FROM 1 — slot 1 is the lead — lead if omitted; this is ALSO
how a TM or HM is TAUGHT: the item
boots and the chosen slot learns the move. A mon that already knows four
moves needs {"op":"use_item","item":"TM_...","slot":N,"forget":"MOVE"}
naming which of ITS OWN four moves to write over — the choice is yours,
made from its move list in obs.party; with no forget the teach is
abandoned and the reply lists the moves),
{"op":"field_move","move":"CUT","x":N,"y":N} (use a field move a party
member KNOWS at the named tile — kind:"cut_tree" objects are the bushes
CUT clears; a fence with a bush in it is a door once you have CUT),
{"op":"toss","item":"TM_BIDE","count":N} (throw away bag items — count
omitted tosses the whole stack. The bag holds 20 KINDS of item and a
FULL bag makes every gift and pickup silently FAIL: "got X!" plays and
nothing arrives. WHICH item to sacrifice is your call),
{"op":"sell","item":"NUGGET","count":N} (sell to THIS map's mart clerk:
raises money AND frees the slot — a NUGGET exists to be sold; key items
are refused. What to part with is your call),
{"op":"store_item","item":"HM_CUT","count":N} (put an item into the PC at
THIS map's PC — every Pokemon Center has one. Frees a bag slot and
DESTROYS NOTHING; obs.pc_items lists what is already in there),
{"op":"retrieve_item","item":"HM_CUT","count":N} (take one back out of
the PC; it fails if the bag is already at 20 kinds),
{"op":"pc_deposit","slot":N} (put party member N into a PC box, at THIS
map's PC. It keeps its levels and moves and can be taken back out; it will
not leave you with an empty party. This is how you make room),
{"op":"pc_withdraw","index":N,"box":B} (take stored Pokemon N back into the
party — obs.pc_mons gives every stored one with its box and index, and box
defaults to the one that is open. Needs a free party slot. A boxed Pokemon
is NOT in the party, so a type or species condition cannot be satisfied by
one sitting in storage),
{"op":"pc_release","index":N,"species":"PIDGEY","box":B} (RELEASE it. It is
gone permanently: no box holds it, and that individual cannot be caught
again. Name the species as well as the index so a shifted list cannot
release the wrong one. Whether releasing anything is a good idea is YOUR
call — this is here so it is available, not because it is advised),
{"op":"daycare_deposit","slot":N} (board party member N with the DAY-CARE
MAN on ROUTE_5. It gains 1 exp for EVERY STEP you walk anywhere in Kanto
and cannot faint, be used, or be switched in while it is there. It takes
one at a time and will not leave you with an empty party. obs.daycare says
who is in and what taking them back costs),
{"op":"daycare_withdraw"} (collect the boarded Pokemon and pay the fee;
needs a free party slot and the money),
{"op":"elevator","floor":"B4F"} (ride an elevator: presses its panel and
picks that floor from the list it offers. Some panels want a key and say
so. After the ride you are STILL INSIDE the car — walk out of its door to
arrive on that floor. A car's floors are NOT doors you can see from
inside it: pressing the panel is the only way to learn where it goes),
{"op":"party_swap","a":1,"b":3} (swap two party slots. SLOT 1 IS WHO GETS
SENT OUT FIRST, in every battle, so this is how you choose who fights and
who is protected — and a Pokemon that never gets sent out never gains a
level. obs.party is in slot order),
{"op":"heal"} (restore the WHOLE party at a Pokemon Center: walks in if
you are outside one on this map and talks to the NURSE. Free, always. It
fails plainly if this map has no Center),
{"op":"wait"}. Battles are auto-handled.
{"op":"tap","btn":"b"} (press B once: closes an open menu, counter or
list you are standing in — the way OUT of a shop counter or a PC screen
you did not mean to open. Nothing is bought, sold or moved by B),
{"op":"skip"} (declare THIS subgoal moot and move the plan on to its next
step: for a step whose condition can no longer come true, or that is
already pointless — you hold what it was for, its event fired under
another name. Say why in your plan; the reason is recorded. It is refused
on a plan's LAST step, which is the objective itself, and the plan is
judged on the objective at the end regardless — skipping does not make
anything true),
{"op":"explore"} (the systematic search step, done for you: it presses
the first thing HERE never pressed; if nothing, takes an exit HERE never
taken; if nothing, walks you over ground you have already walked to the
nearest area that still has one and takes or presses it there. It knows
nothing about where anything leads. It reports what it did and found. It
is the right move when the ledger says the area is fully worked and you
have no better idea of your own; a map-changing op, so it must be the
LAST op of your macro),
{"op":"go","to":AREA} (add "surf":true — like "intent" on grind — to say
"if the way on is water, get on it"; the harness then finds the water beside
ground it can reach and uses SURF, and water becomes walkable. Without it,
water is a wall. walk_to and cross take "surf" the same way.
IF YOU HAVE BEEN SOMEWHERE BEFORE, ONE OP TAKES YOU BACK: it walks the whole route — every door, seam and lift ride you actually
used — in a single action, however many legs it is. AREA as the ledger names
it, e.g. "POKEMON_TOWER_6F|10,2", or a bare map id like "LAVENDER_TOWN" for
the nearest walked part of it. Walked ground only: it fails plainly if no
chain of taken exits joins here to there, and then the way is genuinely not
known yet. PREFER THIS to re-deriving a journey door by door — a nine-leg
walk costs you one round instead of nine, and the rounds are the budget. A
map-changing op, so LAST in your macro),
BLOCKERS: the ledger lists WAYS THAT TURNED YOU BACK anywhere you have been
(a door that refused you, a guard, the ghost) with what was seen or said.
What LIFTS each one is your call, and you can write it down so it is not
worked out twice: add "blockers":[{"where":AREA,"lifts":{condition}}] to
your reply object beside "plan" and "ops" — the condition written like a
DONE_WHEN ({"has_item":{"FRESH_WATER":1}}, {"flag":...}, {"badge":...},
{"party_type":...}) — and the ledger will say when it holds; "cleared":true
marks one dealt with,

HOW TO SEARCH when a step is not working: a thing that has already given
its answer gives the same answer again; repeating it changes nothing. The
ledger marks what HERE is untried, unpressed or unspoken, and what lies
beyond each exit; work through the untried ones first ({"op":"explore"}
takes the next one for you, and keeps taking them, room after room), and
go back to a pressed thing only when something has changed since — the
ledger says when it has. Everything untried, in every room you can reach,
before the same thing again. If a step's own words turn out to describe
something that is not there, {"op":"skip"} moves the plan on.
GROUND TRUTH: your real target is DONE_WHEN. The SUBGOAL text is only a hint
and MAY BE IMPERFECT — if it names a target that isn't in obs.map.objects /
obs.map.warps, or even a different STARTING MAP than the observation shows,
IGNORE the hint and use what the observation actually shows. If a previous
macro made partial progress, the state CARRIED FORWARD — author only the
remaining ops from the current observation. Only interact objects/warps that appear
in the current observation. (E.g. receiving a Pokemon usually means
interacting an item/Poke-Ball object, not an NPC.)
Reply with ONLY a JSON object of the form
{"plan":"one or two sentences, in your own words: what you are doing and
why — this is shown back to you next round, so it is how your strategy
survives from one leg to the next","ops":[{"op":"use_warp","x":7,"y":1}]}
(a bare JSON array of ops is also accepted)."""

    _last_decls: list = []

    @staticmethod
    def _parse_macro(text: str):
        """The macro in a reply, and the model's PLAN if it gave one.

        Returns (ops, plan). Two shapes: {"plan": "...", "ops": [...]} —
        the plan is the model's own sentence about what it is doing, kept
        and echoed next round (EXPLORE_DESIGN §6c) — or a bare array, as
        every reply before 2026-08-18 was. The object is tried first from
        each '{'; a plan text containing '[' cannot fool the array path
        because the array path only runs when no object parsed."""
        dec = json.JSONDecoder()
        idx = text.find("{")
        while idx != -1:
            try:
                obj, _ = dec.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx = text.find("{", idx + 1)
                continue
            if isinstance(obj, dict) and isinstance(obj.get("ops"), list):
                ops = [o for o in obj["ops"] if isinstance(o, dict)]
                plan = str(obj.get("plan") or "").strip()
                # the model's word on blockers rides in the same object;
                # kept on the parser so the caller sees it (a static
                # method cannot store it — the caller reads _last_decls)
                Executor._last_decls = [d for d in (obj.get("blockers") or [])
                                        if isinstance(d, dict)] \
                    if isinstance(obj.get("blockers"), list) else []
                return ops, plan[:400]
            # a single op object, e.g. {"op":"cross","dir":"north"}
            if isinstance(obj, dict) and obj.get("op") and "ops" not in obj:
                return [obj], ""
            idx = text.find("{", idx + 1)
        arr = Executor._parse_macro_array(text)
        return arr, ""

    @staticmethod
    def _parse_macro_array(text: str):
        # raw_decode from each '[' parses the FIRST complete JSON array and
        # ignores trailing prose — a greedy [.*] regex spanned to the last ']'
        # in the reply, so a valid array followed by commentary failed to
        # parse and burned 3 of return_to_oak's 4 rounds on re-prompts.
        dec = json.JSONDecoder()
        idx = text.find("[")
        while idx != -1:
            try:
                arr, _ = dec.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx = text.find("[", idx + 1)
                continue
            out = [step for step in (arr if isinstance(arr, list) else [])
                   if isinstance(step, dict) and "op" in step]
            if out:
                return out
            idx = text.find("[", idx + 1)
        return None

    @staticmethod
    def _goods_delta(pre_obs: dict, obs: dict) -> str:
        """What this op did to the bag and the wallet, in words.

        THE RUN BOUGHT FIFTEEN POKE BALLS WITHOUT MEANING TO, and was
        never told. It had proposed no `buy` op at all — its whole
        vocabulary that run was interact, use_warp, cross, menu and grind —
        but `menu(index=1)` selects BUY and the boilerplate `answer="yes"`
        on the next interact presses A through "That'll be 200. OK?". One
        ball per cycle, fifteen cycles, 3175 money down to 175, and every
        trace line said the same thing:

            interact(VIRIDIANMART_CLERK,answer=yes): ok (map->None, moved,
            dialog still open)

        The harness KNEW. `_snapshot` carries the bag, so the change was
        detected and used internally to keep the op from being marked
        inert, and `money` is right there in the observation. It simply
        was not in the sentence: the change list names map, party and
        movement and nothing else. So the run walked toward Brock broke,
        the way brock37 did at level 8 with 93 money, and nothing it was
        ever shown could have told it why.

        This states the delta and stops. Whether fifteen balls were worth
        3000 is the model's call; it just has to be able to see the bill.
        """
        b0 = (pre_obs or {}).get("bag")
        b1 = (obs or {}).get("bag")
        parts = []
        if isinstance(b0, dict) and isinstance(b1, dict):
            for k in sorted(set(b0) | set(b1)):
                d = (b1.get(k) or 0) - (b0.get(k) or 0)
                if d:
                    parts.append(f"{k} {d:+d} (now {b1.get(k) or 0})")
        m0 = (pre_obs or {}).get("money")
        m1 = (obs or {}).get("money")
        # money is NOT in the snapshot, so a wallet that moves on its own —
        # a blackout halving it — would otherwise be reported by nothing at
        # all. Read it from the observation directly and say it either way.
        if isinstance(m0, int) and isinstance(m1, int) and m0 != m1:
            parts.append(f"money {m1 - m0:+d} ({m1} left)")
        return ("  [" + "; ".join(parts) + "]") if parts else ""

    @staticmethod
    def _snapshot(obs):
        p = (obs or {}).get("player") or {}
        return ((obs or {}).get("map", {}).get("id") if obs else None,
                p.get("x"), p.get("y"), (obs or {}).get("mode"),
                (len((obs or {}).get("party") or []),
                 sum(m.get("level") or 0
                     for m in (obs or {}).get("party") or [])),
                len((obs or {}).get("flags") or []),
                # the BAG is world state too: freeing a slot is exactly
                # the change that makes re-talking a giver worthwhile,
                # and a bag-blind snapshot kept the captain marked inert
                # after the toss that made his gift landable
                (len((obs or {}).get("bag") or {}),
                 sum((obs or {}).get("bag", {}).values()
                     if isinstance((obs or {}).get("bag"), dict) else [])),
                # HP as its own element. Without it a full heal changed
                # NOTHING in the snapshot, so talking to the nurse always
                # read as "no visible effect" — which then marked her inert
                # and refused every later heal. Kept out of the circling
                # test (indices 0/4/5) so taking chip damage is still not
                # mistaken for progress.
                sum(m.get("hp") or 0
                    for m in (obs or {}).get("party") or []),
                # WHICH SCREEN, because "ui" is every screen at once.
                # menu(index=2) opened the item PC instead of the box PC
                # and the snapshot could not tell: both are mode "ui", so
                # a real navigation reported "ran but had NO visible
                # effect (nothing changed)" and the round looked wasted.
                # Trailing, so the circling test (indices 0/4/5) is
                # untouched.
                ((obs or {}).get("ui") or {}).get("screenId"))

    # SAVE ON THE WAY OUT. Both save points sit at the END of an attempt —
    # one for a plan that succeeded, one after the loop "to keep what it
    # earned" when it failed — and there was no signal handling at all, so
    # a SIGTERM partway through an attempt reached neither. Measured on run
    # 11: seven attempts launched, three saves written, and the four
    # missing ones are exactly the attempts that were stopped to land a
    # fix. One of them was carrying the Pokedex and the delivered parcel,
    # and the next attempt started before either.
    #
    # This matters well beyond somebody typing stop: the GPU dropped off
    # the bus once today, and a crash, a power cut or an OOM does the same
    # thing to a run meant to play unattended for hours.
    #
    # The handler only sets a flag. Driving the START menu from inside a
    # signal handler would cut across whatever bridge exchange is in
    # flight; the op loop checks between ops, where the bridge is idle.
    def _install_stop_handler(self):
        import signal

        def _ask_stop(_sig, _frm):
            self._stopping = True
        for _sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(_sig, _ask_stop)
            except (ValueError, OSError):
                pass          # not the main thread; nothing to install

    def _stop_if_asked(self):
        """Between ops: save what this attempt earned, then go."""
        if not getattr(self, "_stopping", False):
            return
        self._stopping = False        # never re-enter this
        r = (self._send_safe("save_game") or {}).get("result") or {}
        print(f"\n[stop] asked to stop mid-attempt — "
              f"{r.get('detail') or 'save failed'}", flush=True)
        self.log("stopped_mid_attempt", saved=bool(r.get("ok")))
        sys.exit(0)

    def _run_traced(self, sg, macro, ignore_done=False):
        """Run a proposed macro step-by-step, returning (done, trace, clean).
        `trace` is plain-English per-op outcomes for feedback (incl. 'ran but
        had NO visible effect'); `clean` is the subset of ops that ran OK —
        what gets DISTILLED, so failed junk ops (e.g. interact 'stairs') the
        model happened to include don't poison the macro and break replay."""
        done = sg.get("done_when")
        trace, clean = [], []
        for step in macro:
            self._stop_if_asked()
            step = dict(step)
            when = step.pop("when", None)
            op = step.pop("op", None)
            self._op_intent = None          # an intent belongs to ONE op
            if not op:
                continue
            obs = self.settle()
            if obs and obs.get("mode") == "battle":
                obs = self.handle_battle(sg, obs)
                obs = self.settle()
            if not ignore_done and pred_holds(done, obs):
                return True, trace, clean
            if when and not pred_holds(when, obs):
                # honor when-guards on replay (verify runs the same guarded
                # macro run_subgoal will): a misplaced op skips, not misfires
                trace.append(f"{op}: skipped (when-guard)")
                continue
            # WHERE IT FAILED IS PART OF THE FAILURE. Without the region in
            # this key, three failures of "cross south" banned crossing
            # south for the whole subgoal no matter where the party later
            # stood — and the refusal it printed claimed "it cannot work
            # FROM HERE", a statement about position made from a key that
            # held none. Cerulean is split by a fence: the south seam is
            # unreachable from the north pocket and reachable from the main
            # city, and an NPC parked in the gap can make even the good
            # side fail transiently. Three such misses sealed the only road
            # to Route 5 for the rest of the leg.
            # {"op":"explore"} — THE FRONTIER STEP, ON REQUEST (EXPLORE_DESIGN
            # §4). Not a shim op: the executor picks the concrete op the
            # ledger ranks first and runs it through this same loop, so
            # every rule below applies to it unchanged.
            if op == "explore":
                _ok, _tr, _cl = self._explore_step(sg, obs, ignore_done)
                trace.extend(_tr)
                clean.extend(_cl)
                if _ok:
                    return True, trace, clean
                continue
            # {"op":"go","to":AREA} — THE WAY YOU KNOW, ON REQUEST. Same
            # machinery explore uses to reach remote ground (walked edges
            # only, _route + _walk_route), offered as an op so a place the
            # run has been can be returned to in one round instead of one
            # round per door: the tower was climbed floor by floor, each
            # floor a full think, six times over.
            if op == "go":
                self._go_surf = bool(step.get("surf"))
                _ok, _tr, _cl = self._go_step(sg, obs, step, ignore_done)
                trace.extend(_tr)
                clean.extend(_cl)
                if _ok:
                    return True, trace, clean
                obs = self.settle() or obs
                continue
            # A DOOR NAMED WITH ITS MAP IS REACHED FIRST. Door coordinates
            # belong to one map, and the model kept aiming use_warp at a
            # door it knew from another map ("no door at (17,13) on
            # VERMILION_CITY"). {"op":"use_warp","map":"ROUTE_6",...} (and
            # walk_to alike) now walks there first, over walked edges only
            # — the same recall machinery as go/explore; nothing unwalked
            # is routed, and an unwalked map is refused by name.
            if op in ("use_warp", "walk_to") and step.get("map"):
                _want = str(step.pop("map")).upper()
                _hr = self._where(obs)
                if _hr.split("|")[0] != _want:
                    _known = [r for r in (set(self.visits or {})
                                          | set(self.explored or {}))
                              if r.split("|")[0] == _want]
                    if not _known:
                        trace.append(
                            f"{op}: {_want} is not a map you have walked — "
                            f"only walked ground can be walked back to; "
                            f"find it first")
                        continue
                    _dk = f"{step.get('x')},{step.get('y')}"
                    _pref = [r for r in _known
                             if _dk in (self.frontier.get(r) or [])
                             or _dk in (self.explored.get(r) or {})]
                    _best = None
                    for _t in (_pref or _known):
                        _pth = self._route(_hr, _t)
                        if _pth and (_best is None
                                     or len(_pth) < len(_best[1])):
                            _best = (_t, _pth)
                    if not _best:
                        trace.append(
                            f"{op}: no walked way from {_hr} to {_want} is "
                            f"known — you have never walked a connected "
                            f"chain of exits between them")
                        continue
                    self.log("prewalk", subgoal=sg.get("id"), op=op,
                             to=_best[0], legs=len(_best[1]))
                    _arr = self._walk_route(sg, _best[1])
                    obs = self.settle() or obs
                    trace.append(
                        f"(first walked {len(_best[1])} leg(s) over walked "
                        f"ground to {_arr or self._where(obs)}, because the "
                        f"op named {_want})")
                    if not ignore_done and pred_holds(done, obs):
                        return True, trace, clean
            # ...AND THE SAME FOR A FIELD MOVE. CUT/STRENGTH aim at a tile
            # and the shim walks to it on THIS map only, so a bush whose
            # component is reachable only by leaving the map and coming
            # back answered "no reachable tile adjacent" for a whole
            # attempt (Route 14, across the ledges). Same recall-only hop.
            if op == "field_move" and step.get("x") is not None:
                _pre = self.settle() or obs
                _r0 = (self._send_safe("field_move", **step) or {})
                _res0 = (_r0.get("result") or {})
                _d0 = str(_res0.get("detail") or "")
                if _res0.get("ok"):
                    obs = self.settle() or _pre
                    trace.append(f"field_move(move={step.get('move')},"
                                 f"x={step.get('x')},y={step.get('y')}): ok"
                                 + (f" — {_d0}" if _d0 else ""))
                    self._record_outcome(_pre, op, step, f"field_move: {_d0}")
                    continue
                if "no reachable tile adjacent" in _d0:
                    _here = self._where(_pre)
                    _mid = _here.split("|")[0]
                    _hopped = 0
                    for _reg in sorted(set(list(self.explored)
                                           + list(self.visits))):
                        if _reg.split("|")[0] != _mid or _reg == _here:
                            continue
                        _path = self._route(_here, _reg)
                        if not _path or _hopped >= 2:
                            continue
                        _hopped += 1
                        self.log("field_move_via_region", subgoal=sg.get("id"),
                                 to=_reg, legs=len(_path))
                        self._walk_route(sg, _path)
                        _cur = self.settle() or _pre
                        _r1 = (self._send_safe("field_move", **step) or {})
                        if ((_r1.get("result") or {}).get("ok")):
                            obs = self.settle() or _cur
                            trace.append(
                                f"field_move(move={step.get('move')}): could "
                                f"not be reached from where you stood, so you "
                                f"were walked {len(_path)} leg(s) over walked "
                                f"ground to {_reg} — and from there it worked")
                            self._record_outcome(_pre, op, step,
                                                 "field_move: ok via " + _reg)
                            break
                    else:
                        obs = self.settle() or _pre
                        trace.append(f"field_move(move={step.get('move')}): "
                                     f"FAILED — {_d0}"
                                     + (f"; nor from the {_hopped} other "
                                        f"part(s) of {_mid} you can walk to"
                                        if _hopped else ""))
                        self._record_outcome(_pre, op, step,
                                             f"field_move: FAILED — {_d0}")
                    continue
                obs = self.settle() or _pre
                trace.append(f"field_move(move={step.get('move')}): FAILED "
                             f"— {_d0}")
                self._record_outcome(_pre, op, step,
                                     f"field_move: FAILED — {_d0}")
                continue
            # ...AND THE SAME FOR A SEAM. `cross` walks to the map's edge
            # from where you stand, so a fence, a building or a river
            # between you and that edge answers "the south seam cannot be
            # walked to from here" — while the run has crossed that very
            # seam from ANOTHER part of the same map (Cerulean's south seam:
            # unreachable from the main square, walked nine times from the
            # eastern strip). Hop to a part that has crossed it, over walked
            # ground, and ask again. Recall only.
            if op == "cross" and step.get("dir"):
                _pre = self.settle() or obs
                _r0 = (self._send_safe("cross", **step) or {})
                _d0 = str((_r0.get("result") or {}).get("detail") or "")
                if (_r0.get("result") or {}).get("ok"):
                    obs = self.settle() or _pre
                    _note = f"cross(dir={step['dir']}): ok"
                    if _d0:
                        _note += f" ({_d0})"
                    trace.append(_note)
                    self._record_outcome(_pre, op, step, _note)
                    if ((_pre.get("map") or {}).get("id")
                            != (obs.get("map") or {}).get("id")):
                        self.note_transition(_pre, step, obs, op_detail=_d0)
                    continue
                if "cannot be walked to" in _d0 or "no walkable path" in _d0:
                    _here = self._where(_pre)
                    _mid = _here.split("|")[0]
                    _dir = step["dir"]
                    _cands2 = [r for r in (self.explored or {})
                               if r.split("|")[0] == _mid and r != _here
                               and _dir in (self.explored.get(r) or {})]
                    for _reg in _cands2[:2]:
                        _path = self._route(_here, _reg)
                        if not _path:
                            continue
                        self.log("cross_via_region", subgoal=sg.get("id"),
                                 to=_reg, dir=_dir, legs=len(_path))
                        self._walk_route(sg, _path)
                        _cur = self.settle() or _pre
                        _r1 = (self._send_safe("cross", **step) or {})
                        if (_r1.get("result") or {}).get("ok"):
                            obs = self.settle() or _cur
                            trace.append(
                                f"cross(dir={_dir}): that seam could not be "
                                f"reached from where you stood, so you were "
                                f"walked {len(_path)} leg(s) over ground you "
                                f"have walked to {_reg} — which HAS crossed "
                                f"it before — and from there it worked")
                            self.note_transition(_cur, step, obs)
                            self._record_outcome(_pre, op, step,
                                                 "cross: ok via " + _reg)
                            break
                    else:
                        obs = self.settle() or _pre
                        trace.append(f"cross(dir={_dir}): FAILED — {_d0}"
                                     + (f"; nor from the {len(_cands2)} other "
                                        f"part(s) of {_mid} that have crossed "
                                        f"it" if _cands2 else ""))
                        self._record_outcome(_pre, op, step,
                                             f"cross: FAILED — {_d0}")
                    continue
                obs = self.settle() or _pre
                trace.append(f"cross(dir={step['dir']}): FAILED — {_d0}")
                self._record_outcome(_pre, op, step, f"cross: FAILED — {_d0}")
                continue
            # A BUILDING IN THE MIDDLE OF A MAP IS NOT A WALL IF YOU HAVE
            # WALKED THROUGH IT. walk_to BFSes one map's cells, so a route
            # gate splitting a road ("no path" to a tile 50 cells east)
            # stopped it dead — while the run had already walked both of
            # that gate's door pairs. Retry through the walked graph: hop to
            # another region OF THIS MAP that we have a walked route to, and
            # ask again from there. Recall only — every hop is a door this
            # run actually took (user, 2026-08-19: "if it HAS walked the
            # edges before, that should def be allowed").
            if op == "walk_to" and step.get("x") is not None:
                _pre = self.settle() or obs
                _r0 = (self._send_safe("walk_to", **step) or {})
                _d0 = str((_r0.get("result") or {}).get("detail") or "")
                if (_r0.get("result") or {}).get("ok"):
                    obs = self.settle() or _pre
                    trace.append(f"walk_to({step.get('x')},{step.get('y')}): ok")
                    self._record_outcome(_pre, op, step, "walk_to: ok")
                    continue
                if "no path" in _d0:
                    _here = self._where(_pre)
                    _mid = _here.split("|")[0]
                    _tried_regions = 0
                    for _reg in sorted(set(list(self.explored)
                                           + list(self.visits))):
                        if _reg.split("|")[0] != _mid or _reg == _here:
                            continue
                        _path = self._route(_here, _reg)
                        if not _path or _tried_regions >= 2:
                            continue
                        _tried_regions += 1
                        self.log("walk_to_via_region", subgoal=sg.get("id"),
                                 to=_reg, legs=len(_path))
                        self._walk_route(sg, _path)
                        _cur = self.settle() or _pre
                        _r1 = (self._send_safe("walk_to", **step) or {})
                        if (_r1.get("result") or {}).get("ok"):
                            obs = self.settle() or _cur
                            trace.append(
                                f"walk_to({step.get('x')},{step.get('y')}): "
                                f"no path from where you stood, so you were "
                                f"walked {len(_path)} leg(s) through ground "
                                f"you have walked before to {_reg} — and "
                                f"from there it worked")
                            self._record_outcome(_pre, op, step,
                                                 "walk_to: ok via " + _reg)
                            break
                    else:
                        obs = self.settle() or _pre
                        trace.append(
                            f"walk_to({step.get('x')},{step.get('y')}): "
                            f"FAILED — {_d0}"
                            + (f"; nor from the {_tried_regions} other part(s)"
                               f" of {_mid} you have walked to"
                               if _tried_regions else ""))
                        self._record_outcome(_pre, op, step,
                                             f"walk_to: FAILED — {_d0}")
                    continue
                obs = self.settle() or _pre
                trace.append(f"walk_to({step.get('x')},{step.get('y')}): "
                             f"FAILED — {_d0}")
                self._record_outcome(_pre, op, step, f"walk_to: FAILED — {_d0}")
                continue
            sig = (self._cur_target, self._where(obs), op,
                   step.get("name") or step.get("dir")
                   or (step.get("x"), step.get("y")))
            # THE LEDGER IS THE GUARD (EXPLORE_DESIGN §2, §6b). Five
            # refusals used to live here — the door you came in by, a map
            # entered twice for this goal, a room already fully searched,
            # a door into a proven dead end, a thing pressed with nothing
            # changed — each of them a fact the ledger now prints on the
            # entry itself, and each of them measured (planner/repeats.py)
            # refusing what the same prompt had offered, then yielding on
            # the third go. Nothing on the ledger is refused. The one
            # refusal left on this ground is OFF-LEDGER: a door, direction
            # or name that is not here at all — the shim would fail it
            # anyway; saying so first is cheaper and names what IS here.
            # (only with a real observation under it: a bridge hiccup that
            # returned {} must not turn every op into "not here")
            if ((obs.get("map") or {}).get("id")
                    and (op in ("use_warp", "cross")
                         or (op == "interact" and step.get("name")))):
                _cands = ledger.build(self, obs, self._cur_target or "",
                                      want_explore=False)
                if ledger.lookup(_cands, step) is None:
                    _keys = [c.label() for c in _cands
                             if c.kind in ("door", "seam")] \
                        if op != "interact" else \
                        [c.key for c in _cands
                         if c.kind not in ("door", "seam", "op")]
                    trace.append(
                        f"{op}({','.join(f'{k}={v}' for k, v in step.items())})"
                        f": REFUSED — OFF-LEDGER: there is no such "
                        f"{'thing' if op == 'interact' else 'door or direction'}"
                        f" here. What is here: {', '.join(_keys[:16]) or 'nothing'}.")
                    continue
            if op == "buy" and step.get("item") in self._cant_afford:
                # The 3-strikes guard keys on the op AND its params, so
                # buying 5, then 3, then 2 Potions looked like three
                # different actions and each got its own three tries. Being
                # unable to afford something is a fact about the ITEM and the
                # WALLET, not about the count — hold it until the money
                # actually changes.
                price = self._cant_afford[step["item"]]
                money = (obs or {}).get("money")
                if isinstance(money, int) and money < price:
                    trace.append(
                        f"buy({step.get('item')}): REFUSED — you have "
                        f"{money} and one costs {price}. No count works, and "
                        f"the price will not change by asking again. Earn "
                        f"money (trainers pay, wild battles do not) or move "
                        f"on without it.")
                    continue
                self._cant_afford.pop(step["item"], None)   # wallet grew
            if op == "interact":
                here_r = self._where(obs)
                # NOTE: marked provisionally, and RETRACTED below if the
                # interact did not actually happen. Marking on intent alone
                # let an unreachable item count as touched, so a floor with
                # item balls still on it reported "everything reachable
                # touched" and was recorded as fully searched.
                if step.get("name"):
                    tried = self._tried_objs.setdefault(here_r, set())
                    tried.add(step["name"])
                    self._stamp_touch(here_r)
                    self._mark_touch(here_r, step["name"], obs)
            if self._dead_ops.get(sig, 0) >= 3:
                # NAME THE OP. This printed the bare op name, so a macro
                # holding two crosses or two interacts was told "cross:
                # REFUSED" with no way to tell which one.
                _args = ",".join(f"{k}={v}" for k, v in step.items()
                                 if k in ("x", "y", "dir", "name", "item"))
                # SAY WHAT STOPPED IT. "It cannot work from here" with no
                # reason left the model re-proposing the gym door after a
                # reload had regrown the bush in front of it — the three
                # failures all said "couldn't reach the warp tile", and the
                # ledger lists that bush as cuttable one line up.
                _why = self._dead_why.get(sig) or ""
                trace.append(f"{op}({_args}): REFUSED — this exact action "
                             "has already failed 3 times in this subgoal "
                             "from this area, with nothing about you "
                             "changed since"
                             + (f", each time: {_why}" if _why else "")
                             + "; it cannot work from here as things stand. "
                             "Whatever stopped it is what has to change.")
                continue
            pre_obs = obs
            before = self._snapshot(obs)
            traversal = op in ("cross", "walk_to", "use_warp", "grind")
            blackout = None
            ghosted = None
            low_hp_flee = ""
            wild_in_way = ""
            _op_det = ""
            # THE OP MAY SAY WHAT ITS BATTLES ARE FOR. The battle policy is
            # chosen per STEP from the step's predicate, so a knows_move
            # step whose model-authored plan was "catch something that can
            # learn CUT" ran grind under the traversal policy and fled
            # every wild — the intent was the model's, and it had no way to
            # say it. {"op":"grind","intent":"catch","want":"ODDISH"} (or a
            # type, or a list) / "intent":"train" / "intent":"pass" now
            # rides on the op for the battles that op starts.
            self._op_intent = None
            _int = str(step.get("intent") or "").lower().strip()
            if _int in ("catch", "train", "fight", "pass", "traversal"):
                _w = step.get("want")
                _wl = ([_w] if isinstance(_w, str)
                       else list(_w) if isinstance(_w, (list, tuple)) else [])
                _wl = [str(x).upper() for x in _wl if str(x).strip()]
                _types = {x for x in _wl if x in TYPE_NAMES}
                _species = {x for x in _wl if x not in TYPE_NAMES}
                self._op_intent = {
                    "intent": _int,
                    "want": ({"species": _species, "types": _types}
                             if (_species or _types) else None)}
            for _ in range(12):
                try:
                    obs = self.b.send(op, **step)
                except TimeoutError:
                    obs = self.b.obs()
                    break
                # the op's OWN detail, before settle/battles replace it —
                # note_transition's door-unknown rule reads it
                _op_det = str(((obs or {}).get("result") or {})
                              .get("detail") or "") or _op_det
                # SAME RECALL FALLBACK AS THE MACRO PATH. Ops are dispatched
                # from two places and this one was missed, so a cross issued
                # here still died on "no walkable path" with the crossing
                # sitting in the ledger.
                _rr = (obs or {}).get("result") or {}
                if (op == "cross" and not _rr.get("ok")
                        and "cannot be walked to" in str(_rr.get("detail"))):
                    _alt = self._cross_by_recall(obs, sg, step.get("dir"))
                    if _alt is None:
                        _alt = self._uncork_seam(obs, sg, step.get("dir"))
                    if _alt is not None:
                        obs = _alt
                if obs and obs.get("mode") == "battle":
                    pre_map = (obs.get("map") or {}).get("id") or before[0]
                    # A room that starts fights is NOT inert. The revisit
                    # refusal exists for rooms with nothing in them; without
                    # this, losing to Brock three times got PEWTER_GYM
                    # refused as "the trigger is not there" and sent the run
                    # wandering east out of town. Losing is a reason to come
                    # back stronger, not evidence of a wrong room.
                    # ...but only a TRAINER makes a room contested. A cave
                    # spawns wild encounters in every corridor, so counting
                    # those marked every Mt Moon room contested, and a
                    # contested room can never be recorded as searched —
                    # which silently disabled the searched and dead-end
                    # ledgers underground, exactly where they matter most.
                    is_wild = ((obs.get("battle") or {}).get("kind")
                               == "wild")
                    # A GHOST is what the screen showed. The traversal
                    # policy flees it without a word, so the op came back
                    # "ok (moved, fled)" and the door it was walking to
                    # stayed plain "untried" — the one fact that says why
                    # the way is shut never reached the model.
                    # ...but only the tower's RESTLESS SOUL stands "in the
                    # way": without the Scope every wild on those floors is
                    # drawn as GHOST too, and a Gastly met on the walk to
                    # the stairs read as the stairs being blocked. The
                    # scripted one is the battle that dodges every ball;
                    # the flag is used for the wording alone.
                    if (obs.get("battle") or {}).get("ghost"):
                        ghosted = ("fixed" if (obs.get("battle") or {})
                                   .get("noCatch") else "wild")
                    if self._cur_target and pre_map and not is_wild:
                        self._battle_regions.add(
                            f"{self._cur_target}|{self._where(pre_obs)}")
                    self._fight_region = (self._where(pre_obs)
                                          if not is_wild else None)
                    # Same rule one level down: an interact that STARTS A
                    # BATTLE did not exhaust the object. A lost fight leaves
                    # the trainer undefeated, and a fossil grab intercepted
                    # by its guard never showed the fossil dialog at all —
                    # counting either as "tried" sealed the fossil room:
                    # every later interact was refused as already-done and
                    # the nerd's flag was declared unreachable in the very
                    # room he stands in.
                    if op == "interact" and step.get("name"):
                        self._retract_touch(self._where(pre_obs),
                                            step["name"])
                    # SAY WHY A TRAINING BATTLE WAS FLED. The spec flees a
                    # wild when the lead is under its HP line, whatever the
                    # goal — right, and invisible: a level grind at 4/25 HP
                    # read "grind: ok (moved, fled)" round after round with
                    # no levels and no word that HP was the reason. The
                    # rule is ours; saying it is not pointing.
                    # A WILD FLED IN A DOORWAY IS THE DOOR NOT OPENING.
                    # The tower's Marowak stands ON the stairs: with the
                    # SILPH SCOPE it is an ordinary wild fight that must be
                    # WON to pass, and the traversal policy fled it every
                    # time — "ok (moved, fled)", no word that a battle was
                    # the thing in the way or that the run chose to flee.
                    if ((obs.get("battle") or {}).get("kind") == "wild"
                            and op in ("use_warp", "cross")
                            and not getattr(self, "_op_intent", None)
                            and choose_battle_policy(sg)[0] == "traversal"):
                        wild_in_way = ((obs.get("battle") or {})
                                       .get("foe") or {}).get("species")
                    _bme = ((obs.get("battle") or {}).get("me") or {})
                    _bkind = (obs.get("battle") or {}).get("kind")
                    _hb = ((ACTIVE_SPEC.get("flee_wild") or {})
                           .get("hp_below"))
                    if (_bkind == "wild" and _hb is not None
                            and _bme.get("maxhp")
                            and (_bme.get("hp") or 0) / _bme["maxhp"] < _hb
                            and choose_battle_policy(sg)[0] != "traversal"):
                        low_hp_flee = (f"{_bme.get('species')} at "
                                       f"{_bme.get('hp')}/{_bme.get('maxhp')} "
                                       f"HP")
                    obs = self.handle_battle(sg, obs)
                    obs = self.settle()
                    post_map = ((obs or {}).get("map") or {}).get("id")
                    # a won battle never changes the map; a party wipe blacks
                    # out and respawns at home/last Center — silently warping
                    # the trajectory (brock15 died in the forest and the next
                    # rounds unknowingly ran from Pallet)
                    if post_map and pre_map and post_map != pre_map:
                        blackout = post_map
                        self._faint_at = before[0] and self._where(pre_obs)
                        self.log("faint_marked", subgoal=sg["id"],
                                 at=self._faint_at)
                        if self._cur_target:
                            self._blackouts[self._cur_target] = \
                                self._blackouts.get(self._cur_target, 0) + 1
                            lv = ((obs or {}).get("party") or [{}])[0]
                            self._blackout_lead[self._cur_target] = \
                                lv.get("level")
                            self._save_memory()
                            # A room is contested when a fight here BEAT US:
                            # that is the unfinished business worth coming
                            # back for. A trainer you defeated leaves the
                            # room ordinary, and marking those too kept
                            # every populated room out of the searched
                            # ledger for the rest of the run.
                            reg = self._fight_region
                            c = self.contested.setdefault(self._cur_target, {})
                            if reg and "None" not in reg and not c.get(reg):
                                c[reg] = True
                                self.searched.get(self._cur_target,
                                                  {}).pop(reg, None)
                                self.searched.get("*", {}).pop(reg, None)
                        self.log("blackout", subgoal=sg["id"], op=op,
                                 respawn=post_map)
                        break
                    # interact resumes after a battle too. Only traversal
                    # ops were re-sent, so an interact whose approach walk
                    # was jumped by a wild resolved the battle and then
                    # reported "ok (moved, battle ended)" — telling the
                    # model it fought the nerd when it fought a Zubat, and
                    # ending an intercepted fossil grab with no fossil. If
                    # the battle WAS the target's own, the re-send lands on
                    # after-text and exits on the first battle-free pass.
                    if ((traversal or op == "interact")
                            and not pred_holds(done, obs)):
                        continue
                break
            r = (obs or {}).get("result") or {}
            # THE PRESS THAT LANDED COUNTS. The provisional touch above is
            # retracted when a battle interrupts the interact, and the
            # re-sent interact that then reaches the thing never re-marked
            # it — so on a cave floor, where every approach step rolls a
            # wild, a person reached through a Geodude stayed "never
            # pressed" for ever and explore pressed him again next round
            # (Rock Tunnel B1F, SUPER_NERD2, twice running). Mark on the
            # landing; the blackout / asked / failed retractions below still
            # undo it where they should.
            if op == "interact" and step.get("name") and r.get("ok"):
                _hr = self._where(pre_obs)
                if _hr and "None" not in str(_hr):
                    self._tried_objs.setdefault(_hr, set()).add(step["name"])
                    self._stamp_touch(_hr)
                    self._mark_touch(_hr, step["name"], obs)
            after = self._snapshot(obs)
            # A MAP OF None IS A MID-TRANSITION READ, NOT A PLACE. An op
            # that ends while a menu or a warp fade is still up snapshots
            # map=None, and the note then told the model "ok (map->None)" —
            # which reads as "you are in a UI state" and had it pressing B
            # at an overworld it was already standing in (the hideout
            # elevator, three rounds). Settle once and read again.
            if after[0] is None and not blackout:
                _o2 = self.settle()
                if ((_o2 or {}).get("map") or {}).get("id"):
                    obs = _o2
                    after = self._snapshot(obs)
            # STATE-BASED blackout fallback. The battle-mode detector only
            # fires when the executor sees mode=="battle" after an op — but
            # grind/cross/walk_to fight their encounters INSIDE the Lua op,
            # so a wipe during one of those lands at a Pokemon Center with
            # the executor never having seen a battle. It then had no
            # faint marker and the walk-back never armed: a wipe in Mt
            # Moon landed at the Viridian centre and the run stalled there.
            # A gen1 blackout is unmistakable in state: you did not ask to go
            # there, you are in a Center, and the whole party is suddenly at
            # full HP.
            # Excluding cross/use_warp was wrong: you cannot CROSS into a
            # Pokemon Center, and warping in while hurt does not heal you —
            # the HP-rise test already rules both out. The exclusion just
            # meant a wipe during those ops went undetected and the walk-back
            # never armed. Gen1 also respawns at HOME before any Center has
            # been used, so accept that too. Only a checkpoint restore can
            # legitimately teleport-and-heal.
            respawn_like = (str(after[0]).endswith("POKECENTER")
                            or after[0] in ("REDS_HOUSE_1F", "PALLET_TOWN"))
            if (not blackout and before[0] and after[0] and before[0] != after[0]
                    and respawn_like and op != "checkpoint_restore"):
                mons = (obs or {}).get("party") or []
                healed = bool(mons) and all(
                    m.get("max_hp") and m.get("hp") == m["max_hp"] for m in mons)
                # index 7 is the party's HP SUM; 6 is (bag kinds, bag total).
                # Testing the bag here meant a wipe inside a Lua op — grind,
                # cross, walk_to, where mode never reads "battle" — was only
                # ever caught when the bag happened to grow on the same step.
                if healed and after[7] > before[7]:
                    blackout = after[0]
                    self._faint_at = self._where(pre_obs)
                    if self._cur_target:
                        self._blackouts[self._cur_target] = \
                            self._blackouts.get(self._cur_target, 0) + 1
                        self._blackout_lead[self._cur_target] = \
                            ((obs or {}).get("party") or [{}])[0].get("level")
                        self._save_memory()
                    self.log("blackout", subgoal=sg["id"], op=op,
                             respawn=after[0], detected="state")
                    self.log("faint_marked", subgoal=sg["id"],
                             at=self._faint_at)
            # WHAT PEOPLE SAID IS EVIDENCE. This game explains its own
            # gates in dialogue — the guard who wants a drink, the man who
            # is too sleepy to move — and the words were being dropped the
            # instant the box closed. Keep them against the region so a
            # later round, or a later attempt, can read why it is stuck.
            said = ((obs or {}).get("last_text") or "").strip()
            heard = ""
            if said and self._op_spoke(pre_obs, obs, said):
                self._last_said = said
                who = step.get("name") or op
                reg = self._where(pre_obs)
                # The harness's own noise is not a hint: saving, using an
                # item and buying all print a line the game addressed to
                # nobody. Keep what a NAMED thing said, and anything else
                # only if it does not read as a system confirmation.
                low = said.lower()
                noise = any(w in low for w in
                            ("saved the game", "saving", "got potion",
                             "put it in", "found ", " learned ",
                             "grew to lv", "gained ", "exp. points"))
                # unconditional: last_text SURVIVES the box closing, so an
                # interact that produced no dialogue of its own inherits
                # whatever was said last — the save banner got filed under
                # the Charmander ball that way.
                if noise:
                    said = ""
                # _op_spoke has already decided this line belongs to this
                # op; the only thing left is the first-op guard, which
                # stops the very first observation inheriting whatever was
                # on screen before the run started.
                heard = said if self._said_ready else ""
                if said and "None" not in reg and len(said) > 12:
                    lst = self.hints.setdefault(reg, [])
                    line = f"{who}: {said[:220]}"
                    if line not in lst:
                        lst.append(line)
                        del lst[:-8]
                        if not hasattr(self, "hints_at"):
                            self.hints_at = {}
                        self.hints_at.setdefault(reg, {})[line] = len(
                            (obs or {}).get("flags") or [])
                        self._save_memory()
            self._said_ready = True
            note = f"{op}({','.join(f'{k}={v}' for k, v in step.items())})"
            # A DECLINED QUESTION IS NOT A TOUCH, however the state moved.
            # This retraction used to live in the "nothing changed" branch,
            # but reaching a fossil means WALKING to it, so the snapshot had
            # moved and the branch never ran: both fossils came back
            # "declined" and were still recorded as touched. The room then
            # read as fully worked, the untouched-things line stopped naming
            # them, and the one prompt that would have made the model try
            # again with answer="yes" never appeared — leaving the corridor
            # east shut behind a question nobody answered.
            # NOR IS A TOUCH THAT ENDED IN A WIPE. Reaching for the Mt
            # Moon fossil starts the Super Nerd fight; losing it blacks the
            # party out and the fossil is NOT taken — but the press was
            # recorded, so the room read as fully worked and the sweep
            # never offered either fossil again. An interaction whose
            # outcome was a faint has not been made.
            if blackout and op == "interact" and step.get("name"):
                self._retract_touch(self._where(pre_obs), step["name"])
            if (ASKING in str(r.get("detail") or "")
                    and op == "interact" and step.get("name")):
                self._retract_touch(self._where(pre_obs), step["name"])
            # A PICKER BACKED OUT OF IS A QUESTION UNANSWERED. "asked WHICH
            # POKEMON, and nothing here had chosen one — backed out" counted
            # as a touch, so the Vermilion trader read as pressed 4x and her
            # room as fully worked, when the one thing she asked was never
            # answered. Same rule as ASKING: it is not a touch until it is.
            if ("asked WHICH POKEMON" in str(r.get("detail") or "")
                    and "backed out" in str(r.get("detail") or "")
                    and op == "interact" and step.get("name")):
                self._retract_touch(self._where(pre_obs), step["name"])
            if not r.get("ok"):
                # THREE FAILURES ARE THREE FAILURES IN ONE WORLD. The
                # refusal below is absolute and never expired, so an op
                # that could not work before CUT was learned, before a
                # guard moved, before a key was in the bag stayed refused
                # for the rest of the subgoal — the same over-claim the
                # dead-end brand made one layer up. Stamp the world mark
                # with the count and start again when the world moves.
                _mk = getattr(self, "_mark_now", None)
                if self._dead_at.get(sig) != _mk:
                    self._dead_ops[sig] = 0
                    self._dead_at[sig] = _mk
                self._dead_ops[sig] = self._dead_ops.get(sig, 0) + 1
                self._dead_why[sig] = str(r.get("detail") or "")[:160]
                note += f": FAILED — {r.get('detail')}"
                # An interact that never happened leaves the thing UNTOUCHED.
                # Without this the provisional mark stands, and a room whose
                # items could not be reached this time counts as fully
                # worked — a false searched proof that stops the run ever
                # coming back for them.
                if op == "interact" and step.get("name"):
                    self._retract_touch(self._where(obs), step["name"])
                # Some failures are DEFINITIVE about this place, not about
                # the attempt: a shop that does not stock the item will
                # never stock it. Without recording that, shopping_for_potions
                # burned ~15 rounds re-entering the Viridian mart, which does
                # not sell POTION at all, and reached Brock with no heals.
                det = str(r.get("detail") or "")
                # Name the problem as MONEY and say what actually fixes it.
                # The bare "cannot afford" was retried as if it were a
                # pathing failure; it is not, and no amount of walking back
                # to the counter changes it.
                # A tile you cannot path to is often a PERSON standing on
                # the way, not geometry — Viridian's old man blocks the road
                # until you talk to him, and the run stood in front of him
                # re-proposing the same warp. Talking is free and people
                # move once their business is done.
                import re as _re
                if "cannot afford" in det and step.get("item"):
                    m = _re.search(r"it costs (\d+)", det)
                    if m:
                        self._cant_afford[step["item"]] = int(m.group(1))
                    # A blocked purchase is unfinished business, exactly
                    # like a lost battle: the WALLET is exhausted, not the
                    # room. Without this, the mart got marked fully worked
                    # and its door refused for item:POTION long after the
                    # money problem had passed.
                    if self._cur_target:
                        reg = self._where(obs)
                        c = self.contested.setdefault(self._cur_target, {})
                        if reg and "None" not in reg and not c.get(reg):
                            c[reg] = True
                            self.searched.get(self._cur_target, {}).pop(reg, None)
                            self.searched.get("*", {}).pop(reg, None)
                            self._save_memory()
                if ("couldn't reach the warp tile" in det
                        or "no path" in det):
                    near = [o.get("name") for o in
                            ((obs.get("map") or {}).get("objects") or [])
                            if o.get("reachable")
                            and o.get("kind") in ("npc", "trainer")
                            and o.get("name") not in
                            self._tried_objs.get(self._where(obs), set())]
                    if near:
                        trace.append(
                            f"You could not path there. Someone may be "
                            f"STANDING in the way — people move once you "
                            f"have talked to them. Reachable people here you "
                            f"have not spoken to: {', '.join(near[:5])}. "
                            f"Interact with them, then try the route again.")
                if op == "cross" and "seam of" in det and (
                        "terrain blocks" in det
                        or "cannot be walked to" in det):
                    # The cross op seam-searches the WHOLE edge, so one
                    # failure proves no cell of this component crosses it.
                    # Leaving it in the frontier made it the "nearest
                    # unopened door" forever — the hint kept selling the
                    # east seam of the Route 4 stub while the real way
                    # east sat two ladders down.
                    d0 = step.get("dir")
                    here0 = self._where(obs)
                    # ...BUT NOT IF YOU HAVE ALREADY CROSSED IT. "One
                    # failure proves no cell of this component crosses it"
                    # is only sound for a road never yet walked. Cerulean's
                    # south seam had been crossed 14 times with 70 visits on
                    # Route 5 when a single failed attempt filed it as
                    # uncrossable — and every later exits list hid it, so
                    # the way to the DAY CARE stopped being offered at all.
                    # A road that has opened before is a road something is
                    # standing in TODAY, which is a different fact.
                    _prev = (self.explored.get(here0) or {}).get(d0) or {}
                    _crossed_before = (
                        _prev.get("to") and _prev.get("to") != here0
                        and not _prev.get("shut")
                        and (self.visits.get(_prev["to"]) or 0) > 0)
                    if d0 and not _crossed_before:
                        self._no_cross.setdefault(here0, set()).add(d0)
                        self._no_cross_at.setdefault(here0, {})[d0] = \
                            self._world_mark(obs)
                    elif d0:
                        self.log("cross_failed_but_known", region=here0,
                                 exit=d0, to=_prev.get("to"))
                    fr = self.frontier.get(here0)
                    if d0 and fr and d0 in fr:
                        fr.remove(d0)
                        self.log("frontier_pruned",
                                 region=here0, exit=d0,
                                 why="seam proven uncrossable")
                    self._save_memory()
                if op == "interact" and step.get("name") and (
                        "no reachable tile adjacent" in det
                        or "not visible" in det):
                    # Where the thing WAS seen. Dead ends and visit counts
                    # only say where the target is NOT; the sightings ledger
                    # earned the positive fact on an earlier visit, and the
                    # graph knows the walked way back. Without this, a plan
                    # that descended into the wrong B2F room burned its
                    # rounds wandering 1F while the nerd's room sat 6 walked
                    # legs away. Same standard as THE KNOWN WAY THERE:
                    # observed evidence, surfaced at the moment of need —
                    # the model still chooses.
                    name = step["name"]
                    here_now = self._where(obs)
                    # A POSITION-MINTED NAME IS NOT UNIQUE ACROSS MAPS. Items
                    # are named ITEM_x_y (contents are not ours to say), and
                    # (8,3) exists on dozens of floors — so the Warden's
                    # House item was "SEEN, reachable, in OAKS_LAB" and the
                    # run was sent across Kanto for a different ball. Match
                    # such names only within the SAME MAP.
                    _pos_named = str(name).startswith("ITEM_")
                    _here_map = here_now.split("|")[0]
                    seen_in = [reg for reg, objs in self.sightings.items()
                               if name in objs and reg != here_now
                               and (not _pos_named
                                    or reg.split("|")[0] == _here_map)]
                    routed = False
                    for reg in seen_in:
                        path = self._route(here_now, reg)
                        if not path:
                            continue
                        first_key, first_dest = path[0]
                        leg = (f"walk {first_key}"
                               if not first_key[0].isdigit()
                               else f"the door at ({first_key})")
                        trace.append(
                            f"{name} is not reachable from THIS area — but "
                            f"you have SEEN it, reachable, in {reg}. You "
                            f"have walked a route there before: start by "
                            f"taking {leg} to {first_dest} "
                            f"({len(path)} leg(s) total).")
                        routed = True
                        break
                    if seen_in and not routed:
                        trace.append(
                            f"{name} is not reachable from THIS area, but "
                            f"you have SEEN it, reachable, in {seen_in[0]} "
                            f"— no walked route from here is known, so "
                            f"explore toward it.")
                if "cannot afford" in det:
                    trace.append(
                        "That is a MONEY problem, not a route problem — "
                        "walking back to this counter will not change it. "
                        "Either buy FEWER (lower the count to what you can "
                        "afford), or go and earn money first: every trainer "
                        "you beat pays prize money, and wild battles do not. "
                        "If neither is worth it, move on without the item — "
                        "this subgoal can stay unfinished.")
                # THE SHELF IS A FACT ONCE SEEN. "not sold here — this mart
                # sells: ..." was said eleven times about FRESH_WATER at
                # the Vermilion mart and lived only in those rounds'
                # traces; every new subgoal re-supposed the water was there.
                # Kept per mart, persisted, printed on the mart's door.
                _sh = _re.search(r"this mart sells: ([A-Z0-9_, ]+)", det) \
                    if "this mart sells" in det else None
                if _sh:
                    _cm = ((obs or {}).get("map") or {}).get("id")
                    if _cm:
                        self._shelves[_cm] = [x.strip() for x in
                                              _sh.group(1).split(",")
                                              if x.strip()]
                        self._save_memory()
                if "is not sold here" in det and self._cur_target:
                    self.note_dead_end(self._cur_target, self._where(obs),
                                       shop_proof=True)
                    trace.append(
                        f"PROVEN: this shop does not stock it and never "
                        f"will. Either buy what IS on this shelf if it "
                        f"serves the goal, or leave and find another shop — "
                        f"do not try this counter again.")
            elif before == after:
                det0 = str(r.get("detail") or "")
                if ASKING in det0:
                    note += f": {det0}"
                else:
                    # A SENTENCE IS NOT NOTHING. Saying "NO visible effect"
                    # and then quoting a line that names the next objective
                    # files the answer under a denial — which is what
                    # happened to "Okay! Say hi to PROF.OAK for me!".
                    # Nothing about the WORLD changed either way; only the
                    # framing moves.
                    note += (": the world did not change, but it SPOKE"
                             if heard else
                             ": ran but had NO visible effect "
                             "(nothing changed)")
                    # ...AND KEEP WHAT THE OP ITSELF SAID. A no-change
                    # result dropped the op's own detail behind "it SPOKE",
                    # so the trader's WHICH POKEMON back-out — "backed out
                    # (which the game takes as a no); re-send with slot=N"
                    # — reached the ledger only as her "That's too bad",
                    # four times, and read as a refusal by her.
                    if det0 and det0 not in ("ok", "done") \
                            and det0[:60] not in note:
                        note += f" — {det0[:220]}"
                    if op == "interact" and step.get("name"):
                        # remember WHICH state it was useless in; if the
                        # world changes (hp drops, a flag fires) it is
                        # worth another go
                        self._inert_objs.setdefault(
                            self._where(pre_obs), {})[step["name"]] = before
            else:
                chg = []
                if before[0] != after[0]:
                    chg.append(f"map->{after[0]}")
                if before[4] != after[4]:
                    chg.append("party changed")
                if (before[1], before[2]) != (after[1], after[2]):
                    chg.append("moved")
                det = r.get("detail")
                if det:
                    chg.append(str(det))
                note += ": ok" + (f" ({', '.join(chg)})" if chg else "")
            if (op == "grind" and "fled" in note and not low_hp_flee
                    and not getattr(self, "_op_intent", None)
                    and choose_battle_policy(sg)[0] == "traversal"):
                note += (" — the battles under this step run the traversal "
                         "policy (wilds are fled) because the step's "
                         "condition is not a catch or a level; to CATCH "
                         "with grind say so on the op — {\"op\":\"grind\","
                         "\"intent\":\"catch\",\"want\":\"SPECIES or TYPE\"} "
                         "(balls thrown at what you name, the rest fled) — "
                         "or \"intent\":\"train\" to fight them")
            if (wild_in_way and "fled" in note
                    and before[0] == after[0]):
                note += (f" — a wild {wild_in_way} was in the way and this "
                         f"step's battles run the traversal policy, so it "
                         f"was FLED and the way stayed shut. If that battle "
                         f"is the thing blocking you, say so on the op — "
                         f"{{\"op\":\"{op}\",...,\"intent\":\"fight\"}} "
                         f"— and it will be fought instead")
            if low_hp_flee and "fled" in note:
                note += (f" — fled because your lead was {low_hp_flee}: "
                         f"under {int(_hb * 100) if _hb else 20}% a wild "
                         f"fight is fled to keep it alive, so a grind at "
                         f"this HP earns nothing; heal first (a Center, or "
                         f"a POTION) and it fights")
            if ghosted == "fixed":
                note += (" — a GHOST appeared on the way there, and you fled "
                         "from it")
            elif ghosted:
                note += " — a wild GHOST appeared, and you fled from it"
            if blackout:
                note += (f" — your party FAINTED mid-op (blackout): you "
                         f"respawned at {blackout}, party healed, position "
                         f"progress lost")
            if r.get("ok") and before[0] != after[0] and not blackout:
                self.note_transition(pre_obs, step, obs, op_detail=_op_det)
                # RECOGNISE A DEAD END ON ARRIVAL. The exit-level warning
                # only covers exits already taken FROM here, so an untried
                # ladder that happens to drop into a known-bad room walked
                # in unchallenged (user watched it happen). Landing is the
                # other moment we can check — and it also teaches the edge,
                # so next time the exit itself carries the warning.
                land = self._where(obs)
                bad = self.dead_for(self._target_key(sg), land)
                if bad:
                    trace.append(
                        f"ARRIVED IN A KNOWN DEAD END: {land} — this goal has "
                        f"already failed here {bad}x. Nothing here achieves "
                        f"it. Leave by a different exit than the one you "
                        f"came in by.")
                    self.log("arrived_dead_end", subgoal=sg["id"],
                             region=land, times=bad)
                    break
            # WHAT IT SAID, IN THE ROUND THAT SAID IT — WHETHER OR NOT THE
            # OP WORKED. The words used to be filed to the region ledger
            # and nowhere else, deduplicated, so a line could be recorded
            # once and never again while the round's own feedback read "ok
            # (moved)" whether a press had opened a lock or turned up
            # trash. Attaching them only to SUCCESS was the same mistake
            # one level up: the Saffron guard speaks precisely because you
            # could not get past him, so the op reports "couldn't reach the
            # warp tile" and his explanation — the one that says the gate
            # wants a drink — was dropped every time. A failed op is
            # exactly when this game explains itself.
            # WHATEVER IT COST, ON EVERY BRANCH. Deliberately outside the
            # ok/no-effect/failed split, because a purchase that rides an
            # op is exactly as real when the op is reported as failing —
            # and "the world did not change" is flatly false about a wallet
            # that just lost 200.
            note += self._goods_delta(pre_obs, obs)
            if heard:
                note += f' — it said: "{heard[:160]}"'
            trace.append(note)
            self._record_outcome(pre_obs, op, step, note)
            # A BUSH YOU CUT COMES BACK ON RELOAD in this recomp. Remember
            # where you cut, so the regrown bush can be named as the same
            # one — the run cut the Vermilion gym's bush, the campaign
            # relaunched, and it then insisted the path was clear while
            # the door failed three times "couldn't reach the warp tile".
            if (op == "field_move" and str(step.get("move")).upper() == "CUT"
                    and r.get("ok") and "hacked away" in note):
                _cm = ((pre_obs or {}).get("map") or {}).get("id")
                if _cm and step.get("x") is not None:
                    self._cut_bushes.setdefault(_cm, [])
                    _xy = f"{step.get('x')},{step.get('y')}"
                    if _xy not in self._cut_bushes[_cm]:
                        self._cut_bushes[_cm].append(_xy)
                        self._save_memory()
            self.status(last=note, obs=obs, doing=f"{op} {json.dumps(step)}")
            # distill an op if it ran OK *or* changed the state — cross via the
            # Oak escort reports ok=False ("cross attempted") yet the map
            # changes, and menu ops have delayed effects; only genuinely-failed
            # no-ops (interact 'stairs') are both not-ok and inert, so dropped.
            if r.get("ok") or before != after:
                # stamp the map this op actually ran from: on replay a
                # diverged trajectory (different blackout timing, a
                # pre-check-skipped subgoal) SKIPS misplaced ops instead of
                # misfiring them — replay1/2 both died to position-blind
                # replays of the grind journey
                rec = {"op": op, **step}
                if before[0]:
                    rec["when"] = {"map": before[0]}
                clean.append(rec)
            # A QUESTION ON SCREEN ENDS THE MACRO. The shim deliberately
            # leaves a yes/no box open rather than answer it with an
            # `answer:` that was written before the question could be read
            # — and then the NEXT op in the same macro ran anyway, into a
            # game that was not in the overworld. At the Mt Moon fossils
            # that meant pressing the DOME FOSSIL asked "You want the DOME
            # FOSSIL?", the very next op pressed the HELIX FOSSIL and
            # stacked a second question onto the first, and nothing ever
            # answered either. Stopping here hands the box to the UI
            # handler, which puts the words to the model and presses what
            # comes back — the only path by which either fossil is takeable.
            if ASKING in str(r.get("detail") or ""):
                trace.append(
                    "— stopped here: a question is on screen and must be "
                    "answered before anything else can run.")
                break
            if not ignore_done and pred_holds(done, self.settle()):
                return True, trace, clean
        return pred_holds(done, self.settle()), trace, clean

    @staticmethod
    def _pos(obs):
        p = (obs or {}).get("player") or {}
        return (p.get("x"), p.get("y"))

    def escalate(self, sg: dict, redo: bool = False, blocked_by: str = "",
                 avoid_region: str = "",
                 blocked_target: str = "") -> tuple[bool, list]:
        """SPD escalation: the model AUTHORS a candidate macro (its strength),
        the executor RUNS it with a per-step trace, and on success distills.
        On failure the DIAGNOSTIC trace (which ops did nothing / where it
        ended) is fed back so the model can rethink — not just 'try again'.

        Rounds CARRY STATE FORWARD and clean ops ACCUMULATE: a failed round's
        partial progress (e.g. exiting a building the subgoal turned out to
        start inside) stands, and the next round authors the remainder from
        the current observation. The start checkpoint is only for the final
        distill-then-verify replay (and a bail-out if the state is lost) —
        restoring between rounds destroyed cross-round progress and made the
        feedback describe a state the restore had just reverted (brock7
        go_to_route_1: rounds 1 and 3 both escaped Oak's lab and the restore
        pulled the player back inside both times)."""
        goal = sg.get("goal_text", sg["id"])
        done = sg.get("done_when")
        rounds = sg.get("escalation_rounds", 4)
        # A REPEAT OFFENDER earns a shorter leash. The rap sheet used to
        # reset every attempt: go_to_route_3 burned 167 journal entries on
        # its THIRD identical failure while the untested subgoals at the
        # plan's tail never ran at all. A subgoal id that already failed
        # in earlier attempts keeps at least one round (the world may have
        # changed) but never again a full budget.
        prior_fails = self._prior_subgoal_fails.get(sg["id"], 0)
        dw_kind = pred_keys(sg.get("done_when") or {})
        is_gate = bool(dw_kind & {"flag", "badge", "has_item"})
        # The discount exists for doomed MARCHES. A gate is where the
        # searching actually happens and already earns a deeper budget —
        # discounting it strangled defeat_lt_surge to ONE round for a
        # four-act siege the moment navigation stopped being the reason
        # it had failed.
        if prior_fails and not is_gate:
            # ...BUT NEVER BELOW WHAT IT TAKES TO TRY. Subtracting one
            # round per past failure took a much-failed map hop down to a
            # SINGLE round — and one round cannot walk into a cave, never
            # mind cross it. Mt Moon was being attempted 1 round at a time
            # after the first few losses, which reads as "failing really
            # quickly" and guarantees it never gets further. The discount
            # is meant to stop a doomed march wasting a deep budget, not
            # to make the attempt impossible.
            rounds = max(3, rounds - prior_fails)
            print(f"   (failed {prior_fails}x in earlier attempts — "
                  f"budget {rounds} round(s))")
        # An EVENT GATE is load-bearing: failing it now ENDS the plan (a
        # missed event cannot be walked past), so giving it the same budget
        # as a trivial map hop meant whole attempts died in ~60s on the one
        # subgoal that actually needed searching. Gates get a deeper budget.
        _dw = pred_keys(sg.get("done_when") or {})
        if _dw & {"flag", "badge"}:
            rounds = max(rounds * 3, 12)
        if redo:
            # relocating across a dungeon takes many legs; the round budget
            # for a normal subgoal is far too small (thin5 ran out inside
            # the mountain, mid-journey, and reported failure)
            rounds = max(rounds, 20)
        feedback = "This is the first attempt."
        inert = []          # targets that ran but did nothing / failed
        backward = []       # ops that moved us to an already-visited map
        progress = []       # clean ops accumulated across rounds
        # NOT reset per escalation: an op that cannot work does not become
        # possible because a new escalation started. use_warp(32,7) failed
        # "couldn't reach the warp tile" once per escalation for 22 rounds
        # because the ledger was wiped each time. Keyed by target, so a
        # different goal still gets a clean slate.
        self._dead_visits = 0
        free_rounds = 0
        self._cur_target = self._target_key(sg)
        # ...AND THE SUBGOAL ITSELF, not just its predicate. _target_key
        # throws the words away, and the words are the only thing that says
        # whether a creature is to be CAUGHT or HANDED OVER. See _hunted.
        self._cur_sg = sg
        self._plan_said = ""      # a plan belongs to the subgoal it served
        self._plans_said = []
        self._stale_rounds = 0    # the stale budget counts per subgoal
        self._stale_fp = None
        self._left_target = set() # target maps walked out of on purpose
        self._dead_why = getattr(self, "_dead_why", {})
        self._idle_rounds = 0     # laps count per subgoal, not per run
        self._seen_this_sg = set()   # rooms this subgoal has stood in
        self._stuck_in: dict = {}
        # NOT reset here: a fresh escalation forgetting what it already
        # interacted with is why the run kept talking to the same Jigglypuff
        # round after round. Same class as the op ledger and the revisit
        # counter — evidence has to outlive the attempt that learned it.
        self.log("escalate_start", subgoal=sg["id"], goal=goal)
        cap = self._send_safe("checkpoint_capture", token="esc") or {}
        can_reset = bool((cap.get("result") or {}).get("ok"))
        self.log("escalate_checkpoint", subgoal=sg["id"], captured=can_reset)
        # A round that CHANGED something (map/party/flags) is progress and
        # does not spend budget — multi-leg subgoals need one leg per round.
        # The absolute cap bounds oscillation (A<->B crossings are each "a
        # map change" yet go nowhere).
        spent, rnd, chat_fails = 0, 0, 0
        redo_from = self._pos(self.settle()) if redo else None
        pardon = False        # one free revisit after a blackout (recovery)
        visits: dict = {}     # round-end maps: re-entering one = circling
        while spent < rounds and rnd < rounds * 3:
            # A ROUND BOUNDARY IS THE OTHER SAFE POINT. Checking only
            # between ops was not enough: an escalation spends most of its
            # wall clock inside a model call, a Python signal handler
            # cannot run until that blocking call returns, and a stop
            # issued mid-round waited past 25s and got SIGKILLed with
            # nothing written. Here the bridge is idle and the last round's
            # work is already in the world.
            self._stop_if_asked()
            rnd += 1
            start = self.settle()
            # NEVER ASK THE MODEL FROM INSIDE A FIGHT. settle() resolves
            # dialogue but not battles, so a wild that jumped the party at
            # the end of the last round left mode=="battle" standing here —
            # and the round built its whole context and asked for a macro
            # with the battle screen up. Watched live: "I am currently in a
            # wild battle with an Ekans. I will fight the battle to return
            # to the map, then..." — the model narrating its way out of a
            # fight the POLICY exists to handle, one model call per round,
            # and every op it can propose fails "not in overworld" until
            # the fight ends. Fights are the policy's; ops are the model's.
            _fights = 0
            while start and start.get("mode") == "battle" and _fights < 8:
                start = self.handle_battle(sg, start)
                start = self.settle()
                _fights += 1
            if _fights:
                self.log("battle_drained_before_round", subgoal=sg["id"],
                         round=rnd, fights=_fights)
            # THE WORLD MAY HAVE CAUGHT UP SINCE THE LAST CHECK. A trade's
            # animation outlasted round 2's post-op check, so the party
            # read unchanged then and the model was asked a round 3 it
            # answered with "skip" — filed as the leg failing. Look before
            # asking: a condition that holds at a round's start is done.
            if rnd > 1 and not redo and pred_holds(done, start):
                self.log("escalate_success", subgoal=sg["id"], round=rnd,
                         proposed=0, distilled=len(progress), verified=False,
                         how="held at the start of the round")
                return True, progress
            # ...and the whole PLAN's objective: a wander can stand on it
            # while a middle step grinds (Lavender, during a heal detour).
            # Succeeding this subgoal hands control to run_plan, whose
            # objective check ends the leg.
            _fin2 = (((self.plan or {}).get("subgoals") or [{}])[-1]
                     or {}).get("done_when")
            if (not redo and _fin2 and _fin2 is not done
                    and sg.get("id") != (((self.plan or {}).get("subgoals")
                                          or [{}])[-1] or {}).get("id")
                    and pred_holds(_fin2, start)):
                self.log("escalate_success", subgoal=sg["id"], round=rnd,
                         proposed=0, distilled=len(progress), verified=False,
                         how="the plan's OBJECTIVE holds here")
                return True, progress
            # A PURCHASE YOU CANNOT AFFORD IS NOT A SEARCH PROBLEM. Once
            # the price is known and the wallet is short, no amount of
            # walking changes it — yet buy_potions burned a whole attempt's
            # rounds re-entering the mart, and backtracks kept re-opening
            # it. End the leg immediately and let the rest of the plan run;
            # the model's own advice already says it may stay unfinished.
            tgt0 = self._target_key(sg)
            if tgt0.startswith("item:"):
                item0 = tgt0.split(":", 1)[1]
                price0 = self._cant_afford.get(item0)
                money0 = (start or {}).get("money")
                if (price0 and isinstance(money0, int) and money0 < price0):
                    self.log("escalate_unaffordable", subgoal=sg["id"],
                             item=item0, price=price0, money=money0)
                    print(f"   (cannot afford {item0}: {money0} < {price0} "
                          f"— leaving this subgoal unfinished)")
                    return False, sg.get("macro", [])
            # WALKED GROUND IS NEVER THE MODEL'S PROBLEM. When the target
            # is a region this run has walked and a route exists from
            # here, walk it before spending a model round: the wander
            # machinery dragged heal_at_vermilion — a fully-walked target
            # three rooms away — to the Route 5 daycare, because nothing
            # made known navigation mechanical outside the unreachable
            # branch. Arrive first; the model handles what arriving
            # cannot (the nurse, the fight, the switch).
            tk0 = self._target_key(sg)
            # a BADGE lives in its gym, and which gym holds which badge
            # is printed in the pamphlet — badge hunts route like travel.
            # The gym itself may be unroutable on a fresh boot (its door
            # bush REGROWS on reload), so its city's doorstep is the
            # fallback: arrive there and let the model cut its way in.
            cands = []
            if tk0.startswith("badge:"):
                g = BADGE_GYMS.get(tk0.split(":", 1)[1])
                if g:
                    cands = [g, g.replace("_GYM", "_CITY")]
            elif tk0.startswith(("map:", "area:")):
                cands = [tk0.split(":", 1)[1]]
            here0 = self._where(start)
            r0 = None
            # A PLACE THE MODEL WALKED OUT OF ON PURPOSE IS NOT WALKED BACK
            # INTO FOR IT. Watched live at Misty: fainted in the gym, "heal
            # first" in its plan, walked out to the city — and this block
            # walked it back into the gym at the top of every round, four
            # times, before it could reach the Center. Once the model has
            # left the target map by its own op this escalation, the
            # known-way walk stands down for that target; the ledger's
            # KNOWN WAY line still names the first leg, and it can walk
            # back the moment it means to.
            _left = getattr(self, "_left_target", set())
            cands = [c for c in cands if c.split("|")[0] not in _left]
            for dest0 in cands:
                if here0.startswith(dest0.split("|")[0]):
                    r0 = None
                    break
                if "|" in dest0:
                    r0 = self._route(here0, dest0)
                else:
                    for _reg in set(list(self.explored)
                                    + list(self.visits)):
                        if _reg.split("|")[0] != dest0:
                            continue
                        _p = self._route(here0, _reg)
                        if _p and (r0 is None or len(_p) < len(r0)):
                            r0 = _p
                if r0:
                    break
            if r0:
                self._walk_route(sg, r0)
                start = self.settle() or start
                if pred_holds(done, start):
                    # SAY THAT A ROUTE WAS WALKED. Op-count is not a proxy
                    # for "nothing happened": a trainer engages you as you
                    # walk into their line of sight, so this branch WON THE
                    # MISTY FIGHT in 241 seconds while proposing zero ops —
                    # and the author, reading distilled==0, was told the
                    # badge was "already true on arrival, nothing was done"
                    # under thirty WIPED lines for that same fight. The one
                    # success in the run rendered as a no-op.
                    self.log("escalate_success", subgoal=sg["id"],
                             round=rnd, proposed=0, walked=len(r0),
                             distilled=len(progress), verified=False)
                    return True, progress
            sig0 = self._snapshot(start)
            if rnd == 1 and sig0[0]:
                visits[sig0[0]] = 1
            obs = model_view(start, holding_map=self._holding_town_map(start),
                             walked_dest=self._walked_dest)
            atlas = self._atlas_text(
                ((start or {}).get("map") or {}).get("id"))
            redo_note = ""
            if redo:
                redo_note = (
                    "\n\nREDO: you ALREADY satisfy DONE_WHEN — but you are in "
                    "the WRONG PLACE. The next objective (" + blocked_by +
                    ") turned out to be impossible from here, which means this "
                    "map has more than one area that satisfies DONE_WHEN and "
                    "you reached the wrong one. Get to a DIFFERENT place that "
                    "also satisfies it — typically by going back the way you "
                    "came and taking another route. Standing still is failure.")
            memory = self.exploration_text(start, self._target_key(sg), sg)
            # A FULL BAG fails every gift silently: the captain's HM01
            # played its "got it!" text into a 20-of-20 bag and vanished.
            # The game normally says "no room" on screen; say it here.
            nkinds = len((start or {}).get("bag") or {})
            if nkinds >= 18:
                state = ("FULL — every gift and pickup now FAILS: the "
                         "'got it!' text plays and NOTHING arrives"
                         if nkinds >= 20 else
                         "NEARLY FULL — a gift needing a fresh slot is "
                         "about to fail silently")
                memory += (
                    f"\nYOUR BAG holds {nkinds} of 20 kinds: {state}. "
                    "Free slots on YOUR judgment — USING a consumable "
                    "spends it and keeps its value: a TM teaches its "
                    "move ({\"op\":\"use_item\",\"item\":\"TM_...\","
                    "\"slot\":N,\"forget\":\"MOVE\"} when four moves are "
                    "known), a RARE_CANDY raises a level, HP_UP and its "
                    "kin permanently boost a stat, heals heal. SELLING "
                    "at a mart clerk raises money AND frees the slot "
                    "({\"op\":\"sell\",\"item\":...} — a NUGGET exists "
                    "to be sold). TOSSING dumps dead weight "
                    "({\"op\":\"toss\",\"item\":...}). STORING at any "
                    "Pokemon Center's PC frees the slot and destroys "
                    "nothing, so it is the only reversible one "
                    "({\"op\":\"store_item\",\"item\":...}, and "
                    "{\"op\":\"retrieve_item\",...} brings it back; "
                    "obs.pc_items is what the PC already holds). "
                    "Whoever tried to hand you a thing will hand it "
                    "again once there is room.")
            # Log what the model was actually TOLD. Most of this session's
            # bugs were "the signal never reached the model" (dead ends only
            # in failure feedback, the too-weak note shadowed by an elif,
            # LAST_MAP unresolved), and each took a whole run to find because
            # the prompt was never recorded anywhere.
            self.log("escalate_context", subgoal=sg["id"],
                     target=self._target_key(sg), memory=memory[:6000])
            # ...and the ECHO the model reads beside it. The context log was
            # written before plan_echo exists, so the one part of the prompt
            # that carries the model's own beliefs forward — the part that
            # explains why a dead idea keeps coming back — has never been in
            # the journal, and reading a stuck leg meant guessing at it.
            # THE PLAN ECHO (§6c). 80% of proposals are one op, so the
            # model re-derives its intent every round with nothing of its
            # own carried forward — the trace it reads is ours. Its last
            # plan, in its words, goes back to it beside what happened.
            plan_echo = ""
            _hist = list(self._plan_hist.get(self._cur_target or "?", []))
            # this escalation's own plans first; earlier attempts' plans for
            # the same target behind them, so a supposition that failed
            # last attempt is on the page when it is about to be made again
            _older = [tuple(x) for x in _hist
                      if tuple(x) not in {tuple(y) for y in self._plans_said}]
            _older = _older[-4:]
            if self._plans_said or _older:
                plan_echo = "YOUR LAST PLANS, in your own words, oldest first, "\
                            "with where you stood when you wrote each"
                if _older:
                    plan_echo += (" (the first ones are from EARLIER ATTEMPTS "
                                  "at this same step)")
                def _pl(t):
                    _r, _w, _p = t[0], t[1], t[2]
                    _v = t[3] if len(t) > 3 and t[3] else ""
                    return (f"  R{_r} (at {_w}): {_p}"
                            + (f"  → {_v}" if _v else ""))
                plan_echo += ":\n" + "\n".join(
                    _pl(t) for t in (_older + list(self._plans_said))) + "\n"
            # ...AND WHAT YOU HAVE DONE FOR THIS STEP, over every attempt:
            # the outcome ledger summed across areas — op, how many times,
            # what happened last. The ledger block shows it per area; this
            # is the whole step's rap sheet in eight lines.
            _tk = self._cur_target or ""
            _agg: dict = {}
            for _k, _book in (self._outcomes or {}).items():
                if not _k.startswith(_tk + "|"):
                    continue
                _area = _k.split("|", 1)[1]
                for _key, _rec in (_book or {}).items():
                    _e = _agg.setdefault(_key, {"n": 0, "last": "", "where": _area})
                    _e["n"] += int(_rec.get("n") or 0)
                    _e["last"] = _rec.get("last") or _e["last"]
            _tried = sorted(_agg.items(), key=lambda kv: -kv[1]["n"])[:8]
            if _tried and sum(v["n"] for _, v in _tried) >= 4:
                plan_echo += ("WHAT YOU HAVE DONE FOR THIS STEP SO FAR, over "
                              "every attempt (thing, how many times, what "
                              "happened last):\n"
                              + "\n".join(
                                  f"  {k} x{v['n']} at {v['where']}"
                                  + (f" — {v['last'][:110]}" if v['last'] else "")
                                  for k, v in _tried) + "\n")
            if plan_echo:
                self.log("escalate_echo", subgoal=sg["id"], round=rnd,
                         echo=plan_echo[:2000])
            user = (f"SUBGOAL: {goal}\nDONE_WHEN: {json.dumps(done)}"
                    f"{redo_note}\n{memory}\n"
                    f"ATLAS (map edges and doors you have observed so far): "
                    f"{atlas or 'nothing yet'}\n"
                    f"{plan_echo}"
                    f"FEEDBACK FROM YOUR LAST MACRO:\n{feedback}\n"
                    f"CURRENT_OBSERVATION: "
                    f"{json.dumps(obs, separators=(',', ':'))}\n"
                    "Author the op-list macro to achieve DONE_WHEN from here. "
                    "If ops in the feedback 'had no visible effect', they did "
                    "NOT do what you intended — try a different approach.")
            try:
                reply = brock_probe.chat(
                    [{"role": "system", "content": self.MACRO_AUTHOR_SYS},
                     {"role": "user", "content": user}], self.model)
            except Exception as e:
                # ONE BAD SECOND IS NOT THE END OF THE SUBGOAL. This used to
                # `break`, forfeiting every remaining round: ollama swapping
                # a model out costs one refused connection and cost this leg
                # its whole escalation budget. chat() now retries internally;
                # if it still fails, that is one round spent, not all of
                # them. Three in a row is a server that is not coming back.
                self.log("escalate_chat_error", subgoal=sg["id"], round=rnd,
                         err=str(e))
                chat_fails += 1
                if chat_fails >= 3:
                    self.log("escalate_chat_giveup", subgoal=sg["id"],
                             fails=chat_fails)
                    break
                spent += 1
                continue
            Executor._last_decls = []
            macro, plan_said = self._parse_macro(reply)
            _decl_lines = self._declare_blockers(Executor._last_decls, obs)
            if _decl_lines:
                self.log("blockers_declared", subgoal=sg["id"], round=rnd,
                         lines=_decl_lines)
            if plan_said:
                self._plan_said = plan_said
                self._plans_said.append((rnd, self._where(start), plan_said))
                del self._plans_said[:-4]
                _ph = self._plan_hist.setdefault(self._cur_target or "?", [])
                _ph.append([rnd, self._where(start), plan_said])
                del _ph[:-8]
                self._save_memory()
            # {"op":"skip"} — THE MODEL DECLARES THIS STEP MOOT. Until now
            # a subgoal was done only when its predicate held, so a step
            # gated on a flag the model itself chose wrongly could be
            # SEEN through ("I already have Poke Balls…") and still not
            # stepped past. Its judgment, its stated reason; the plan moves
            # to the next step. Not on the LAST step: that is the objective,
            # and the objective is what the leg is judged on afterwards.
            if any(isinstance(s2, dict) and s2.get("op") == "skip"
                   for s2 in (macro or [])):
                # A SKIP OF A STEP THAT IS ALREADY TRUE IS SUCCESS. The
                # trade completed during round 2's animation; the check
                # after that round saw the party unchanged, the model saw
                # DUX in the party and said skip — and skip on the last
                # step was filed as the leg failing, then backtracked to
                # "redo" the walk into a house it was standing in. Look
                # again before ruling on the skip.
                _now = self.settle()
                if not redo and pred_holds(sg.get("done_when"), _now):
                    self.log("escalate_success", subgoal=sg["id"], round=rnd,
                             proposed=0, distilled=0, verified=False,
                             how="the step's condition held at the skip")
                    print(f"   (skip asked, but {sg['id']}'s condition "
                          f"already holds — done)")
                    return True, []
                subs = (self.plan or {}).get("subgoals") or []
                idx = next((i for i, s2 in enumerate(subs)
                            if s2.get("id") == sg.get("id")), None)
                if idx is not None and idx == len(subs) - 1:
                    # A SKIP AIMED AT THE FINAL STEP IS A VERDICT ON THE
                    # LEG (user, 2026-08-18): the model is saying the
                    # objective is already fulfilled or its condition is
                    # wrong. The step is not skipped — that is the ladder's
                    # call — but the verdict is recorded with its reason
                    # and no more rounds are spent on the step: the attempt
                    # ends and the rewrite / wording rung reads "the model
                    # asked to skip the final step" in the journal digest.
                    self.log("skip_last_step", subgoal=sg["id"], round=rnd,
                             reason=self._plan_said)
                    print(f"   (the model asked to skip the plan's final "
                          f"step {sg['id']}: {(self._plan_said or '')[:120]} "
                          f"— recorded as its verdict; ending the attempt)")
                    return False, sg.get("macro", [])
                self.log("subgoal_skipped", subgoal=sg["id"], round=rnd,
                         reason=self._plan_said)
                print(f"   (the model skipped {sg['id']}: "
                      f"{(self._plan_said or '')[:120]})")
                self._skipped = sg["id"]
                return True, []
            if not macro:
                self.log("escalate_bad_proposal", subgoal=sg["id"], round=rnd,
                         reply=reply[:600])
                feedback = ("Your last reply held no ops. Return ONLY a JSON "
                            "object {\"plan\":\"...\",\"ops\":[...]} "
                            "(or a bare JSON array of ops).")
                spent += 1
                continue
            # ONE LEG PER MACRO, enforced: ops after the first map-changing op
            # target a map the model has never seen — always hallucinated.
            cut = next((i for i, s in enumerate(macro)
                        if s.get("op") in ("cross", "use_warp", "explore",
                                           "go")),
                       None)
            stripped = 0
            if cut is not None:
                if cut + 1 < len(macro):
                    self.log("escalate_truncated", subgoal=sg["id"], round=rnd,
                             kept=cut + 1, dropped=len(macro) - cut - 1)
                    macro = macro[:cut + 1]
                # cross/use_warp path-find from wherever you stand; a walk_to
                # prelude is never needed and walking onto a door mat
                # teleports (the Pallet<->lab oscillation burned 8 rounds of
                # go_to_route_2 on walk_to(12,11) = the lab door).
                keep = [s for s in macro[:-1] if s.get("op") != "walk_to"]
                stripped = len(macro) - 1 - len(keep)
                if stripped:
                    self.log("escalate_stripped_walkto", subgoal=sg["id"],
                             round=rnd, dropped=stripped)
                    macro = keep + [macro[-1]]
            self.log("escalate_proposal", subgoal=sg["id"], round=rnd,
                     macro=macro, plan=self._plan_said)
            self.status(subgoal=sg["id"], goal_text=goal, done_when=done,
                        obs=self.settle(),
                        phase=("REDO " if redo else "") + f"escalation {rnd}",
                        doing=json.dumps(macro)[:150])
            ok, trace, clean = self._run_traced(sg, macro,
                                                ignore_done=redo)
            if _decl_lines:
                trace = list(_decl_lines) + list(trace)
            if ok and redo:
                # "somewhere else that also satisfies it": a couple of tiles
                # is the same place. A real relocation crosses the map (the
                # east half of Route 4 is ~70 cells from the west half).
                cur_obs = self.settle() or {}
                region = (cur_obs.get("map") or {}).get("region")
                land = self._where(cur_obs)
                failed_here = self.dead_for(blocked_target, land)
                if failed_here:
                    ok = False
                    trace.append(
                        f"(you satisfied the condition again in {land}, but "
                        f"the objective that sent you back here has already "
                        f"failed from there {failed_here}x — that is the "
                        f"same wrong place. Somewhere ELSE satisfies this.)")
                # the test is REGION, not distance: thin7 went back into the
                # cave and out the SAME door — tiles away, same dead end
                if avoid_region and region == avoid_region:
                    # ...but a demand nobody can meet is not a plan. If the
                    # area has no untried way out, no other region can be
                    # reached from it, and insisting only burns the budget:
                    # exit_mt_moon sat at REDO round 31 on ROUTE_4 already
                    # satisfying its own condition. Accept and move on.
                    if not self._untried_exits(cur_obs):
                        trace.append(
                            "(you are back where you started, and this area "
                            "has no untried way out — accepting it rather "
                            "than demanding a relocation that is not "
                            "possible from here.)")
                        self.log("redo_accepted_no_exits", subgoal=sg["id"],
                                 region=land)
                    else:
                        ok = False
                        trace.append(
                            "(you are back in the SAME walkable area you "
                            "started from — the same places are reachable, so "
                            "nothing has changed. You must reach a DIFFERENT "
                            "area: a door you have not used, the far side of "
                            "the map.)")
            if stripped:
                trace.insert(0, f"(note: {stripped} leading walk_to op(s) "
                             "dropped — cross/use_warp path-find on their "
                             "own; never use door tiles as waypoints)")
            progress.extend(clean)
            if ok and sg.get("no_verify"):
                # grind-style subgoals are non-deterministic repetition: a
                # verify replay would need the whole grind again under fresh
                # RNG, and done_when IS the verification. Commit directly.
                self.log("escalate_success", subgoal=sg["id"], round=rnd,
                         proposed=len(macro), distilled=len(progress),
                         verified=False)
                return True, progress
            if ok:
                # DISTILL-THEN-VERIFY: a macro is only trustworthy if it
                # reproduces the subgoal from the clean start (walk_to onto a
                # door mat can fire the warp once by luck and fail on replay;
                # use_warp is reliable). Replay the ACCUMULATED clean ops (all
                # rounds' partial progress concatenated) from the start
                # checkpoint; commit only if they reach done_when again.
                restored = False
                if can_reset and VERIFY_MACROS:
                    rr = self._send_safe("checkpoint_restore", token="esc") or {}
                    restored = bool((rr.get("result") or {}).get("ok"))
                if restored:
                    v_ok, _, v_clean = self._run_traced(sg, progress)
                    # a 0-op "verified" while the first run needed ops means the
                    # restore didn't actually reset the relevant state (some
                    # gate/event state isn't in the checkpoint) — the verify is
                    # meaningless, so keep the accumulated clean ops.
                    if v_ok and (v_clean or not progress):
                        self.log("escalate_verified", subgoal=sg["id"],
                                 round=rnd, ops=len(v_clean))
                        return True, v_clean
                    if v_ok and not v_clean and progress:
                        self.log("escalate_verify_noreset", subgoal=sg["id"],
                                 round=rnd, ops=len(progress))
                        return True, progress
                    self.log("escalate_unverified", subgoal=sg["id"], round=rnd)
                    feedback = (
                        "Your ops reached the goal ONCE but did NOT reproduce "
                        "it on a clean replay — some op relied on luck or "
                        "approach. For doors/stairs/exits use use_warp{x,y} "
                        "(reliable), NOT walk_to onto the tile. You are back "
                        "at the SUBGOAL START; author the FULL sequence from "
                        "the current observation.")
                    self._send_safe("checkpoint_restore", token="esc")
                    progress = []
                    spent += 1
                    continue
                # couldn't restore to verify (some states refuse it) — commit
                # the accumulated clean ops best-effort rather than a bogus
                # 0-op "verified" from an un-reset replay.
                self.log("escalate_success", subgoal=sg["id"], round=rnd,
                         proposed=len(macro), distilled=len(progress),
                         verified=False)
                return True, progress
            cur = self.settle() or {}
            # three shapes of PROOF that this area cannot serve this goal:
            #   object present but no adjacent tile reachable
            #   map edge exists but its seam cannot be walked to
            #   warp exists but its tile cannot be reached
            # the third is the characteristic failure INSIDE a dungeon and
            # was missing, so cave rooms never got marked and the run kept
            # reconsidering them: finished cave rooms stayed unlabelled.
            in_control = (cur.get("mode") == "overworld"
                          and not (cur.get("player") or {}).get("moving"))
            unreachable = [] if not in_control else [t for t in trace
                           if "no reachable tile adjacent" in t
                           or "cannot be walked to from" in t
                           or "couldn't reach the warp tile" in t]
            # An object you can REACH but have not TOUCHED can be the
            # blocker itself — Mt Moon's fossils sit in the corridor and
            # taking one clears it. Proving a room barren while such an
            # object is still un-clicked is not a proof at all: pure14
            # called B2F hopeless with a reachable fossil untouched, so the
            # corridor stayed shut and the super nerd was never found.
            # Same law the transitive pruner obeys — geometry can change.
            # A dead end is a claim that this place can NEVER serve the
            # goal, so it must rest on something permanent. Being short of
            # money is not: PEWTER_MART got item:POTION marked dead while
            # the shop stocks Potions perfectly well and the wallet later
            # held 1423. Same for any other retryable shortfall.
            retryable = any(("cannot afford" in t or "couldn't reach the clerk" in t
                             or "no shop clerk" in t) for t in trace)
            live = []
            if cur:
                _tried = self._tried_objs.get(self._where(cur), set())
                # An untouched ITEM counts even when it reads unreachable
                # right now. Reachability is judged from the four tiles
                # around an object at this instant, so a wanderer standing
                # in the one open approach tile makes a perfectly pathable
                # item ball look unreachable — it then vanished from this
                # list and the floor signed off as fully worked with items
                # still on it. People move; items do not, so an untouched
                # item is unfinished business either way.
                _tried = self._untaken(cur.get("map") or {}, _tried)
                # A BUSH IS NOT A THING YOU HAVE NEVER INTERACTED WITH:
                # interact by name never reaches one, so counting it here
                # sent the model to "interact CUT_TREE" (watched live).
                live = [o.get("name") for o in
                        ((cur.get("map") or {}).get("objects") or [])
                        if (o.get("reachable") or o.get("kind") == "item")
                        and o.get("kind") != "cut_tree"
                        and o.get("name") not in _tried]
                # FIXTURES ARE SWITCHES: pressable AGAIN by nature, and
                # some puzzles REQUIRE re-pressing (the gym's trash-can
                # locks reset on a wrong guess). A room holding reachable
                # fixtures is never provably barren — the abandon fired
                # here with Surge unreachable behind his locked door and
                # fifteen once-pressed cans standing right there.
                live += [o.get("name") for o in
                         ((cur.get("map") or {}).get("objects") or [])
                         if o.get("kind") in ("fixture", "cut_tree")
                         and o.get("reachable")
                         and o.get("name") in _tried]
            # REDO suppresses the done-check on purpose (its job is to
            # relocate, not to satisfy the goal), so every redo round looks
            # like a failure even standing on the answer. Recording proofs
            # from that produced "map:PALLET_TOWN is unreachable from
            # PALLET_TOWN" — self-contradictory, and persisted across runs.
            if redo or retryable:
                pass
            elif unreachable and cur and live:
                trace.append(
                    f"Do NOT conclude this area is a dead end yet: you can "
                    f"reach {len(live)} thing(s) here you have never "
                    f"interacted with ({', '.join(live[:6])}). Something you "
                    f"can reach but have not touched may BE the obstacle — "
                    f"picking an item up or moving it can open a way that is "
                    f"shut. Interact with all of them before leaving.")
            elif cur and (unreachable
                          or (not self._untried_exits(cur) and not live
                              and not self._unopened_doors(cur))):
                # entry condition covers BOTH shapes: a reachability failure,
                # or a room that is simply finished (no untried exit, nothing
                # untouched). The latter produces no failure trace at all,
                # which is why finished rooms were never being labelled.
                here = self._where(cur)
                # CONFIRM against the map before calling it geography. A
                # script can block an exit that is perfectly walkable (the
                # rival intercepts you leaving Oak's lab), and that failure
                # looks identical in the trace — but it does NOT change the
                # reachability flags. Only mark when the map agrees.
                cmap = cur.get("map") or {}
                confirmed = any(
                    not w.get("reachable") for w in (cmap.get("warps") or []))
                confirmed = confirmed or any(
                    not o.get("reachable") for o in (cmap.get("objects") or []))
                confirmed = confirmed or any(
                    "cannot be walked to from" in t for t in trace)
                # A cave room almost always contains SOME unreachable rock
                # or ledge-gap item, so "any object here is unreachable" is
                # not evidence about anything in particular — it stamped
                # flag:EVENT_BEAT_MT_MOON_3_SUPER_NERD onto B1F rooms four
                # times, and the nerd is on B2F. Two extra conditions:
                #   - the region must have NO untried exit left. While an
                #     unopened door remains you cannot conclude anything is
                #     unreachable from here (the transitive pruner's rule,
                #     applied to the primary proof).
                #   - a FLAG target needs SEAM evidence, not scenery: a rock
                #     you cannot walk to says nothing about an event on
                #     another floor.
                tk = self._target_key(sg)
                seam_evidence = any("cannot be walked to from" in t
                                    or "couldn't reach the warp tile" in t
                                    for t in trace)
                # FULLY WORKED is itself the strongest proof: every exit
                # taken, everything reachable touched, condition still false.
                # Tightening the other shapes left this case unmarked, so a
                # finished room never got labelled and the run kept coming
                # back to it. (Distinct from "escalation rounds ran out",
                # which is NOT evidence — this is about the room, not the
                # budget.)
                # A room you were DUMPED in proves nothing. After a wipe the
                # party stands in a Pokemon Center it did not choose to
                # enter and leaves immediately — that recorded the Center as
                # "searched" for whatever the goal was, a proof about the
                # blackout rather than the room.
                if self._faint_at:
                    pass
                elif (not self._untried_exits(cur) and not live
                      and not self._unopened_doors(cur)):
                    # SEARCHED, not sealed. Every exit taken and everything
                    # touched proves the target is not IN this room — it does
                    # NOT prove the target is unreachable THROUGH it. Marking
                    # a dead end here branded B1F corridor rooms unreachable
                    # for a B2F flag, and the run then refused the very
                    # ladders leading down to it. Record it as searched so
                    # the room is not re-worked, and leave passage alone;
                    # whether everything beyond is hopeless is the transitive
                    # pruner's job, computed on demand.
                    confirmed = False
                    self.note_searched(tk, here)
                elif self._untried_exits(cur):
                    confirmed = False
                    self.log("dead_end_withheld", subgoal=sg["id"],
                             region=here, reason="untried exits remain")
                elif tk.startswith("flag:") and not seam_evidence:
                    confirmed = False
                    self.log("dead_end_withheld", subgoal=sg["id"],
                             region=here, reason="scenery is not flag evidence")
                if confirmed:
                    self.note_dead_end(tk, here)
                objs = [o for o in ((cur.get("map") or {}).get("objects")
                                    or []) if not o.get("reachable")]
                seam = any("cannot be walked to from" in t
                           or "couldn't reach the warp tile" in t
                           for t in trace)
                # A TRAVEL goal cannot be killed by a barren room. EVERY
                # room on the way back to Pewter is "barren" for
                # map:PEWTER_CITY — what matters is whether the walked
                # graph still knows the way onward. Abandoning on the
                # local-room proof ended return_to_pewter three rounds in,
                # and the potion stop it guarded never happened: the run
                # entered the mountain with an empty bag again.
                routed = None
                if tk.startswith(("map:", "area:")):
                    dest = tk.split(":", 1)[1]
                    if "|" in dest:
                        routed = self._route(here, dest)
                    else:
                        for region in set(list(self.explored)
                                          + list(self.visits)):
                            if region.split("|")[0] != dest:
                                continue
                            p = self._route(here, region)
                            if p and (routed is None or len(p) < len(routed)):
                                routed = p
                if (objs or seam) and routed:
                    # EXECUTE the route, never merely advise it. The
                    # advice version was watched live: the run stood in
                    # the fence house with the route computed, was told
                    # "keep moving", proposed cross(south) from the wrong
                    # side again, and left by the door it came in.
                    # Walking edges the run itself walked before is
                    # replay, not decision.
                    walked_to = self._walk_route(sg, routed)
                    trace.append(
                        f"Nothing in THIS room serves the goal, so the "
                        f"walked route toward {tk} was taken "
                        f"({len(routed)} leg(s)): now at "
                        f"{walked_to or 'an unexpected stop'} — continue "
                        f"from here.")
                elif objs or seam:
                    self.log("target_unreachable", subgoal=sg["id"],
                             target=self._target_key(sg), region=here,
                             objects=[o.get("name") for o in objs][:5])
                    # This REGION is proven barren — but that is not the same
                    # as the subgoal being hopeless, and killing it here threw
                    # away the whole goal the moment one room failed. Mt Moon
                    # B2F has three separate regions; pure14 proved the first
                    # one barren and gave up with two never entered, so the
                    # super nerd was never found. Same rule the transitive
                    # pruner already obeys: an untried door blocks the
                    # conclusion.
                    ways = self._untried_exits(cur)
                    if not ways:
                        # "Nothing here and no door left" is precisely when
                        # to WALK somewhere that still has one — not when
                        # to end the subgoal. This break fired on the Route
                        # 4 stub every attempt, two rounds in, short-cutting
                        # past the escort further down the loop and ending
                        # the leg with the whole east side unvisited.
                        # ...UNDER THE LEDGER THE WALK IS THE MODEL'S
                        # (explore). Watched live in Cerulean: cross south
                        # failed at the fence, this escorted the party into
                        # the Pokemon Center (5 things never pressed), the
                        # model walked out and tried south again, and round
                        # after round it was walked back in. The ledger
                        # names the trashed house's untried back door and
                        # explore would take it; the choice is the model's.
                        moved = (None if USE_LEDGER else
                                 self._route_to_frontier(cur, sg, patient=True))
                        if moved:
                            cur = self.settle() or cur
                            trace.append(
                                f"Nothing here serves this goal and no exit "
                                f"is unopened, so you were walked to {moved}, "
                                f"which still has doors never taken. Take one.")
                            continue
                        if USE_LEDGER:
                            # say it, and let the round go on: the ledger's
                            # remote lists name where ways never taken are
                            # and explore walks there; ending the subgoal
                            # here was the escort's shadow
                            trace.append(
                                f"Nothing in {here} serves this goal and no "
                                f"exit here is unopened. Areas you have been "
                                f"that still have ways never taken are "
                                f"listed above with their first leg; "
                                f"{{\"op\":\"explore\"}} walks to the "
                                f"nearest and takes one.")
                        else:
                            print(f"   (target unreachable from {here} — "
                                  f"abandoning this area)")
                            break
                    else:
                        print(f"   (target unreachable from {here} — "
                              f"{len(ways)} untried exit(s) left, keeping on)")
                        trace.append(
                            f"PROVEN: what this goal needs is NOT in {here}. "
                            f"But {len(ways)} way(s) out of here have never "
                            f"been taken: {', '.join(ways)}. Take one — do "
                            f"not give up and do not re-search this area.")
            if not cur:
                # bridge hiccup lost the state: fall back to the subgoal start
                self.log("escalate_state_lost", subgoal=sg["id"], round=rnd)
                if can_reset:
                    self._send_safe("checkpoint_restore", token="esc")
                    progress = []
                feedback = ("The game state was lost and reset to the subgoal "
                            "start; author the full sequence again.")
                spent += 1
                continue
            if cur.get("mode") == "ui":
                cur = self._leave_ui(cur, sg) or cur
            else:
                self._ui_pending = 0
            stuck_note = ""      # per-round; the walk-back note appends below
            if self._faint_at and cur.get("mode") == "overworld":
                back = self._return_from_blackout(cur, sg)
                if back:
                    cur = self.settle() or cur
                    stuck_note += (f"\nYour party fainted and you were sent "
                                   f"back to a Pokemon Center. You have been "
                                   f"walked back to {back}, where you were. "
                                   f"You are HEALED, and whatever beat you "
                                   f"is still standing where it was.")
            sig1 = self._snapshot(cur)
            here_now = self._where(cur)
            self._stuck_in[here_now] = self._stuck_in.get(here_now, 0) + 1
            # did THIS round's own ops walk the party out of the target
            # map? (see the known-way block at the top of the round)
            _tmaps = set()
            _tk1 = self._target_key(sg)
            if _tk1.startswith("badge:"):
                _g1 = BADGE_GYMS.get(_tk1.split(":", 1)[1])
                if _g1:
                    _tmaps = {_g1, _g1.replace("_GYM", "_CITY")}
            elif _tk1.startswith(("map:", "area:")):
                _tmaps = {_tk1.split(":", 1)[1].split("|")[0]}
            _m0 = sig0[0]
            if (_m0 in _tmaps and sig1[0] and sig1[0] != _m0
                    and any(c.get("op") in ("cross", "use_warp")
                            for c in clean)):
                if not hasattr(self, "_left_target"):
                    self._left_target = set()
                self._left_target.add(_m0)
                self.log("left_target_on_purpose", subgoal=sg["id"],
                         round=rnd, left=_m0, now=sig1[0])
            # NB: do not reset stuck_note here — the blackout walk-back note
            # is appended above and a reset at this point deleted it before
            # it was ever sent, so the round after a wipe never learned it
            # had been walked home or that the thing that beat it is still
            # standing there.
            if self._blackouts.get(self._target_key(sg), 0) >= 2:
                # WHAT the wipes cost and whether anything changed between
                # them — never what to do about it. This note used to
                # conclude "you are TOO WEAK to win this fight as you are,
                # do not walk back in unchanged" and list remedies, which is
                # a strategy claim the harness is in no position to make: a
                # trainer you beat STAYS beaten, so re-entering a gauntlet
                # banks the ones you got before you fell. The run ground the
                # Nugget Bridge down over 13 wipes, L26 -> L28, while being
                # told every round that repeating was hopeless. The paired
                # levels below are the evidence that settles it either way
                # (wiped at L19, still L19 = nothing has changed; L26 -> L28
                # = the grind is working). Print them and stop talking.
                last_lv = self._blackout_lead.get(self._target_key(sg))
                now_lv = ((cur or {}).get("party") or [{}])[0].get("level")
                dated = (f" (last wipe: lead L{last_lv}; your lead now: "
                         f"L{now_lv})" if last_lv and now_lv else "")
                stuck_note += (
                    f"\nYour party has been WIPED OUT "
                    f"{self._blackouts[self._target_key(sg)]}x pursuing this "
                    f"goal{dated}. Each blackout also costs you half your "
                    f"money.")
                # WHAT IS IN THE BAG AND WHAT THE PARTY CAN ACTUALLY DO.
                # The wipe note reported the count and the levels and
                # nothing about the tools: Charmeleon lost to Misty ten
                # times swinging RAGE (20 power) with GROWL and LEER filling
                # two of its four slots, while TM_MEGA_PUNCH sat unused in
                # the bag the whole time. Inventory beside the problem —
                # what to do with it, if anything, is not stated here.
                _bag = (cur or {}).get("bag") or {}
                if _bag:
                    stuck_note += ("\nWHAT YOU ARE CARRYING: "
                                   + ", ".join(f"{k} x{v}"
                                               for k, v in sorted(_bag.items()))
                                   + ".")
                # AND WHAT IT IS WORTH. The bag reached the note and the
                # wallet never did, so "you have a NUGGET" sat next to no
                # number to compare it with. The run walked into the mart
                # holding a NUGGET, two coins short of the 100 the day care
                # wanted for its own CHARIZARD, and walked out again.
                _money = (cur or {}).get("money")
                if _money is not None:
                    stuck_note += f"\nMONEY: {_money}."
                _dc = (cur or {}).get("daycare") or {}
                if _dc.get("species"):
                    stuck_note += (
                        f"\nAT THE DAY CARE: your {_dc.get('species')} "
                        f"L{_dc.get('level')}, which costs {_dc.get('cost')} "
                        f"to collect.")
                _mv = []
                for _m in (cur or {}).get("party") or []:
                    _names = ", ".join(
                        str(x.get("id") if isinstance(x, dict) else x)
                        for x in (_m.get("moves") or []))
                    _mv.append(f"{_m.get('species')} L{_m.get('level')}"
                               f" knows {_names or 'nothing'}")
                if _mv:
                    stuck_note += "\nWHAT YOUR PARTY CAN DO: " + "; ".join(_mv) + "."
            # TRAINING A FAINTED POKEMON IS NOT TRAINING. It cannot be sent
            # out, so it earns nothing and the lead soaks every battle while
            # the condition never moves. The party screen says so; say it
            # here too, before the round is spent.
            # NOT ONLY AFTER A WIPE. This first sat inside the blackout
            # branch, so the one fact that unsticks a map-split city was
            # withheld from every subgoal that had not yet got itself
            # killed. Being stuck is the trigger; dying is not a
            # prerequisite for being told how the city is put together.
            stuck_note += self._passage_note(here_now)
            # distance to the objective, and how long since it improved
            _drift_note, _drift_done = self._goal_drift(sg, cur)
            stuck_note += _drift_note
            if _drift_done:
                stuck_note += (
                    "\nThis subgoal has spent a long stretch getting no "
                    "nearer and is being ended here so the plan can be "
                    "rewritten from what actually happened.")
                # exhaust the budget rather than breaking out: the loop's
                # own exit (while spent < rounds) runs the same cleanup a
                # natural exhaustion does, and this code does not take
                # kindly to new exits.
                spent = rounds
            want2 = ((sg.get("done_when") or {}).get("slot_level") or {}
                     ).get("slot")
            if want2:
                pty = (cur or {}).get("party") or []
                if len(pty) >= want2 and (pty[want2 - 1].get("hp") or 0) <= 0:
                    stuck_note += (
                        f"\nSLOT {want2} "
                        f"({pty[want2 - 1].get('species')}) IS FAINTED. A "
                        f"fainted Pokemon cannot be sent into battle and "
                        f"earns no experience, so this goal cannot move "
                        f"until it is healed at a Pokemon Center.")
            spent_here = self._tried_objs.get(here_now, set())
            here_objs = {o.get("name") for o in
                         ((cur.get("map") or {}).get("objects") or [])
                         if o.get("reachable")}
            if stuck_note:
                pass          # a party wipe outranks an exhausted room:
                              # "leave, it is not here" is the opposite of
                              # the truth when you simply keep losing
            elif here_objs and here_objs.issubset(spent_here):
                stuck_note = (
                    f"\nYou have now interacted with EVERYTHING reachable in "
                    f"this area and DONE_WHEN is still false. The trigger is "
                    f"NOT here. Leave through an exit you have not taken "
                    f"yet — some events fire by TRAVELLING (walking out "
                    f"along a road) rather than by entering a place or "
                    f"talking to anyone.")
            elif self._stuck_in.get(here_now, 0) >= 3:
                stuck_note = (
                    f"\n{self._stuck_in[here_now]} rounds in this same area "
                    f"have not moved DONE_WHEN. Whatever sets it may not be "
                    f"HERE. Events can be triggered by TRAVELLING (walking "
                    f"out along a road or path) rather than by entering a "
                    f"building or talking to someone. Consider leaving and "
                    f"taking an UNTRIED map edge or door.")
            loop_note = ""
            had_blackout = any("blackout" in t for t in trace)
            # A round in which EVERY op was refused executed nothing: the
            # model has been told "no" but has not yet had a turn to act on
            # it. Charging those rounds meant enter_oaks_lab burned 3 of its
            # 5 rounds on refusals and ran out before it reached the road
            # north, having only searched two buildings. Capped so a model
            # that proposes nothing but refused ops still terminates.
            # A ROUND WHERE NOTHING WORKED IS DEAD, whoever said no. This
            # was REFUSED-only — the harness turning an op down — so a round
            # in which every op RAN AND FAILED did not qualify, and that is
            # the commoner case by far. Watched live in the clean-room run:
            # Viridian City, every trace line "cross(dir=north): FAILED —
            # couldn't reach north edge gap" and "interact: FAILED — no
            # reachable tile adjacent", the old man lying across the road
            # north, and four untried doors on the ledger including the MART
            # that holds the Parcel which is the only thing that moves him.
            # The free round below already walks through an untried door; it
            # simply never fired, so the run bounced between Route 1 and the
            # city border while the answer was a building it had never
            # entered.
            #
            # This is the blind half of exploring and it is deliberately
            # blind: it does not know the mart matters, any more than a
            # player does the first time. It knows the room has a door
            # nobody has opened, and a round in which nothing worked is the
            # moment to open it.
            _dead = bool(trace) and all(("REFUSED" in t or "FAILED" in t)
                                        for t in trace)
            if _dead and free_rounds < 3:
                free_rounds += 1
                self.log("free_round", subgoal=sg["id"], round=rnd,
                         spent_free=free_rounds)
                # A refused-only round used to STAND STILL — watched live:
                # five refused norths in front of the Cerulean guard while
                # the ledger held an untried south edge leading to the
                # subgoal's own target map. The sweep precedent applies to
                # doors: with every proposal proven futile and untried
                # ways out of THIS region on the ledger, walking through
                # one is mechanics — the model steers again from the next
                # observation.
                # A FLAG target usually needs a PERSON, and people repeat
                # their offers when the world has changed — the captain
                # re-offers HM01 forever, but the lifetime touched ledger
                # certified his room "exhausted" and the stuck note walked
                # the run out of it. On a dead round, re-talk each
                # reachable person once per attempt before wandering off.
                retalked_now = False
                tgt_flag = self._target_key(sg).startswith("flag:")
                if tgt_flag and (cur or {}).get("mode") == "overworld":
                    npcs = [ob for ob in ((cur.get("map") or {})
                                          .get("objects") or [])
                            if ob.get("kind") in ("npc", "trainer")
                            and ob.get("reachable")
                            and ob.get("name") not in self._retalked]
                    if npcs:
                        nm = npcs[0].get("name")
                        self._retalked.add(nm)
                        self._send_safe("interact", name=nm, answer="yes")
                        o2 = self.settle()
                        while o2 and o2.get("mode") == "battle":
                            o2 = self.handle_battle(sg, o2)
                            o2 = self.settle()
                        self.log("free_round_retalk", subgoal=sg["id"],
                                 name=nm)
                        trace.append(
                            f"(free round: spoke to {nm} AGAIN — people "
                            f"repeat their offers once the world has "
                            f"changed, a freed bag slot included)")
                        retalked_now = True
                here_r = self._where(cur)
                untried = self._frontier_left(here_r)
                # ...and neither does the free round's exit walk (same
                # rule; the free round still re-talks people and sweeps,
                # neither of which moves the party).
                if (not USE_LEDGER and not retalked_now and untried
                        and (cur or {}).get("mode") == "overworld"):
                    # goal-ward edge first, same rule as the reroute rank:
                    # by DISTANCE over the printed map, so a first hop
                    # toward a far target beats a door that goes nowhere
                    # near it (alphabetical order buried Cerulean's 'east'
                    # behind every numeric door key on the map)
                    tgt_k = self._target_key(sg)
                    want_m = (tgt_k.split(":", 1)[1].split("|")[0]
                              if tgt_k.startswith(("map:", "area:"))
                              else BADGE_GYMS.get(tgt_k.split(":", 1)[1])
                              if tgt_k.startswith("badge:") else None)
                    want_m = _doorstep(want_m) if want_m else None
                    hmap = (cur.get("map") or {}).get("id")
                    redges = dict((self.atlas.get(hmap) or {})
                                  .get("edges") or {})
                    for d, m2 in (MAP_EDGES.get(hmap) or {}).items():
                        redges.setdefault(d, m2)
                    # A DOOR NOBODY HAS OPENED CANNOT BE SCORED, and the
                    # scorer below only ever ranked exits it could score —
                    # so the free round, whose whole purpose is to try
                    # something new, systematically elected ground it had
                    # already walked. In the Cerulean trashed house the two
                    # ways out were the front door (known: back to a city
                    # visited 11x, refused one line earlier for exactly
                    # that) and the hole in the back wall (never opened).
                    # It took the front door, because the last-resort
                    # tiebreak was alphabetical and "2,7" sorts before
                    # "3,0". Prefer the exit we know least about.
                    unopened = [e for e in sorted(untried)
                                if not redges.get(e)]
                    key, scored = None, []
                    if want_m:
                        blocked = self._impassable()
                        # THE EXIT'S OWN EDGE PAYS TOO. _goal_score rates
                        # the map an exit LEADS TO, and Saffron is zero hops
                        # from Saffron — so the shut gate scored 0, the best
                        # possible, as though the run were already through
                        # it. Pricing only the road BEYOND a door means a
                        # door that has never once opened outranks every
                        # road that has. Charge the step itself: shut, and
                        # by how hard it has already been leaned on.
                        # ONE CURRENCY, MEASURED FROM WHERE YOU STAND.
                        # _goal_score answers on three different scales — a
                        # bare hop count when the goal is reachable avoiding
                        # shut edges, 50+ for nearest-unvisited, 80+ for the
                        # tolled fallback — so adding an edge toll to it
                        # compared prices in different units. Saffron scored
                        # 2 ("once through the gate it is a two-hop stroll")
                        # + 44 for the gate = 46, while the genuinely open
                        # eastern road came back as 80 + 18 = 98. Price the
                        # WHOLE journey through this exit instead, tolls and
                        # all, and the numbers mean the same thing.
                        vis_e = self._map_visits()
                        toll = {b: 4 + min(vis_e.get(b[0], 0) // 8, 40)
                                for b in blocked}
                        walked = self._walked_map_links()

                        def _via(dest):
                            on = static_cost(dest, want_m, toll, walked)
                            if on is None:
                                return 999
                            return 1 + toll.get((hmap, dest), 0) + on
                        scored = sorted((_via(redges[e]), e)
                                        for e in sorted(untried)
                                        if redges.get(e))
                        # A known exit still wins outright when it IS the
                        # door to the target AND that door has ever opened;
                        # short of that, an unopened door beats another lap
                        # through walked ground.
                        if scored and (scored[0][0] == 0 or not unopened):
                            key = scored[0][1]
                            self.log("free_round_goalward", subgoal=sg["id"],
                                     via=key, score=scored[0][0],
                                     toward=want_m,
                                     blocked=sorted(blocked)[:4])
                    if key is None and unopened:
                        key = unopened[0]
                        self.log("free_round_unopened", subgoal=sg["id"],
                                 via=key, untried=len(untried))
                    if key is None:
                        key = scored[0][1] if scored else sorted(untried)[0]
                    pre = cur
                    if _is_door_key(key):
                        x, y = key.split(",")
                        self._send_safe("use_warp", x=int(x), y=int(y))
                        step = {"x": int(x), "y": int(y)}
                    else:
                        self._send_safe("cross", dir=key)
                        step = {"dir": key}
                    o2 = self.settle()
                    while o2 and o2.get("mode") == "battle":
                        o2 = self.handle_battle(sg, o2)
                        o2 = self.settle()
                    # RECORD IT EVEN WHEN IT MOVED NOTHING. This guarded on
                    # a map CHANGE, so a door that refuses you was never
                    # written down — and "prefer the exit nobody has opened"
                    # then elected the same shut gate for ever, because a
                    # gate you cannot pass is a door that stays unopened by
                    # definition. It also meant the goal-ward pricing never
                    # ran: unopened doors short-circuit it, and there was
                    # always one. note_transition handles the went-nowhere
                    # case itself now; just let it see the attempt.
                    if o2:
                        self.note_transition(
                            pre, step, o2,
                            reason=str(((o2 or {}).get("result") or {})
                                       .get("detail") or ""))
                    self.log("free_round_exit", subgoal=sg["id"],
                             via=key, to=self._where(o2))
                    trace.append(
                        f"(nothing in that round worked, so the free round "
                        f"took an untried way out of the area: {key} led "
                        f"to {self._where(o2)})")
            elif (sig1[0], sig1[4], sig1[5]) == (sig0[0], sig0[4], sig0[5]):
                spent += 1   # round went nowhere (same map/party/flags)
            elif had_blackout or pardon:
                # a blackout's map-jump wasn't chosen, and the NEXT round's
                # walk back to where the party fainted isn't circling either
                pardon = had_blackout
            elif sig1[0] and sig1[0] != sig0[0]:
                # revisit penalty only on an actual TRANSITION to a seen map:
                # staying put while making progress (grinding levels on one
                # map) is not circling (brock23 spent its whole budget on
                # level-up rounds counted as "revisits")
                visits[sig1[0]] = visits.get(sig1[0], 0) + 1
                if visits[sig1[0]] >= 2:
                    spent += 1   # back on a map already visited: circling
                    mover = next((s for s in reversed(clean)
                                  if s.get("op") in ("cross", "use_warp")),
                                 None)
                    if mover:
                        desc = (mover["op"] + "("
                                + ",".join(f"{k}={v}" for k, v in
                                           mover.items() if k != "op")
                                + f") -> {sig1[0]}")
                        if desc not in backward:
                            backward.append(desc)
                    # COUNT, DO NOT COMMAND (the ledger prints "taken Nx"
                    # on the very exit; "do not re-enter maps you just
                    # left" is a strategy claim). Under the ledger the
                    # count is the whole note.
                    loop_note = (
                        f"\nThis is visit #{visits[sig1[0]]} to {sig1[0]} "
                        f"during this subgoal."
                        if USE_LEDGER else
                        f"\nWARNING: you are going in CIRCLES — this is visit "
                        f"#{visits[sig1[0]]} to {sig1[0]} during this subgoal. "
                        f"Use the ATLAS to pick the direction that leads "
                        f"toward DONE_WHEN; do not re-enter maps you just "
                        f"left.")
            # accumulate targets that failed or did nothing, so the model is
            # told NOT to repeat them (it looped on the pokedex before).
            for t in trace:
                if ("FAILED" in t or "NO visible effect" in t) and ":" in t:
                    tgt = t.split(":", 1)[0]
                    if tgt not in inert:
                        inert.append(tgt)
            objs = [f"{o.get('kind')}:{o.get('name')}({o.get('x')},{o.get('y')})"
                    + ("" if o.get("reachable") else " [CANNOT REACH from "
                       "this area — a wall or ledge is in the way]")
                    for o in (cur.get("map") or {}).get("objects", [])]
            conns = (cur.get("map") or {}).get("connections") or {}
            open_prompt = ""
            if cur.get("mode") == "ui" and cur.get("recent_text"):
                open_prompt = (
                    f"\nA CHOICE PROMPT is still OPEN and your macro did not "
                    f"answer it (prompt: {cur.get('recent_text')!r}). Add a "
                    f"menu op to answer it (1=YES/first, 2=NO/second) — e.g. "
                    f"to accept, follow the interact with {{\"op\":\"menu\","
                    f"\"index\":1}}.")
            # Nothing new reachable from here? Walk back to somewhere that
            # still has unopened exits, rather than burning rounds re-reading
            # a finished room.
            # After several rounds, a LOCAL untried exit stops being a
            # reason to stay: 1F kept one door unopened (25,15, which only
            # rejoins ground already walked) and that alone held the escort
            # back while the run shuttled between two known warps. Same
            # first-refusal rule as the object veto — local options get
            # their turn, then navigation resumes.
            # Patience counted PER ESCALATION never matured: a backtrack
            # re-opens the subgoal with rnd back at 1, so a run that spent
            # thirty rounds shuttling between two rooms never once reached
            # the threshold. Count rounds spent on this TARGET in this
            # REGION, across escalations — the same law that fixed the
            # revisit counter, the op ledger and the searched ledger.
            hk = f"{self._cur_target}|{self._where(cur)}"
            self._rounds_here[hk] = self._rounds_here.get(hk, 0) + 1
            patient = self._rounds_here[hk] >= 3
            # NEVER overrule a move the model actually made. With patience
            # alone the escort hauled the party back to the frontier every
            # round while the model was deliberately walking to Pewter for
            # its shopping goal — the harness deciding, not facilitating.
            # Escort only when the round left the party where it started:
            # that is being stuck, and being stuck is what it is for.
            # CLEAR THE ROOM BEFORE LEAVING IT. When a room has gone
            # unproductive the useful move is the dull one: press A on
            # everything reachable that has not been touched. Listing them
            # was not enough — rooms sat half-worked for whole attempts, so
            # they never qualified as searched and the run kept coming back
            # to reconsider them. Sweeping is cheap, cannot lose progress,
            # and either finds the thing or proves the room empty.
            # No patience gate on the SWEEP. Pressing A on things is cheap
            # and cannot lose progress, so it should happen the first time
            # a round achieves nothing — waiting for three rounds in one
            # region meant it almost never qualified, because the run
            # changes rooms between rounds. The ESCORT still waits: moving
            # the party is disruptive, sweeping is not.
            # THIS round's clean ops, not the run's. `progress` accumulates
            # across rounds, so gating on it meant the sweep could only ever
            # fire before the subgoal's first successful op — which is
            # almost never — and it never ran at all.
            if not clean:
                here_s = self._where(cur)
                touched = self._tried_objs.setdefault(here_s, set())
                loose = [o.get("name") for o in
                         ((cur.get("map") or {}).get("objects") or [])
                         if o.get("reachable") and o.get("name")
                         and o.get("name") not in touched]
                # A FLAG hunt re-asks the PEOPLE. `touched` is a lifetime
                # ledger, so the captain read as spent and the run stood
                # in his cabin and walked out — but people repeat their
                # offers when the world changes (the freed bag slot), so
                # for a flag target every reachable person joins the
                # sweep once per attempt.
                if self._target_key(sg).startswith("flag:"):
                    loose += [o.get("name") for o in
                              ((cur.get("map") or {}).get("objects") or [])
                              if o.get("kind") in ("npc", "trainer")
                              and o.get("reachable") and o.get("name")
                              and o.get("name") in touched
                              and o.get("name") not in self._retalked
                              and not self._retalked.add(o.get("name"))]
                # A BUSH IS NOT PRESSED, IT IS CUT. The sweep pressed A on
                # CUT_TREE and nothing happened — with CUT known for hours
                # and the harness itself naming the tree as the untouched
                # thing in the room, Cerulean's east bush (the road to Rock
                # Tunnel and everything beyond) stayed standing. Clearing a
                # named obstacle with a move the party already knows is
                # execution, not judgment.
                kinds = {o.get("name"): o.get("kind")
                         for o in ((cur.get("map") or {}).get("objects") or [])}
                coords = {o.get("name"): (o.get("x"), o.get("y"))
                          for o in ((cur.get("map") or {}).get("objects") or [])}
                knows_cut = any(
                    "CUT" in [str(mv.get("id") if isinstance(mv, dict) else mv)
                              for mv in (mon.get("moves") or [])]
                    for mon in (cur.get("party") or []))
                if knows_cut:
                    loose += [o.get("name") for o in
                              ((cur.get("map") or {}).get("objects") or [])
                              if o.get("kind") == "cut_tree"
                              and o.get("reachable")
                              and o.get("name") not in loose]
                if loose:
                    self.log("room_sweep", subgoal=sg["id"], region=here_s,
                             objects=loose[:8])
                    asked_back = []
                    for name in loose[:8]:
                        if kinds.get(name) == "cut_tree" and knows_cut:
                            x, y = coords.get(name, (None, None))
                            o2 = self._send_safe("field_move", move="CUT",
                                                 x=x, y=y)
                            self.log("sweep_cut", subgoal=sg["id"],
                                     at=f"{x},{y}")
                        else:
                            o2 = self._send_safe("interact", name=name)
                        if o2 and o2.get("mode") == "battle":
                            o2 = self.handle_battle(sg, o2)
                            o2 = self.settle()
                        # A DECLINED OFFER IS NOT AN EXHAUSTED THING. The
                        # sweep sends `interact` with NO answer, and the op's
                        # own contract is that a question with no answer
                        # given is DECLINED — so it walked up to the Mt Moon
                        # fossils, was asked "You want the DOME FOSSIL?",
                        # said no, and marked BOTH touched. The lifetime
                        # ledger then retired them, the room read as fully
                        # worked, and the run left the mountain with no
                        # fossil and no way to notice. Widening the free
                        # round this afternoon made it happen more often.
                        # It is NOT fixed by answering yes: the sweep is
                        # blind, and yes to the Magikarp salesman costs 500.
                        # Declining stays the safe default; what changes is
                        # that a thing which asked something is not recorded
                        # as spent, and the model is told it is still open.
                        if not self._record_touch(here_s, name, o2):
                            _det = str(((o2 or {}).get("result") or {})
                                       .get("detail") or "")
                            if ASKING in _det:
                                asked_back.append(name)
                        cur = o2 or cur
                        if pred_holds(done, cur):
                            break
                    trace.append(
                        f"(swept this area: pressed A on "
                        f"{', '.join(loose[:8])} — everything reachable "
                        f"here has now been tried)")
                    if asked_back:
                        trace.append(
                            f"({', '.join(asked_back)} ASKED something and "
                            f"the sweep could only decline — it presses "
                            f"blind and cannot answer for you. They are NOT "
                            f"recorded as done. To accept, press one "
                            f"yourself with an answer: "
                            f'{{"op":"interact","name":"{asked_back[0]}",'
                            f'"answer":"yes"}})')
                    if pred_holds(done, self.settle() or cur):
                        self.log("escalate_success", subgoal=sg["id"],
                                 round=rnd, proposed=0,
                                 distilled=len(progress), verified=False)
                        return True, progress
            # MOTION IS NOT PROGRESS. This asked only whether the round did
            # ANYTHING, and crossing a route boundary always works — so a
            # run bouncing ROUTE_11 <-> ROUTE_12 chasing a sealed Saffron
            # counted every lap as progress and the walk-back to unexplored
            # ground was never even considered, with 38 regions still
            # holding untried exits. Rounds that move the party without
            # moving the CONDITION are the definition of stuck; after a few
            # of them, go somewhere new instead.
            # ...BUT REACHING SOMEWHERE NEW IS PROGRESS. Counting only
            # done_when made every ladder in a dungeon an idle lap — three
            # floors in and the walk-back dragged the run out of the cave
            # it was crossing. A room it has never stood in is exactly what
            # exploring means, whether or not the goal came any closer.
            moved_itself = bool(progress)
            _here_now = self._where(cur)
            _fresh_ground = _here_now not in getattr(self, "_seen_this_sg", ())
            if not hasattr(self, "_seen_this_sg"):
                self._seen_this_sg = set()
            self._seen_this_sg.add(_here_now)
            if moved_itself and not pred_holds(done, cur) and not _fresh_ground:
                self._idle_rounds = getattr(self, "_idle_rounds", 0) + 1
                if self._idle_rounds >= 3:
                    moved_itself = False
            else:
                self._idle_rounds = 0
            # THE STALE BUDGET. Six rounds in a row that changed nothing
            # the run CARRIES (badges, flags, bag kinds), KNOWS (no ground
            # new to this subgoal) or IS (party species/levels, money) is
            # a subgoal spending inference on an idea, not on the world —
            # the mart leg ran 78 rounds of it. End it here and hand the
            # loop to the rewrite, which now sees the repetition counted
            # (author.tried_text). This decides nothing about the game:
            # it is the same "long stretch getting no nearer" rule
            # _goal_drift applies to travel, made to work where distance
            # is undefined (a flag, an item, a person).
            # WHAT IT MUST NEVER CUT: a fight being lost and come back to
            # (contested), a room with re-pressable switches (Surge's cans
            # re-randomise on a miss — the room IS the puzzle and pressing
            # again is the only way through; a PC is a service, not a
            # switch), a training goal (levels ARE the change), a round
            # that fainted, or one that ended off the overworld.
            _fp = (tuple(self._world_mark(cur)),
                   tuple((m.get("species"), m.get("level"))
                         for m in (cur.get("party") or [])),
                   cur.get("money"))
            _switches = any(
                o.get("kind") == "fixture" and o.get("reachable")
                and str(o.get("name") or "") != "PC"
                for o in ((cur.get("map") or {}).get("objects") or []))
            _exempt = (STALE_CUTOFF <= 0
                       or self._is_party_goal(self._cur_target or "")
                       or bool(self.contested.get(self._cur_target, {})
                               .get(_here_now))
                       or _switches or had_blackout
                       or cur.get("mode") != "overworld")
            # An exempt round is NOT COUNTED — neither for nor against.
            # Resetting on it let a round that ended in the shop menu (mode
            # ui) wipe five stale rounds of pacing between the mart and the
            # street, and the mart leg was pacing exactly that. Only new
            # ground or a changed fingerprint says the run got somewhere.
            _moved_world = bool(_fresh_ground or _fp != self._stale_fp)
            if _moved_world:
                self._stale_rounds = 0
            elif not _exempt:
                self._stale_rounds += 1
            self._stale_fp = _fp
            # WRITE THE VERDICT ON THE PLAN. The plan echo quoted past plans
            # in the model's own words and nothing else, so "engage the
            # ghost in battle" read back as a plan, not as a plan that had
            # already changed nothing four times — and it was re-adopted
            # "based on previous attempts". Each plan now carries what came
            # of it: new ground / something changed / NOTHING CHANGED.
            _verdict = ("new ground" if _fresh_ground else
                        "something changed" if _moved_world else
                        "NOTHING CHANGED")
            if self._plans_said and len(self._plans_said[-1]) == 3 \
                    and self._plans_said[-1][0] == rnd:
                _r0, _w0, _p0 = self._plans_said[-1]
                self._plans_said[-1] = (_r0, _w0, _p0, _verdict)
                _ph = self._plan_hist.get(self._cur_target or "?") or []
                if _ph and _ph[-1][0] == rnd and len(_ph[-1]) == 3:
                    _ph[-1] = [_r0, _w0, _p0, _verdict]
            # THE CLOCK, IN VIEW. A step about to be ended for staleness
            # should say so while there is still a round to spend on the
            # untried list instead — a fact about the harness's own budget,
            # not the game. What is untried is in the ledger; explore takes
            # the next one; which is the model's.
            if 0 < self._stale_rounds < STALE_CUTOFF:
                stuck_note += (
                    f"\nSTALE {self._stale_rounds} of {STALE_CUTOFF}: that "
                    f"many rounds in a row have changed nothing you carry, "
                    f"know or are, on ground already walked for this step. "
                    f"At {STALE_CUTOFF} this step is ended and the plan "
                    f"rewritten. THE RULE OF THE SEARCH: a thing that "
                    f"changed nothing last time changes nothing this time "
                    f"unless YOU have changed since — something carried, "
                    f"known or beaten that you were not before. If nothing "
                    f"about you has changed, the same door, person or "
                    f"fight again is the same result again; only NEW "
                    f"ground can produce something new. Everything still "
                    f"untried is in the ledger above and in WAYS THAT "
                    f"TURNED YOU BACK / places with ways never taken; "
                    f"{{\"op\":\"explore\"}} takes the nearest untried one "
                    f"for you, and {{\"op\":\"go\"}} walks you to a place you "
                    f"know. If this step's condition can no longer come "
                    f"true, or you already hold what it was for, "
                    f"{{\"op\":\"skip\"}} moves the plan on to its next step.")
            if self._stale_rounds >= STALE_CUTOFF and spent < rounds:
                self.log("stale_cutoff", subgoal=sg["id"], round=rnd,
                         stale=self._stale_rounds, at=_here_now)
                stuck_note += (
                    f"\n{self._stale_rounds} rounds in a row changed "
                    f"nothing you carry, know or are, on ground you had "
                    f"already walked for this subgoal. It is being ended "
                    f"here so the plan can be rewritten from what happened.")
                spent = rounds
            # THE ESCORT DOES NOT SELF-FIRE UNDER THE LEDGER. Watched live
            # on the mart leg: the model entered the mart to talk to the
            # clerk three rounds running and the escort hauled it back to
            # the street after each — the harness undoing a move the model
            # made, every round. The frontier walk is {"op":"explore"} now,
            # offered as entry 1 whenever the area is worked; taking it is
            # the model's. (The legacy renderer keeps the escort.)
            if (not USE_LEDGER and not moved_itself
                    and (patient or not self._untried_exits(cur))):
                went = self._route_to_frontier(cur, sg, patient=patient)
                if went:
                    cur = self.settle() or cur
                    stuck_note += (
                        f"\nYou were walked back to {went} because it still "
                        f"has exits you have NEVER taken, and where you were "
                        f"had none. Take one of them now.")
            feedback = ("Per-step results of your last macro:\n"
                        + "\n".join(f"  {i + 1}. {t}"
                                    for i, t in enumerate(trace))
                        + f"\nAfter it, DONE_WHEN was NOT met. You are STILL "
                        f"at that end state (no reset): map="
                        f"{(cur.get('map') or {}).get('id')}, mode="
                        f"{cur.get('mode')}, party size="
                        f"{len(cur.get('party') or [])}. Your next macro "
                        f"CONTINUES from here — author only the REMAINING "
                        f"steps, do not repeat ones that already took effect."
                        + loop_note + stuck_note
                        + open_prompt
                        # ONE LEDGER PER PROMPT. This re-rendered the whole
                        # exploration text from the round-end state inside
                        # the feedback, one settle away from the fresh
                        # render at the top of the next round — the same
                        # block twice, and two escalate_context records per
                        # round. Under the ledger only the events-fired
                        # note rides here; the legacy renderer keeps both.
                        + (self._fired_text(cur, sg) if USE_LEDGER
                           else self._logged_exploration(cur, sg))
                        # ...and under the ledger, nothing below: the
                        # reachable / unreachable warps, the edges, the
                        # object list, the inert and backward lists are all
                        # entries in the block at the top of the prompt,
                        # with their history. Feedback is the trace and
                        # what changed (EXPLORE_DESIGN §2 item 6).
                        + ("" if USE_LEDGER else
                           (("\nWarps you can currently WALK TO from here: "
                            + ", ".join(
                                f"({w.get('x')},{w.get('y')})->{w.get('dest')}"
                                for w in ((cur.get("map") or {}).get("warps")
                                          or []) if w.get("reachable"))
                            + ". Warps NOT reachable from here: "
                            + (", ".join(
                                f"({w.get('x')},{w.get('y')})->{w.get('dest')}"
                                for w in ((cur.get("map") or {}).get("warps")
                                          or []) if not w.get("reachable"))
                               or "none")
                            + ". If the way onward is blocked, LEAVE through a "
                              "reachable warp and come back another way."
                            + self._through_buildings(cur))
                           if (cur.get("map") or {}).get("warps") else "")
                        + (f"\nEdges from this map (cross that dir to reach): "
                           + ", ".join(
                               f"{d}->"
                               + (self._walked_dest(
                                   (cur.get("map") or {}).get("id"), d)
                                  or "UNKNOWN")
                               + (" (PROVEN uncrossable from THIS part of "
                                  "the map — the connection exists on the "
                                  "far side of a barrier)"
                                  if d in self._sealed(self._where(cur))
                                  else "")
                               for d in conns)
                           if conns else "")
                        + (f"\nObjects here you can interact: {objs}" if objs
                           else "")
                        + (f"\nThese targets did NOTHING — do NOT repeat them, "
                           f"pick a DIFFERENT one: {inert}" if inert else "")
                        + (f"\nThese ops moved you BACKWARD to already-"
                           f"visited maps — never use them again this "
                           f"subgoal: {backward}" if backward else "")))
            self.log("escalate_note", subgoal=sg["id"], round=rnd,
                     stuck=stuck_note[:400], loop=loop_note[:200])
            self.log("escalate_feedback", subgoal=sg["id"], round=rnd,
                     spent=spent, trace=trace, inert=inert,
                     # where the round STARTED and where it ended: a cross
                     # that reports "seam unreachable" is a claim about the
                     # tile under the player, and the escalation path logs
                     # no per-step position at all
                     at=self._where(cur),
                     progress_ops=len(progress))
        self.log("escalate_end", subgoal=sg["id"], success=False)
        return False, sg.get("macro", [])

    def distill(self, sg: dict, ops: list) -> bool:
        """Write the escalation's successful op sequence back as the macro,
        with provenance (the claim needs to show the model authored it).

        AN EMPTY SEQUENCE IS NOT A ROUTE. Escalation can succeed having
        proposed nothing: the harness's own pathfinder walks a route
        (proposed=0, walked=1), a trainer engages on the way and the fight
        settles the condition, or the condition was already true by the
        time the ops resolved. All real successes — but none of them is a
        sequence that reproduces the state from anywhere else, and this
        method PERSISTS what it is given to the plan file.

        Storing [] therefore did two bad things at once. It deleted
        whatever macro was there (add and update, never delete), and it
        wrote a macro that must fail every future replay, since replaying
        no ops changes nothing and the done-check then decides. The record
        run logged eight of these in one chain, one of them for
        go_to_elevator, which then "finished in the wrong place" and sent
        the plan backtracking.

        The subgoal is still satisfied and the caller still proceeds; what
        is refused is the claim that a route was learned.
        """
        if not ops:
            self.log("distill_refused_empty", subgoal=sg["id"],
                     kept_macro=len(sg.get("macro") or []))
            return False
        sg["macro"] = ops
        # WHO WROTE THE SUBGOAL and WHO AUTHORED ITS MACRO are different
        # facts, and distillation used to collapse them: writing a macro
        # overwrote a hand-seeded subgoal's marker with the model's name, so
        # the plan file OVERSTATED model authorship (found 2026-08-12 while
        # auditing). Subgoal provenance is written once, at creation.
        sg.setdefault("subgoal_provenance",
                      {"authored_by": "unknown (pre-audit)"})
        sg["macro_provenance"] = {"authored_by": self.model, "run": self.run_id,
                                  "via": "escalation", "n_ops": len(ops)}
        if self.plan_path:
            # tmp+rename, same reason as the ledger: this is the file the
            # next attempt REPLAYS from, and a truncated one is a plan the
            # chain cannot parse at all — every leg written into it lost,
            # not just the macro being added.
            _tmp = self.plan_path.with_suffix(".json.tmp")
            _tmp.write_text(json.dumps(self.plan, indent=2))
            _tmp.replace(self.plan_path)
        self.log("distilled", subgoal=sg["id"], n_ops=len(ops))
        return True

    def run_subgoal(self, sg: dict) -> bool:
        done = sg.get("done_when")
        for attempt in range(1, sg.get("max_attempts", 3) + 1):
            obs = self.settle()
            if obs and obs.get("mode") == "battle":
                obs = self.handle_battle(sg, obs)
                obs = self.settle()
            if pred_holds(done, obs):
                self.log("subgoal_done", subgoal=sg["id"], attempt=attempt,
                         via="pre-check")
                return True
            self.log("subgoal_attempt", subgoal=sg["id"], attempt=attempt)
            self.status(subgoal=sg["id"], goal_text=sg.get("goal_text"),
                        done_when=sg.get("done_when"), obs=obs,
                        phase=f"replay attempt {attempt}", doing="macro")
            # A QUESTION ON SCREEN STOPS THE MACRO, on the replay path too.
            # The guard existed only in _run_traced, so escalation knew to
            # stop at an open box and REPLAY did not — and 422 macro steps
            # across plans/*.json have an op following an `interact`. At the
            # Mt Moon fossils that shape pressed the DOME FOSSIL, got "You
            # want the DOME FOSSIL?", and pressed the HELIX FOSSIL into the
            # open question; nothing ever answered either. Answering is not
            # ours to do — an `interact` that means to say yes carries
            # `answer` — so a macro that walked into an unanswered question
            # is a macro that is wrong, and it fails here and escalates,
            # where the words go to the model.
            asked = False
            for step in sg.get("macro", []):
                step = dict(step)
                when = step.pop("when", None)
                op = step.pop("op")
                obs = self.settle()
                if obs and obs.get("mode") == "battle":
                    obs = self.handle_battle(sg, obs)
                    obs = self.settle()
                if pred_holds(done, obs):
                    self.log("subgoal_done", subgoal=sg["id"],
                             attempt=attempt, via="mid-macro")
                    return True
                if when and not pred_holds(when, obs):
                    self.log("step_skipped", subgoal=sg["id"], op=op,
                             when=when, mode=obs.get("mode") if obs else None)
                    continue
                # Traversal steps (cross/walk_to) get cut short by wild
                # battles in grass — fight the battle, then RE-RUN the step so
                # the traversal resumes instead of burning a whole attempt.
                traversal = op in ("cross", "walk_to", "use_warp", "grind")
                for _ in range(12):
                    pre_obs = obs
                    try:
                        obs = self.b.send(op, **step)
                    except TimeoutError as e:
                        self.log("step_timeout", subgoal=sg["id"], op=op,
                                 err=str(e))
                        obs = self.b.obs()
                        break
                    r = (obs or {}).get("result") or {}
                    # the seam is unwalkable FROM HERE; the ledger may know
                    # a part of this map it IS walkable from
                    if (op == "cross" and not r.get("ok")
                            and "cannot be walked to" in str(r.get("detail"))):
                        _re_obs = self._cross_by_recall(obs, sg,
                                                        step.get("dir"))
                        if _re_obs is None:
                            _re_obs = self._uncork_seam(obs, sg,
                                                        step.get("dir"))
                        if _re_obs is not None:
                            obs = _re_obs
                            r = (obs or {}).get("result") or {}
                    self.log("step", subgoal=sg["id"], op=op, params=step,
                             ok=r.get("ok"), detail=r.get("detail"),
                             map=(obs.get("map") or {}).get("id")
                             if obs else None,
                             # WHERE it stood, not just which map: a cross
                             # that fails "seam unreachable" is a claim
                             # about the TILE, and pinning down whether the
                             # party was on the east or west half of Route 4
                             # cannot be done from the map id alone
                             # x/y live under obs["player"]; read off the
                             # top level this logged "None,None" from the
                             # day it was added — and it was added to pin
                             # down the TILE a cross failed from, which is
                             # the one thing it never once recorded.
                             at=(f"{((obs or {}).get('player') or {}).get('x')},"
                                 f"{((obs or {}).get('player') or {}).get('y')}"
                                 f" {((obs or {}).get('map') or {}).get('region')}")
                             if obs else None,
                             mode=obs.get("mode") if obs else None)
                    if obs and obs.get("mode") == "battle":
                        obs = self.handle_battle(sg, obs)
                        obs = self.settle()
                        if traversal and not pred_holds(done, obs):
                            continue     # battle interrupted travel: resume
                    # A wipe during REPLAY was invisible: both blackout
                    # detectors live in the escalation loop, so a macro
                    # party that died in Mt Moon woke at a Center with no
                    # faint marker and no walk-back, and the map trail read
                    # as silent teleports to Pewter, over and over. Same
                    # state test as escalation: an unasked-for jump to a
                    # respawn map with the party's HP suddenly RISEN.
                    pre_map = ((pre_obs or {}).get("map") or {}).get("id")
                    post_map = ((obs or {}).get("map") or {}).get("id")
                    if (pre_map and post_map and post_map != pre_map
                            and (post_map.endswith("POKECENTER")
                                 or post_map in ("REDS_HOUSE_1F",
                                                 "PALLET_TOWN"))):
                        mons = (obs or {}).get("party") or []
                        tot = lambda o: sum((m.get("hp") or 0) for m in
                                            (o or {}).get("party") or [])
                        healed = bool(mons) and all(
                            m.get("max_hp") and m.get("hp") == m["max_hp"]
                            for m in mons)
                        if healed and tot(obs) > tot(pre_obs):
                            self._faint_at = self._where(pre_obs)
                            tk0 = self._target_key(sg)
                            self._blackouts[tk0] = \
                                self._blackouts.get(tk0, 0) + 1
                            self._blackout_lead[tk0] = \
                                (mons or [{}])[0].get("level")
                            self._save_memory()
                            self.log("blackout", subgoal=sg["id"], op=op,
                                     respawn=post_map, detected="macro")
                            self.log("faint_marked", subgoal=sg["id"],
                                     at=self._faint_at)
                            self.log("subgoal_failed", subgoal=sg["id"])
                            return False
                    # RECORD WHAT THE MACRO WALKED. Only escalation ops were
                    # recording edges, so every map change made by a stored
                    # macro was invisible to the graph: the party descended
                    # 1F->B1F->B2F on a replayed macro, fainted, and the
                    # walk-back found no route to a floor it had just walked
                    # A door is a door whoever opened it.
                    if (r.get("ok") and pre_obs
                            and (pre_obs.get("map") or {}).get("id")
                            != ((obs or {}).get("map") or {}).get("id")):
                        self.note_transition(pre_obs, dict(step, op=op), obs)
                    if ASKING in str(r.get("detail") or ""):
                        self.log("macro_stopped_on_question",
                                 subgoal=sg["id"], op=op,
                                 detail=r.get("detail"))
                        asked = True
                    break
                if asked:
                    break
            if pred_holds(done, self.settle()):
                self.log("subgoal_done", subgoal=sg["id"], attempt=attempt,
                         via="post-macro")
                return True
        self.log("subgoal_failed", subgoal=sg["id"])
        return False

    def _checkpoint(self, sg):
        """Write the save the moment a subgoal is finished.

        WHY NOT JUST AT THE END OF AN ATTEMPT. That is where both existing
        saves are, and an attempt is long: many subgoals, each with up to a
        dozen escalation rounds. Everything earned since the last one is at
        risk from anything that ends the process early — and this run met
        three such things in a day. The GPU dropped off the bus. A leg was
        stopped to land a fix, nine times. Run 11 launched seven attempts
        and wrote three saves, and one of the four it lost was carrying the
        Pokedex and the delivered parcel, so the next attempt re-did an
        errand it had already done.
        A stop handler was the obvious answer and it is not enough on its
        own: an escalation spends most of its wall clock inside a model
        call, a Python signal handler cannot run until that returns, and a
        stop issued mid-round waited 90s and still had to be SIGKILLed.
        Bounding the loss to ONE SUBGOAL needs no signal to arrive on time.
        Cheap for what it buys: a save is a couple of seconds against a
        subgoal that takes minutes, and gen1 levels, items and flags only
        ever go up, so persisting mid-leg cannot lose progress.
        """
        if not getattr(self, "save_each", False):
            return
        r = (self._send_safe("save_game") or {}).get("result") or {}
        self.log("checkpoint", subgoal=sg.get("id"), ok=bool(r.get("ok")))

    def _attempt(self, sg) -> bool:
        """Replay the macro; escalate if that fails. Saves on success."""
        won = self._attempt_inner(sg)
        if won:
            self._checkpoint(sg)
        return won

    def _attempt_inner(self, sg) -> bool:
        """Replay the macro; escalate if that fails."""
        try:
            ok = self.run_subgoal(sg) if sg.get("macro") else False
        except TimeoutError as e:
            self.log("subgoal_timeout", subgoal=sg["id"], err=str(e))
            ok = False
        self._report_malformed(sg)
        if not ok and self.can_escalate:
            print(f"   -> escalating {sg['id']} to the model")
            self.escalations += 1
            try:
                success, ops = self.escalate(sg)
            except TimeoutError as e:
                self.log("escalate_timeout", subgoal=sg["id"], err=str(e))
                success, ops = False, []
            if success:
                ok = True
                if getattr(self, "_skipped", None) == sg.get("id"):
                    self._skipped = None
                    print(f"   {sg['id']} skipped by the model — not "
                          f"distilled, not done; the plan moves on")
                elif self.distill(sg, ops):
                    print(f"   distilled {sg['id']} ({len(ops)} ops)")
                else:
                    # say which it was: "0 ops" read as a distilled route
                    # of length zero, which is the one thing it never is
                    print(f"   {sg['id']} came true with no reproducible "
                          f"ops — macro left as it was")
        self._report_malformed(sg)
        return ok

    def _report_malformed(self, sg):
        """Say it out loud ONCE per malformation. pred_holds no longer dies
        on a value it cannot read, which is right for an unattended run —
        but a condition that can never come true now stalls a leg silently
        instead, and a silent stall with no name is the worst thing in this
        codebase to find. This is the name."""
        for k, why in list(PRED_MALFORMED.items()):
            if k in self._pred_said:
                continue
            self._pred_said.add(k)
            self.log("predicate_malformed", subgoal=sg.get("id"),
                     pred=k, why=why)
            print(f"   [predicate] {sg.get('id')}: {k} — {why}; "
                  f"this condition cannot be met as written")

    def run_plan(self, plan: dict) -> bool:
        self.log("plan_start", goal=plan.get("goal"), escalate=self.can_escalate)
        fails = 0
        backtracks = 0
        subgoals = plan["subgoals"]
        # WHAT REPLACED THE STICKY-WAYPOINT LEDGER. There used to be a
        # `_plan_done` map of "subgoal ids completed under this goal in an
        # earlier attempt", written on every success and carried across
        # processes — and NOTHING EVER READ IT. The resume below superseded
        # it deliberately, for the reason stated in the next paragraph, and
        # the ledger was left behind still being written, still being saved,
        # with a comment above it describing behaviour the file does not
        # have. A field that lies about what the code does is worse than no
        # field, so it is gone; this is the note it leaves.
        # RESUME FROM WHERE THE PARTY STANDS, not from the union of
        # everything ever done: the union version skipped the navigation
        # scaffold (those waypoints WERE walked once) and stranded a bare
        # flag target in Cerulean while its giver waited on the ship. The
        # furthest subgoal whose condition holds RIGHT NOW is the honest
        # resume point; everything after it re-runs even if some earlier
        # attempt once completed it — position is not an achievement.
        resume = 0
        at0 = self.settle()
        for i in range(len(subgoals) - 1, -1, -1):
            dw = subgoals[i].get("done_when")
            # ONLY positional conditions are resume evidence. A flag or
            # badge holds forever once earned, so a stale-true flag late
            # in the plan teleported the resume past everything: v8 ended
            # on talk_to_bill {EVENT_GOT_SS_TICKET} — true since morning
            # — and the whole leg "completed" without the HM it was for.
            if not isinstance(dw, dict):
                continue
            if "any_of" in dw:
                # An either/or is resume evidence only if EVERY branch is
                # positional. One flag branch would satisfy the whole
                # predicate from an achievement earned hours ago, which is
                # the teleport this block exists to prevent.
                if not pred_keys(dw) <= {"map", "area", "player_at"}:
                    continue
            elif not ("map" in dw or "area" in dw):
                continue
            try:
                if pred_holds(dw, at0):
                    resume = min(i + 1, len(subgoals) - 1)
                    break
            except Exception:
                continue
        for idx, sg in enumerate(subgoals):
            if idx < resume:
                # A POSITION CANNOT VOUCH FOR AN ACHIEVEMENT BEFORE IT.
                # This block already refuses to use a flag as resume
                # EVIDENCE, and then skipped flag subgoals anyway once a
                # later positional one held: leg 3's plan was
                #   reach_pallet_town {map} / enter_oaks_lab {area} /
                #   deliver_parcel {flag EVENT_GOT_POKEDEX} /
                #   reach_viridian_city {map VIRIDIAN_CITY}
                # and the party STANDING in Viridian honored all four, so
                # the parcel was never delivered, the Pokedex never got,
                # and the leg marched on to Pewter with the parcel still
                # in the bag. Its own comment says position is not an
                # achievement; this makes the skip obey that.
                #
                # Walking somewhere twice is cheap and idempotent, which
                # is why positional waypoints are safely honored. A deed
                # is neither. So a non-positional subgoal before the
                # resume point is honored only if it actually HOLDS.
                dw0 = sg.get("done_when")
                positional = (isinstance(dw0, dict)
                              and pred_keys(dw0) <= {"map", "area",
                                                     "player_at"})
                if positional or (dw0 and pred_holds(dw0, at0)):
                    print(f"== subgoal: {sg['id']} (holds from where the "
                          f"party stands — honored)")
                    self.log("subgoal_prior_done", subgoal=sg["id"])
                    continue
                print(f"== subgoal: {sg['id']} (earlier in the plan, but "
                      f"it is a DEED and it has not happened)")
                self.log("subgoal_deed_not_skipped", subgoal=sg["id"],
                         done_when=dw0)
            # THE OBJECTIVE MET MID-PLAN ENDS THE PLAN. The leg is judged
            # on its LAST subgoal's condition, and a wander can satisfy it
            # while some middle step is being ground on: leg 19 stood in
            # LAVENDER_TOWN — the objective — during a heal detour, walked
            # out again, and spent the rest of the attempt hunting a flute
            # for a road it had already used. Only the current subgoal was
            # ever checked. Transient conditions (a map) must be caught at
            # the moment; durable ones were already caught at attempt start.
            _fin = (subgoals[-1] or {}).get("done_when")
            if idx < len(subgoals) - 1 and _fin \
                    and pred_holds(_fin, self.settle()):
                print(f"== the plan's OBJECTIVE ({json.dumps(_fin)}) holds "
                      f"from where the party stands — the leg's aim is "
                      f"achieved; skipping the remaining steps")
                self.log("plan_objective_met_early", skipped_from=sg["id"])
                return True
            has_macro = bool(sg.get("macro"))
            print(f"== subgoal: {sg['id']}" + ("" if has_macro else " (no macro)"))
            ok = self._attempt(sg)
            # BACKTRACK: a subgoal that cannot be done may not be the broken
            # one. A done_when like {map:X} is satisfied ANYWHERE on X, so the
            # PREVIOUS subgoal can "succeed" in a place this one is impossible
            # from (Route 4's two halves). Re-open it in REDO mode — same
            # done_when, but it must relocate — then try this one again.
            # Harness logic, not route knowledge: it fixes the whole class.
            # ...but only if redoing it could CHANGE anything. Backtracking
            # into a subgoal whose condition already holds just makes it
            # wander: exit_house (done_when map:PALLET_TOWN) was redone from
            # inside Pallet over and over, and because REDO demands a region
            # change it toured the houses instead. Walk back to the last
            # subgoal that is actually unsatisfied.
            prev = None
            if (not ok and self.can_escalate and idx > 0
                    and backtracks < 2 and not sg.get("optional")):
                at = self.settle() or {}
                # A satisfied MAP subgoal is still worth redoing when that
                # map has other enclosed areas we have not searched for this
                # goal — "I am on B2F" is true in all four of its rooms, and
                # the nerd is in one of them. Without this the gate ended the
                # plan and the campaign restarted, instead of relocating one
                # room over, instead of ending the plan and restarting the
                # whole campaign.
                # And look PAST satisfied gates: with defeat_super_nerd's
                # flag already set, the candidate scan stopped on it with
                # "already holds" while the relocatable descend_to_b2f sat
                # one step further back — so the stored macro kept replaying
                # the wrong ladder and the waypoint leg kept dying in the
                # wrong room, taking the wrong ladder every time.
                cand = None
                holds = False
                elsewhere = []
                for back in range(idx - 1, max(-1, idx - 5), -1):
                    c = subgoals[back]
                    h = pred_holds(c.get("done_when") or {}, at)
                    if not h:
                        cand, holds = c, False
                        break
                    want = (c.get("done_when") or {}).get("map")
                    if want:
                        done = self._worked_for(self._target_key(sg))
                        here_now = self._where(at)
                        elw = [r for r in
                               set(list(self.explored) + list(self.visits))
                               if r.split("|")[0] == want
                               and r != here_now and r not in done]
                        if elw:
                            cand, holds, elsewhere = c, True, elw
                            break
                if cand is None:
                    self.log("backtrack_skipped", failed=sg["id"],
                             candidate=subgoals[idx - 1]["id"],
                             reason="nothing redoable behind")
                else:
                    if holds:
                        self.log("backtrack_relocate_within_map",
                                 failed=sg["id"], candidate=cand["id"],
                                 unsearched=len(elsewhere))
                    prev = cand
            if prev is not None:
                stuck_region = ((self.settle() or {}).get("map")
                                or {}).get("region", "")
                backtracks += 1
                # REDO ONLY WHEN IT IS TRUE. The candidate is chosen either
                # because its condition still HOLDS and another place also
                # satisfies it (relocate), or because its condition does
                # NOT hold at all (it was never really done). Both were
                # escalated with redo=True, whose prompt opens "you ALREADY
                # satisfy DONE_WHEN — but you are in the WRONG PLACE" —
                # told to a run that did not hold the item, twelve rounds
                # running: it "knew" it had Fresh Water because we said so.
                # A step whose condition is false gets an ordinary
                # escalation of that step.
                _redo = bool(pred_holds(prev.get("done_when") or {},
                                        self.settle() or {}))
                print(f"   <- backtracking: "
                      + (f"redoing {prev['id']} (it may have finished in "
                         f"the wrong place)" if _redo else
                         f"re-opening {prev['id']} (its condition does not "
                         f"hold)"))
                self.log("backtrack", failed=sg["id"], redoing=prev["id"],
                         redo=_redo)
                try:
                    moved, ops = self.escalate(
                        prev, redo=_redo, avoid_region=stuck_region,
                        blocked_target=self._target_key(sg),
                        blocked_by=sg.get("goal_text", sg["id"])[:120])
                except TimeoutError as e:
                    self.log("escalate_timeout", subgoal=prev["id"],
                             err=str(e))
                    moved = False
                if moved:
                    self.log("backtrack_relocated", subgoal=prev["id"])
                    print(f"   -> relocated; retrying {sg['id']}")
                    ok = self._attempt(sg)
                    if not ok and backtracks < 2:
                        # relocating somewhere else that still cannot reach
                        # the goal is a wrong guess, not a dead end — try
                        # once more from the new position
                        backtracks += 1
                        print(f"   <- backtracking again: {prev['id']}")
                        self.log("backtrack", failed=sg["id"],
                                 redoing=prev["id"], attempt=backtracks)
                        try:
                            moved2, _ = self.escalate(
                                prev, redo=bool(pred_holds(
                                    prev.get("done_when") or {},
                                    self.settle() or {})),
                                avoid_region=stuck_region,
                                blocked_target=self._target_key(sg),
                                blocked_by=sg.get("goal_text", sg["id"])[:120])
                        except TimeoutError:
                            moved2 = False
                        if moved2:
                            ok = self._attempt(sg)
            # A plan is not dead because ONE subgoal is: a side objective
            # (the fossil fight), an unaffordable shop, or a step the world
            # already satisfied differently should not end the run. Carry on
            # and let the remaining subgoals judge — the plan fails when it
            # cannot make progress at all (3 failures in a row) or when the
            # LAST subgoal is unmet. Marking specific subgoals "optional" by
            # hand is an inserted signal a record run cannot contain; this
            # decides it at runtime instead.
            if not ok and not sg.get("optional"):
                # A KNOWN repeat offender failing again is expected, not
                # news: its budget was shrunk precisely so the plan could
                # get PAST it. Counting those toward the consecutive-fail
                # abort meant a three-march doomed prefix killed the plan
                # before its untested tail ever ran — fast-failing just
                # aborted faster.
                if self._prior_subgoal_fails.get(sg["id"], 0) == 0:
                    fails += 1
                last = sg is plan["subgoals"][-1]
                # An EVENT is a gate, not a step you can walk past. When
                # defeat_mt_moon_nerd failed, the plan carried on and
                # "completed" three subgoals that are satisfied by RETREATING
                # (ascend to B1F, ascend to 1F, exit to Route 4), marching to
                # the end having achieved nothing and only noticing at
                # Cerulean. A missed map hop can be carried; a missed event
                # cannot, because everything after it assumes it happened.
                gate = bool(pred_keys(sg.get("done_when") or {})
                            & {"flag", "badge"})
                if gate:
                    print(f"   !! {sg['id']} failed and it is an EVENT gate "
                          f"— not continuing past it")
                    self.log("gate_subgoal_failed", subgoal=sg["id"],
                             done_when=json.dumps(sg.get("done_when")))
                elif fails < 3 and not last:
                    print(f"   !! {sg['id']} failed — continuing")
                    self.log("subgoal_failed_continuing", subgoal=sg["id"],
                             consecutive=fails)
                    # ...AND THE END OF THE RUN MUST SAY SO. Carrying a
                    # missed map hop is deliberate; reporting the result as
                    # ALL PLANS COMPLETE afterwards is not. Leg 34 skipped
                    # three of six subgoals (never reached Celadon, never
                    # bought the drink), satisfied a last subgoal that only
                    # asked to be standing in a gate building, and printed
                    # the same sentence a clean run prints.
                    self._carried = getattr(self, "_carried", 0) + 1
                    self._carried_ids = getattr(self, "_carried_ids", [])
                    self._carried_ids.append(sg["id"])
                    continue
            elif ok:
                fails = 0
            if not ok and sg.get("optional"):
                # a shop you cannot afford is skipped, not run-fatal — the
                # player walks on and makes do (brock39 arrived at Pewter
                # with 140 money and died to a hard potion gate)
                print(f"   skipped (optional): {sg['id']}")
                self.log("subgoal_skipped_optional", subgoal=sg["id"])
                continue
            if not ok:
                print(f"!! FAILED: subgoal {sg['id']}")
                self.log("plan_failed_at", subgoal=sg["id"])
                self.failed_subgoal = sg["id"]
                return False
            print(f"   done: {sg['id']}")
            # Save after each completed SUBGOAL, not just each plan. A leg
            # that never completes never saved, so a restart threw away
            # everything won inside it — the Mt Moon fossil was taken and
            # then lost on the next launch, twice. "Resume from the last
            # step that worked" only means anything if the step is recorded.
            # Do NOT save while a blackout recovery is still pending. A wipe
            # teleports you to a Center; if a subgoal completes there and we
            # save, the setback is baked into the save and the NEXT attempt
            # resumes in town — undoing the walk-back and re-walking to the
            # mountain, leaving the run wandering the town it respawned in.
            # Save once the party is back where it fell.
            if self.save_each and self._faint_at:
                self.log("save_deferred", subgoal=sg["id"],
                         pending_return=self._faint_at)
            elif self.save_each:
                r = (self._send_safe("save_game") or {}).get("result") or {}
                if not r.get("ok"):
                    self.log("subgoal_save_failed", subgoal=sg["id"],
                             detail=r.get("detail"))
        self.log("plan_complete", goal=plan.get("goal"),
                 escalations=self.escalations)
        return True


def bootstrap(b: Bridge, cont: bool = False):
    """New game, or CONTINUE from the on-disk save (mash A: with a save
    present the title's first option is CONTINUE, and A confirms the info
    box — the player's own resume path)."""
    if cont:
        print("[bootstrap] continue from save")
    else:
        print("[bootstrap] new_game (decision-free ceremony skip)")
        r = (b.send("new_game") or {}).get("result") or {}
        if not r.get("ok"):
            raise RuntimeError(f"new game failed: {r.get('detail')}")
    # Mash A through the title/info box, then STOP: a save resumes exactly
    # where it was written, and if that spot faces an NPC every further A
    # talks to them. The Pokemon Center save died on the nurse this way;
    # the mart save died deeper — six A's per round opened the SHOP MENU
    # and dug into it faster than the one B per round could close it, so
    # every --continue crashed on a restored ShopMenu without playing a
    # step. Two A-rounds clear the ceremony; after that B is the workhorse
    # (cancel menus, close text) with a rare A to advance anything only A
    # can, at odds B always wins.
    for i in range(24):
        if i < 2:
            o = b.send("mash_a", times=6) or {}
        elif i % 6 == 5:
            o = b.send("mash_a", times=2) or {}
        else:
            o = b.send("tap", btn="b") or {}
        if (o or {}).get("mode") == "overworld":
            return
        o = b.obs() or {}
        if o.get("mode") == "overworld":
            return
    raise RuntimeError(
        f"bootstrap failed (stuck in mode={(b.obs() or {}).get('mode')})")


def _write_last_state(b, failed_plan=None, failed_subgoal=None):
    """Snapshot where the run stands, for the campaign's re-author.

    Called on the normal exit path AND from the crash handler: a snapshot
    that is missing is worse than useless, because the loop then reads a
    PREVIOUS campaign's file and plans against a game that no longer exists.

    WHICH LEG FAILED is recorded here rather than re-derived from world
    state. A wipe at Misty teleports the party back to the Mt Moon centre,
    which makes the MOUNTAIN leg's "be in Cerulean" condition false — so
    the campaign blamed the mountain and re-authored it 17 times while the
    badge leg, the only one that could gain a training subgoal, was never
    reconsidered once. The leg that failed is a fact the executor holds;
    guessing it from where the party ended up gets it wrong exactly when a
    fight knocks the run backwards.
    """
    try:
        o = b.obs() or {}
        (RUN / "last_state.json").write_text(json.dumps({
            "map": (o.get("map") or {}).get("id"),
            "region": (o.get("map") or {}).get("region"),
            # hp alone is unreadable at plan time — health only means
            # anything against max_hp, and a start state that cannot say
            # "already healthy" leaves the re-author keeping every heal leg
            # defensively while it prunes shopping the visible bag settles
            # MOVES TRAVEL WITH THE PARTY. This whitelist silently dropped
            # them, so the start line said "CHARMELEON L32 88/88hp" and the
            # author could not see two of its four slots were GROWL and
            # LEER. state_text learned to print movesets hours ago and the
            # sentence never changed, because last_state is what a re-author
            # actually reads — obs.json belongs to a game process that has
            # already exited.
            "party": [{"species": m.get("species"), "level": m.get("level"),
                       "hp": m.get("hp"), "max_hp": m.get("max_hp"),
                       "status": m.get("status"), "moves": m.get("moves"),
                       # types are on the party screen; without them the
                       # sweep's state text could not tell CHARIZARD was
                       # the FLYING type the objective wanted
                       "types": m.get("types")}
                      for m in (o.get("party") or [])],
            "badges": o.get("badges") or [],
            "bag": o.get("bag") or {},
            "money": o.get("money"),
            # where a faint sends you — carried so the re-author sees it
            "respawn": o.get("respawn"),
            # a party member that is NOT in the party — without this the
            # re-author sees one Magikarp and no reason for it
            "daycare": o.get("daycare"),
            "flags": o.get("flags") or [],
            "failed_plan": failed_plan,
            "failed_subgoal": failed_subgoal,
        }, indent=1))
    except Exception as e:
        print(f"[warn] could not write last_state.json: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plans", type=Path, nargs="+")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--continue", dest="cont", action="store_true",
                    help="bootstrap resumes the on-disk save (title "
                         "CONTINUE) instead of starting a new game")
    ap.add_argument("--save-after-each", action="store_true",
                    help="in-game SAVE after each completed plan (player-"
                         "action persistence for chained legs)")
    ap.add_argument("--max-battle-turns", type=int, default=40)
    ap.add_argument("--verify-macros", action="store_true",
                    help="replay each successful macro from a restored "
                         "checkpoint before committing it (authoring "
                         "hygiene; visibly bounces the player and pollutes "
                         "the exploration memory, so off by default)")
    ap.add_argument("--score-battles", action="store_true",
                    help="probe the oracle each battle turn and log "
                         "policy-vs-oracle agreement (does not change play)")
    ap.add_argument("--escalate", action="store_true",
                    help="when a subgoal has no macro or its macro fails, hand "
                         "it to the live model, then DISTILL the successful ops "
                         "back into the plan file as the subgoal's macro")
    ap.add_argument("--model", default="gemma4:26b-a4b-it-q4_K_M")
    ap.add_argument("--run-id", default="run")
    ap.add_argument("--policy-spec", type=Path, default=None,
                    help="model-authored battle-policy spec (JSON); replaces "
                         "the hand-seeded default in every battle decision")
    args = ap.parse_args()
    if args.policy_spec:
        set_active_spec(battle_policy.load_spec(args.policy_spec))
        print(f"[policy] active spec: {ACTIVE_SPEC.get('name')} "
              f"({args.policy_spec})")

    global SCORE_BATTLES, VERIFY_MACROS
    # RED_SCORE_BATTLES=1 does the same as --score-battles. The flag exists
    # and no orchestrator has ever passed it, so the oracle has never once
    # scored the spec that actually plays — its single live run predates the
    # commit that made the model-authored spec play at all. Adding the flag
    # to fresh_run.sh means editing a shell script that may be mid-chain, and
    # the rule here is that a running script is never edited; an env var can
    # be set on the next launch instead. Scoring probes, it does not choose,
    # so it changes turn cost and nothing else.
    SCORE_BATTLES = args.score_battles or os.environ.get(
        "RED_SCORE_BATTLES") == "1"
    VERIFY_MACROS = args.verify_macros
    b = Bridge()
    if args.bootstrap:
        bootstrap(b, cont=args.cont)
    ex = Executor(b, max_battle_turns=args.max_battle_turns,
                  can_escalate=args.escalate, model=args.model,
                  run_id=args.run_id)
    ex.save_each = args.save_after_each
    # ...and from here on a stop saves what it earned (see
    # _install_stop_handler). Installed AFTER the bridge is up, so the
    # handler always has something to save through.
    if args.save_after_each:
        ex._install_stop_handler()
    ex.seed_regions()          # the bridge is up; re-teach known place-names
    ok = True
    for plan_path in args.plans:
        plan = json.loads(plan_path.read_text())
        ex.plan, ex.plan_path = plan, plan_path
        ex.status(plan=plan_path.name)
        print(f"\n===== PLAN: {plan_path.name} =====")
        ok = ex.run_plan(plan)
        # A leg that walked to the end of its subgoal list has not
        # necessarily ACHIEVED anything: continue-past-failure lets it reach
        # the end with the objective unmet, and the chain then started the
        # NEXT leg on a premise that was never true — mountain subgoals were
        # running on a fresh Charmander L7 with no badge. Check the leg's
        # final condition against the live game before going on.
        if ok:
            final = (plan.get("subgoals") or [{}])[-1].get("done_when") or {}
            # ...BUT A TRANSIENT CONDITION CANNOT BE RE-WITNESSED. This
            # re-check calls settle(), whose whole job is to resolve the
            # game to a clean decision state — which CLOSES whatever menu
            # is open. So a leg whose objective is a UI screen is failed by
            # the act of checking it: leg 3 opened the PC, its subgoal
            # reported done fourteen times, and every attempt died on
            # "reached its last subgoal but its objective {"screen":
            # "BoxMenu"} is NOT met". Twenty-two plan versions, hours, and
            # the run never once did anything wrong.
            # The guard is right for DURABLE facts — a badge, a flag, an
            # item, a map — which is what it was written for (mountain
            # subgoals running on a fresh Charmander with no badge). A
            # screen is true only while it is open, the subgoal's own
            # success already witnessed it, and there is nothing left to
            # re-witness.
            if final and pred_keys(final) <= {"screen", "mode"}:
                ex.log("plan_objective_transient", plan=plan_path.name,
                       final=json.dumps(final))
                final = {}
            if final and not pred_holds(final, ex.settle()):
                print(f"!! {plan_path.name} reached its last subgoal but its "
                      f"objective {json.dumps(final)} is NOT met — stopping "
                      f"here rather than starting the next leg on a false "
                      f"premise")
                ex.log("plan_objective_unmet", plan=plan_path.name,
                       final=json.dumps(final))
                ok = False
        if not ok:
            break
        if args.save_after_each:
            r = (ex._send_safe("save_game") or {}).get("result") or {}
            print(f"[save] {r.get('detail') or 'save failed'}")
    o = b.obs() or {}
    # Durable snapshot of where the run ENDED. obs.json belongs to the live
    # bridge and is gone once the game process dies, so the campaign's
    # re-author was reading "an unknown location" — throwing away the single
    # most useful piece of evidence it has about what to fix.
    # Taken BEFORE the save below: save_game drives the START menu, and an
    # observation caught mid-menu carries no map at all, which is exactly
    # the "unknown location" the snapshot exists to prevent.
    _write_last_state(b, failed_plan=(None if ok else
                                      getattr(ex, "plan_path", None)
                                      and ex.plan_path.name),
                      failed_subgoal=(None if ok else ex.failed_subgoal))
    # SAVE WHAT WAS EARNED, even when the plan failed. The save above only
    # fires for a plan that fully succeeded — `if not ok: break` skips it —
    # so an attempt that crossed two maps, beat fifteen trainers and banked
    # 3277 money threw ALL of it away because its last subgoal failed, and
    # the next attempt replayed from a stale save. A whole campaign ran
    # without writing one save. Levels, items and event flags only ever go
    # UP in gen1, so persisting a failed attempt's state cannot lose
    # progress; position is the one thing that can be worse, and walking is
    # what this harness is best at.
    if args.save_after_each and not ok:
        r = (ex._send_safe("save_game") or {}).get("result") or {}
        print(f"[save] (after a failed plan, to keep what it earned) "
              f"{r.get('detail') or 'save failed'}")
    _carried = getattr(ex, "_carried_ids", [])
    _verdict = ("ALL PLANS COMPLETE" if ok and not _carried else
                (f"PLANS ENDED WITH UNMET SUBGOALS ({', '.join(_carried)})"
                 if ok else "PLAN FAILED"))
    print(f"\nRESULT: {_verdict} | "
          f"map={(o.get('map') or {}).get('id')} "
          f"party={[(m.get('species'), m.get('level')) for m in o.get('party') or []]} "
          f"badges={o.get('badges')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        # a crashing attempt must still leave an honest snapshot, or the
        # campaign plans its next leg against a stale one
        try:
            _write_last_state(Bridge())
        except Exception:
            pass
        raise
