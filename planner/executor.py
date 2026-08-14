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
import sys
import time
from pathlib import Path

from bridge import Bridge, RUN
import battle_policy

# Which gym holds which badge — the pamphlet's leader page.
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


def _doorstep(map_id: str) -> str:
    """The printed-map place a target sits in: itself if the town map
    draws it, else the city its name carries (CELADON_GYM -> CELADON_CITY,
    the same fallback badge routing already uses)."""
    if not map_id or map_id in MAP_EDGES:
        return map_id
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
def model_view(obs: dict) -> dict:
    o = dict(obs or {})
    o.pop("flags", None)
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
            if not any(pred_holds(alt, obs) for alt in (want or [])):
                return False
        elif key == "map":
            if (obs.get("map") or {}).get("id") != want:
                return False
        elif key == "mode":
            if obs.get("mode") != want:
                return False
        elif key == "party_nonempty":
            if bool(obs.get("party")) != want:
                return False
        elif key == "party_alive":
            alive = any((m.get("hp") or 0) > 0 for m in obs.get("party") or [])
            if alive != want:
                return False
        elif key == "party_healthy":
            mons = obs.get("party") or []
            healthy = bool(mons) and all(
                (m.get("hp") or 0) > 0
                and (not m.get("max_hp") or m["hp"] == m["max_hp"])
                and m.get("status") in (None, "", "0", "NONE", "OK")
                for m in mons)
            if healthy != want:
                return False
        elif key == "lead_level":
            lead = (obs.get("party") or [{}])[0]
            if (lead.get("level") or 0) < want:
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
            if not mons or any((m.get("level") or 0) < want for m in mons):
                return False
        elif key == "slot_level":
            # a specific party slot (1-based), for "get the SECOND one to N"
            mons = obs.get("party") or []
            slot = int((want or {}).get("slot", 1))
            need = int((want or {}).get("min", 0))
            if slot < 1 or slot > len(mons):
                return False
            if (mons[slot - 1].get("level") or 0) < need:
                return False
        elif key == "has_item":
            bag = obs.get("bag") or {}
            for item, n in (want or {}).items():
                if not bag or bag.get(item, 0) < n:
                    return False
        elif key == "player_at":
            # {"x":N,"y":N,"radius":R} — where you are standing is
            # player-visible, and a map id alone cannot distinguish
            # disconnected regions that share one id
            pl = obs.get("player") or {}
            if pl.get("x") is None or pl.get("y") is None:
                return False
            r = (want or {}).get("radius", 4)
            if (abs(pl["x"] - want["x"]) > r
                    or abs(pl["y"] - want["y"]) > r):
                return False
        elif key == "party_size":
            if len(obs.get("party") or []) < want:
                return False
        elif key == "badge":
            if want not in (obs.get("badges") or []):
                return False
        elif key == "flag":
            if want not in (obs.get("flags") or []):
                return False
        elif key == "no_battle":
            if (obs.get("mode") == "battle") == want:
                return False
        else:
            raise ValueError(f"unknown predicate key: {key}")
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


def _run_policy(spec, bridge, obs, log, max_turns, intent="fight"):
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
           "journal": DAMAGE_JOURNAL}
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


BATTLE_POLICIES = {
    "default": lambda b, o, lg, mt: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="fight"),
    "typed_v0": lambda b, o, lg, mt: _run_policy(
        battle_policy.SPECS["typed_v0"], b, o, lg, mt, intent="fight"),
    "slot1": battle_slot1,
    "traversal": lambda b, o, lg, mt: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="traversal"),
    "catch": lambda b, o, lg, mt: _run_policy(
        ACTIVE_SPEC, b, o, lg, mt, intent="catch"),
}


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
        self.searched: dict = {}    # "*" -> {region: fully worked};
                                    # flag:/item: keys add per-target claims
        self.contested: dict = {}   # target -> {region: a fight ran here}
        self._arrived = None        # (region, (x,y)) — the door we came in by
        self._came_from = None      # the region we were in a moment ago
        self._reversals = 0
        self._dead_visits = 0
        self._entered_map: dict = {}   # "target|map" -> entries for target
        self._revisit_refusals: dict = {}   # target -> refusals spent
        self._battle_regions: set = set()   # "target|region" a fight ran in
        self._blackouts: dict = {}          # target -> party wipes
        self._blackout_lead: dict = {}      # target -> lead level, last wipe
        self._faint_at = None               # region we were in when wiped
        self._ui_pending = 0                # rounds a prompt has sat open
        self._dead_ops: dict = {}           # (target, op, arg) -> failures
        self.save_each = False              # in-game SAVE after each subgoal
        self._tried_objs: dict = {}         # region -> objects interacted
        self._inert_objs: dict = {}         # region -> {object: state it was inert in}
        self._cant_afford: dict = {}        # item -> unit price we lack
        self._no_cross: dict = {}           # region -> dirs proven uncrossable
        self._rounds_here: dict = {}        # target|region -> rounds spent
        self._fight_region: str | None = None   # where the last trainer fought
        self.flag_sites: dict = {}          # flag -> area it fired in
        self.shut_doors: dict = {}   # region -> doors seen but unreachable
        self._last_obs_dormant = 0   # objects this map has yet to reveal
        self.hints: dict = {}        # region -> things people said here
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

    def _note(self, obs):
        self.note_frontier(obs)
        self.note_sightings(obs)
        self.note_flag_site(obs)
        m = (obs or {}).get("map") or {}
        if m.get("id") and (m.get("connections") or m.get("warps")):
            e = self.atlas.setdefault(m["id"], {})
            if m.get("connections"):
                e["edges"] = m["connections"]
            if m.get("warps"):
                e["warps"] = [{"x": w.get("x"), "y": w.get("y"),
                               "dest": w.get("dest")} for w in m["warps"]]
        return obs

    MEMORY = RUN / "explored.json"

    def _load_memory(self):
        """Carry the map across runs. Each attempt used to rediscover the
        same mountain from scratch: it explores outward from the entrance,
        exhausts the exits reachable from there, and never gets far enough
        to find the far-side door. Knowledge that survives the process is
        what turns N attempts into progress instead of N repetitions."""
        try:
            data = json.loads(self.MEMORY.read_text())
            self.explored = data.get("explored", {})
            self.dead_ends = data.get("dead_ends", {})
            self.visits = data.get("visits", {})
            self.frontier = data.get("frontier", {})
            self.sightings = data.get("sightings", {})
            self.searched = data.get("searched", {})
            self.contested = data.get("contested", {})
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
            for r in [r for r in anyd
                      if r.split("|")[0].endswith(("POKECENTER", "MART"))]:
                anyd.pop(r, None)
            # every surviving entry was recorded under the fully-worked
            # condition, so the union of targets joins the worked rooms
            for tgt, rooms in list(self.searched.items()):
                if tgt != "*":
                    for r in rooms:
                        anyd[r] = True
            self._tried_objs = {r: set(v) for r, v in
                                (data.get("touched") or {}).items()}
            self._no_cross = {r: set(v) for r, v in
                              (data.get("no_cross") or {}).items()}
            self.flag_sites = data.get("flag_sites") or {}
            self.shut_doors = data.get("shut_doors") or {}
            self.hints = data.get("hints") or {}
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
            self._plan_done = data.get("plan_done") or {}
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
            edges = sum(len(v) for v in self.explored.values())
            if edges:
                print(f"[memory] {len(self.explored)} areas, {edges} known "
                      f"exits from previous runs")
        except (OSError, ValueError):
            self.explored, self.dead_ends = {}, {}
            self.visits, self.frontier, self.sightings = {}, {}, {}
            self.searched = {}
            self.contested = {}

    def _save_memory(self):
        try:
            self.MEMORY.write_text(json.dumps(
                {"explored": self.explored, "dead_ends": self.dead_ends,
                 "visits": self.visits, "frontier": self.frontier,
                 "sightings": self.sightings, "searched": self.searched,
                 "contested": self.contested,
                 # touched outlives the process so "sighted but never
                 # touched" stays computable across attempts — the Mt Moon
                 # fossils are the door east, and every restart forgot who
                 # had already been talked to
                 "touched": {r: sorted(s)
                             for r, s in self._tried_objs.items()},
                 "no_cross": {r: sorted(s)
                              for r, s in self._no_cross.items()},
                 "flag_sites": self.flag_sites,
                 "shut_doors": self.shut_doors,
                 "hints": self.hints,
                 "blackouts": self._blackouts,
                 "blackout_lead": self._blackout_lead,
                 "plan_done": getattr(self, "_plan_done", {})},
                indent=1))
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
        if not set(names).issubset(was):
            self.sightings[here] = sorted(was | set(names))
            self._save_memory()

    def note_frontier(self, obs):
        self._last_obs_dormant = ((obs or {}).get("map") or {}).get("dormant")
        """Every exit visible from where we stand — the inventory that makes
        'all ways out are dead' a justified conclusion rather than a guess."""
        here = self._where(obs)
        if "None" in here:
            return
        # A visit is a VISIT, counted on arrival — not only on a recorded
        # transition. Regions whose transitions landed under other labels
        # (the hop-free relabeling) collected zero visits however often
        # the escort delivered the party there, so they ranked "freshest"
        # forever and the reroute elected the same mirage six times.
        if here != getattr(self, "_last_visit_region", None):
            self.visits[here] = self.visits.get(here, 0) + 1
            self._last_visit_region = here
        m = (obs or {}).get("map") or {}
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
        shut = sorted(f"{k}->{dest} ({who} is standing there)"
                      for k, dest, who in self._unopened_doors(obs))
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
        _nc = self._no_cross.get(here, set())
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
        if (target or "").startswith(("item:", "party_healthy")):
            return self.searched.get(target) or {}
        return self.searched.get("*") or {}

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
        if region.split("|")[0].endswith(("POKECENTER", "MART")):
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
                  "slot_level", "party_healthy"):
            if k in dw:
                return f"{k}:{dw[k]}"
        return "subgoal:" + sg.get("id", "?")

    @staticmethod
    def _where(obs) -> str:
        m = (obs or {}).get("map") or {}
        return f"{m.get('id')}|{m.get('region')}"

    def note_transition(self, before_obs, step, after_obs):
        """Record: from this area, that exit led there."""
        src, dst = self._where(before_obs), self._where(after_obs)
        if src == dst or "None" in src or "None" in dst:
            return
        key = (f"{step.get('x')},{step.get('y')}"
               if step.get("x") is not None else step.get("dir"))
        if key is None:
            return
        self.visits[dst] = self.visits.get(dst, 0) + 1
        dmap = dst.split("|")[0]
        if dmap != src.split("|")[0] and self._cur_target:
            k = f"{self._cur_target}|{dmap}"
            self._entered_map[k] = self._entered_map.get(k, 0) + 1
        ap = (after_obs or {}).get("player") or {}
        if ap.get("x") is not None:
            self._arrived = (dst, (ap["x"], ap["y"]))
            self._came_from = src
            self._reversals = 0
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
        if old and old.get("to") not in (dst,) \
                and dst not in AREA_ALIASES.get(old.get("to"), ()):
            self.log("edge_conflict", frm=src, via=str(key),
                     was=old.get("to"), now=dst)
            del node[key]
            self._save_memory()
            return
        e = node.setdefault(key, {"n": 0, "to": dst})
        e["n"] += 1
        e["to"] = dst
        self.log("explored", frm=src, via=str(key), to=dst, times=e["n"])
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
        taken = self.explored.get(here, {}) or {}
        m = (obs or {}).get("map") or {}
        folk = [o for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("x") is not None]
        out = []
        for w in (m.get("warps") or []):
            k = f"{w.get('x')},{w.get('y')}"
            if k in taken or w.get("reachable"):
                continue
            near = next((o.get("name") for o in folk
                         if abs((o.get("x") or 0) - (w.get("x") or 0))
                         + abs((o.get("y") or 0) - (w.get("y") or 0)) <= 1),
                        None)
            if near:
                out.append((k, w.get("dest"), near))
        return out

    def _untried_exits(self, obs) -> list:
        """Ways out of here never taken — doors and roads alike. Map edges
        count: a town's road out is the exit an event most often hides on."""
        m = (obs or {}).get("map") or {}
        taken = self.explored.get(self._where(obs), {}) or {}
        # a proven-uncrossable seam is not an exit — leaving it "untried"
        # here meant the searched proof could never fire for a stub region
        # and the escort ranked it as frontier forever
        blocked = self._no_cross.get(self._where(obs), set())
        seen_maps = {a.split("|")[0] for a in self.visits}
        out = []
        for w in (m.get("warps") or []):
            if not w.get("reachable"):
                continue
            k = f"{w.get('x')},{w.get('y')}"
            if k not in taken and k not in blocked:
                out.append((w.get("dest") in seen_maps,
                            f"({k})->{w.get('dest')}"))
        for d, t in (m.get("connections") or {}).items():
            if d not in taken and d not in blocked:
                out.append((t in seen_maps, f"walk {d} -> {t}"))
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
            return out

        seen, q = {frm} | set(avoid or ()), deque([(frm, [])])
        while q:
            cur, path = q.popleft()
            for key, e in edges(cur).items():
                nxt = e.get("to")
                if not nxt or nxt in seen:
                    continue
                hop = path + [(key, nxt)]
                if nxt == to or nxt in AREA_ALIASES.get(to, ()):
                    return hop
                seen.add(nxt)
                q.append((nxt, hop))
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
                    if "," in key:
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
                             "y": int(key.split(",")[1])} if "," in key
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
            done_x = set((self.explored.get(region) or {}).keys())
            fresh = [e for e in exits if e not in done_x]
            if not fresh:
                continue
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
            rank = (goalward, self.visits.get(region, 0), len(path))
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
                if "," in key:
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
                         "y": int(key.split(",")[1])} if "," in key
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

    def _walk_route(self, sg, path):
        """Replay a fully-walked route hop by hop (the escort's pattern):
        send the edge, settle, fight through interruptions, record the
        transition. Returns where the walk ended."""
        o = None
        for key, nxt in path:
            for _ in range(4):
                pre = self.b.obs()
                if "," in key:
                    x, y = key.split(",")
                    self._send_safe("use_warp", x=int(x), y=int(y))
                    step = {"x": int(x), "y": int(y)}
                else:
                    self._send_safe("cross", dir=key)
                    step = {"dir": key}
                o = self.settle()
                if o and pre and ((pre.get("map") or {}).get("id")
                                  != (o.get("map") or {}).get("id")):
                    self.note_transition(pre, step, o)
                fought = False
                while o and o.get("mode") == "battle":
                    o = self.handle_battle(sg, o)
                    o = self.settle()
                    fought = True
                if self._where(o) == nxt or not fought:
                    break
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
            if self._where(o) != nxt:
                # A hop that fails to land even after the passage retry
                # CONTRADICTS the recorded edge: void it, or the router
                # re-picks the phantom forever (a blackout walk-back
                # minted a phantom and fifteen straight walks died on it).
                frm = self._where(pre)
                rec = (self.explored.get(frm) or {}).get(key)
                if rec and rec.get("to") == nxt:
                    del self.explored[frm][key]
                    self.log("edge_voided", frm=frm, via=key, to=nxt)
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
            if vis.get(m, 0) >= 8 and not vis.get(nb))

    def _goal_score(self, from_map: str, want: str, blocked) -> int:
        """Printed-map legs from here to the goal, avoiding shut maps —
        and when no open road to the goal exists at all, legs to the
        NEAREST GROUND NEVER SET FOOT ON. A sealed goal should send the
        run looking, not re-treading: with Saffron shut there is no
        printed route to Celadon, and the honest next move is the
        unexplored east."""
        h = static_hops(from_map, want, blocked)
        if h is not None:
            return h
        vis = self._map_visits()
        best = None
        for m in MAP_EDGES:
            if vis.get(m):
                continue
            hh = static_hops(from_map, m, blocked)
            if hh is not None and (best is None or hh < best):
                best = hh
        return 50 + best if best is not None else 99

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
        if self._ui_pending < 1:
            self._ui_pending += 1
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

    def _logged_exploration(self, obs, sg) -> str:
        txt = self.exploration_text(obs, self._target_key(sg))
        self.log("escalate_context", subgoal=sg["id"],
                 target=self._target_key(sg), memory=txt[:1200])
        return txt

    def exploration_text(self, obs, target: str = "") -> str:
        """Untried vs already-taken exits from where we stand."""
        here = self._where(obs)
        taken = self.explored.get(here, {})
        m = (obs or {}).get("map") or {}
        # candidates are DOORS *and* MAP EDGES. Listing only warps meant a
        # town's road out never appeared as untried, so the run kept
        # re-entering the same building instead of walking north (pure4).
        warps = [{"key": f"{w.get('x')},{w.get('y')}", "dest": w.get("dest"),
                  "reachable": w.get("reachable")}
                 for w in (m.get("warps") or [])]
        warps += [{"key": d, "dest": t, "reachable": True}
                  for d, t in (m.get("connections") or {}).items()]
        # A seam PROVEN uncrossable from this region is not an exit. A map
        # connection belongs to the whole map, so the stub side of a split
        # route still lists the far side's edge — and advertising it as
        # preferred-untried held the run on the Route 4 stub for twenty
        # rounds while the real door was named two lines below.
        blocked = self._no_cross.get(here, set())
        untried, tried = [], []
        for w in warps:
            if not w.get("reachable") or w["key"] in blocked:
                continue
            k = w["key"]
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
                    done_x = set((self.explored.get(dest) or {}).keys())
                    left = [e for e in (self.frontier.get(dest) or [])
                            if e not in done_x]
                    if left:
                        beyond = (f"; BUT {dest} still has {len(left)} exit(s) "
                                  f"never taken, so going back through here "
                                  f"is how you reach them")
                tried.append(
                    f"({k}) -> {dest} [taken {taken[k]['n']}x"
                    + (f"; that area is a KNOWN DEAD END for this goal, "
                       f"failed there {bad}x — do NOT go back" if bad else beyond)
                    + "]")
            else:
                untried.append(
                    (w.get("dest") in {a.split("|")[0] for a in self.visits},
                     f"walk {k} out of here -> {w.get('dest')}"
                     if not k[0].isdigit() else f"({k})->{w.get('dest')}"))
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
                    f"have already walked. Take it even if you have used it "
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
                    f"have already walked ({len(best)} legs total). Take it "
                    f"even if you have used it before; an untried exit that "
                    f"leads somewhere else is not progress toward this goal.")
        # Rooms already fully worked: nothing left to find in them, but you
        # may still walk through — that distinction is why they are not
        # dead ends. Read the ROOM-level ledger, not the per-target one:
        # travel goals never earn per-target entries, so keying the advice
        # by target meant the model was never told a room was finished
        # during exactly the legs where it cycled through worked rooms.
        worked = self._worked_for(target)
        done_rooms = [r for r in worked if r != here]
        searched_line = ""
        if worked.get(here):
            searched_line = ("\nYou have ALREADY fully worked this exact "
                             "area — every exit taken, everything touched. "
                             "Do not search it again; pass through or go "
                             "somewhere new.")
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
                "\nDOORS HERE YOU HAVE NEVER OPENED, each with somebody "
                "standing in the way: "
                + ", ".join(f"({k})->{d} — {who} is beside it"
                            for k, d, who in shut[:4])
                + ". A door does not move, so the person is what is shutting "
                "it. Talk to them, then try the door.")
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
                         + "\n  ".join(said_here[-6:]))
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
        if been >= 2 and not self.contested.get(target, {}).get(here):
            warned = (f"\nYOU HAVE BEEN IN THIS EXACT AREA {been} TIMES "
                      f"ALREADY ({here}). Arriving here again is not "
                      f"progress — if the last thing you did brought you "
                      f"back here, undo that choice and take a different "
                      f"exit.")
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
        held = {r: [f"{k}({who})" for k, _d, who in
                    [(x.split("->")[0], None,
                      x.split("(")[-1].rstrip(") ").replace(
                          " is standing there", ""))
                     for x in v]]
                for r, v in (self.shut_doors or {}).items() if r != here}
        for region, exits in list(self.frontier.items()) + \
                [(r, []) for r in held if r not in self.frontier]:
            if region == here:
                continue
            done_x = set((self.explored.get(region) or {}).keys())
            left = [e for e in exits if e not in done_x]
            left += held.get(region, [])
            if not left:
                continue
            # Naming a destination without its first leg loses to local
            # exits (the ROUTE_2 lesson) — but naming only the NEAREST
            # was goal-blind: it sold a Route 2 gate door while the way
            # to Cerulean waited on B2F. Distance and first leg for EVERY
            # candidate; which door matters is the model's judgment.
            path = self._route(here, region)
            if path:
                fk, fd = path[0]
                leg = (f"walk {fk}" if not fk[0].isdigit()
                       else f"door ({fk})")
                elsewhere.append(
                    f"{region} ({', '.join(sorted(left))} — {len(path)} "
                    f"leg(s) away, first: {leg} to {fd})")
            else:
                elsewhere.append(
                    f"{region} ({', '.join(sorted(left))} — no walked "
                    f"route from here)")
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
        loot = [_named(o) for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("name")
                and o.get("name") not in taken_objs]
        reach = [_named(o) for o in (m.get("objects") or [])
                 if o.get("reachable") and o.get("name")]
        loot_line = pp_line
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
            loot_line += ("\nRooms you have SEEN things in that you have "
                          "never touched: "
                          + "; ".join(t for _, t in held[:4])
                          + ". A thing in a passage can BE the blockage — "
                          "going back and pressing A on it can open ground "
                          "no exit reaches.")
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
            route_line += (f"\nTHE TOWN MAP: {want_map} attaches to — "
                           f"{att}. To arrive, stand in one of THOSE and "
                           f"cross the matching edge.")
            # ...and the town map can be READ ALL THE WAY: a static BFS
            # over its printed adjacencies gives the map-by-map itinerary
            # (interiors like tunnels don't appear on it — a leg that
            # cannot be crossed outdoors goes through one).
            here_map = self._where(
                self.b.obs() or {}).split("|")[0]
            if here_map in MAP_EDGES or any(
                    here_map in v.values() for v in MAP_EDGES.values()):
                import collections
                q = collections.deque([[here_map]])
                seen_m = {here_map}
                path_m = None
                while q:
                    p = q.popleft()
                    if p[-1] == want_map:
                        path_m = p
                        break
                    for _d, m2 in (MAP_EDGES.get(p[-1]) or {}).items():
                        if m2 not in seen_m:
                            seen_m.add(m2)
                            q.append(p + [m2])
                if path_m and len(path_m) > 1:
                    route_line += (
                        f"\nTOWN-MAP ITINERARY from {here_map}: "
                        + " -> ".join(path_m)
                        + ". Legs the evidence has proven blocked need a "
                          "tunnel, a building or a deed at that step.")
        if not (untried or tried):
            if elsewhere:
                return (warned + route_line
                        + "\nNothing here is new, but these places "
                        "you have already been still have ways you have "
                        "NEVER taken: " + "; ".join(sorted(elsewhere)[:6])
                        + ". Go back to one and take it." + near_hint
                        + loot_line)
            return (warned + route_line + searched_line + shut_line
                    + hint_line + loot_line)
        out = warned + "\nEXITS FROM HERE — "
        out += ("UNTRIED (prefer these, they are the only way to find "
                f"anything new): {', '.join(untried)}. " if untried
                else "none untried. ")
        if tried:
            out += (f"Already taken from here: {'; '.join(tried)} — retaking "
                    "one returns you where it says. That is still the right "
                    "move if the note says there is unopened ground beyond "
                    "it, or if nothing here is untried.")
        if elsewhere:
            out += ("\nPlaces you have already been that still have ways "
                    "you have NEVER taken: " + "; ".join(sorted(elsewhere)[:6])
                    + "." + near_hint)
        out += route_line + searched_line + shut_line + hint_line + loot_line
        return out

    def _atlas_text(self) -> str:
        parts = []
        for mid, e in self.atlas.items():
            bits = []
            if e.get("edges"):
                bits.append(", ".join(f"{d}->{t}"
                                      for d, t in e["edges"].items()))
            if e.get("warps"):
                dd: dict = {}
                for w in e["warps"]:
                    dd.setdefault(w["dest"], []).append(
                        f"({w['x']},{w['y']})")
                bits.append("doors: " + ", ".join(
                    f"{d} at {'/'.join(v[:2])}" for d, v in dd.items()))
            parts.append(f"{mid}: " + "; ".join(bits))
        return " | ".join(parts)

    def status(self, **kw):
        """Keep run/status.txt current: what is it TRYING to do right now.
        Watching the window shows behaviour; this shows intent. Pair them:
          watch -n1 cat ~/Developer/red-recomp/run/status.txt
        """
        self._st.update({k: v for k, v in kw.items() if v is not None})
        st = self._st
        obs = st.get("obs") or {}
        pl = obs.get("player") or {}
        party = ", ".join(
            f"{m.get('species')} L{m.get('level')} {m.get('hp')}/"
            f"{m.get('max_hp')}" for m in (obs.get("party") or []))
        lines = [
            f"PLAN     {st.get('plan','?')}",
            f"SUBGOAL  {st.get('subgoal','?')}  [{st.get('phase','')}]",
            f"GOAL     {(st.get('goal_text') or '')[:150]}",
            f"DONE_WHEN{json.dumps(st.get('done_when') or {})}",
            f"DOING    {st.get('doing','')}",
            f"LAST     {(st.get('last') or '')[:150]}",
            f"WHERE    {(obs.get('map') or {}).get('id')} "
            f"({pl.get('x')},{pl.get('y')}) mode={obs.get('mode')}",
            f"PARTY    {party}",
            f"MONEY    {obs.get('money')}   BAG {json.dumps(obs.get('bag') or {})}",
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
        name = subgoal.get("battle_policy")
        if not name:
            dw = subgoal.get("done_when") or {}
            name = ("catch" if "party_size" in dw
                    else "default" if ("lead_level" in dw
                                       or "party_min_level" in dw
                                       or "slot_level" in dw)
                    else "traversal")
            if name not in BATTLE_POLICIES:      # never crash on a bad key
                name = "traversal"
        # Name the combatants: three Misty wipes reached the re-author as
        # bare FAILED lines, so every rewrite fixed the route and never the
        # matchup — species and levels are on screen the whole fight.
        b0 = (obs or {}).get("battle") or {}
        foe, me = b0.get("foe") or {}, b0.get("me") or {}
        self.log("battle_start", subgoal=subgoal["id"], policy=name,
                 foe=f"{foe.get('species')} L{foe.get('level')}",
                 me=f"{me.get('species')} L{me.get('level')} "
                    f"{me.get('hp')}/{me.get('maxhp')}hp")
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
                                    self.max_battle_turns)
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

    def settle(self) -> dict:
        """Resolve to a clean decision state before checking guards/predicates.
        A step can leave the game mid-dialogue (e.g. the 'got the PARCEL!' box,
        after which the event flag sets only once it closes), where map reads
        None and map-keyed when-guards would wrongly skip. A `wait` triggers
        the shim's auto-advance, which rides plain text to the next decision."""
        try:
            obs = self.b.obs()
        except TimeoutError as e:
            self.log("send_timeout", op="obs", err=str(e))
            return None
        for _ in range(12):
            if not obs or obs.get("mode") != "dialog":
                return self._note(obs)
            obs = self._send_safe("wait", frames=6)
        return self._note(obs)

    MACRO_AUTHOR_SYS = """You AUTHOR a macro — an ordered list of ops — to
achieve one Pokemon Red subgoal, then the executor RUNS it. You do NOT pilot
live; you write the whole sequence up front, reading the observation for exact
coordinates. Read:
  obs.map.warps      doors/stairs as {x,y,dest} — use_warp their x,y to exit
  obs.map.objects    interactables as {kind,name,x,y} — interact by name
  obs.map.connections adjacent maps by direction — cross that direction.
    ROUTE: pick the direction whose DEST map leads toward the goal, using the
    ATLAS of edges you have already seen. ONE LEG PER MACRO: your macro may
    contain at most ONE map-changing op (cross, or use_warp through a door)
    and it must be the LAST op — anything after it is DISCARDED, because you
    cannot know coordinates on a map you are not standing in. You will be
    re-prompted with a fresh observation after arriving.
    The warp tile AT OR NEXT TO your position is the door you came IN by —
    use_warp on it goes BACKWARD. To go forward, pick a warp elsewhere on
    the map whose dest leads toward the goal (compare warp dests in
    obs.map.warps), or cross an edge.
Ops: {"op":"walk_to","x":N,"y":N} (within-map), {"op":"cross","dir":"north|
south|east|west"} (to the adjacent map), {"op":"use_warp","x":N,"y":N} (a
door/stairs), {"op":"interact","name":"OBJECT_NAME","answer":"yes"} OR
{"op":"interact","x":N,"y":N,"answer":"yes"} — press A on a TILE rather than
a listed object. Not everything you can press A on is in obs.map.objects:
machines, computers, statues, bookshelves and trash cans are part of the
scenery and are never listed, so a coordinate is the only way to reach one.
If a room's listed objects are exhausted and something in it must still be
operated, press A at the tile it occupies. (answer
accepts a yes/no question the thing asks — taking an item it offers needs
"yes"; with no answer given the question is DECLINED), {"op":"menu","index":N}
(1-based: 1=YES/first, 2=NO/second), {"op":"grind"} (pace this map's wild
grass; each battle is fought and the op repeats until the subgoal's
DONE_WHEN is met, whatever it is — levels, or party size. Wild Pokemon
appear by WALKING in tall grass, never by standing still, so this is the
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
{"op":"wait"}. Battles are auto-handled.

GROUND TRUTH: your real target is DONE_WHEN. The SUBGOAL text is only a hint
and MAY BE IMPERFECT — if it names a target that isn't in obs.map.objects /
obs.map.warps, or even a different STARTING MAP than the observation shows,
IGNORE the hint and use what the observation actually shows. If a previous
macro made partial progress, the state CARRIED FORWARD — author only the
remaining ops from the current observation. Only interact objects/warps that appear
in the current observation. (E.g. receiving a Pokemon usually means
interacting an item/Poke-Ball object, not an NPC.)
Reply with ONLY a JSON array of ops, e.g.
[{"op":"use_warp","x":7,"y":1},{"op":"use_warp","x":2,"y":7}]"""

    @staticmethod
    def _parse_macro(text: str):
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
                    for m in (obs or {}).get("party") or []))

    def _run_traced(self, sg, macro, ignore_done=False):
        """Run a proposed macro step-by-step, returning (done, trace, clean).
        `trace` is plain-English per-op outcomes for feedback (incl. 'ran but
        had NO visible effect'); `clean` is the subset of ops that ran OK —
        what gets DISTILLED, so failed junk ops (e.g. interact 'stairs') the
        model happened to include don't poison the macro and break replay."""
        done = sg.get("done_when")
        trace, clean = [], []
        for step in macro:
            step = dict(step)
            when = step.pop("when", None)
            op = step.pop("op", None)
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
            sig = (self._cur_target, self._where(obs), op,
                   step.get("name") or step.get("dir")
                   or (step.get("x"), step.get("y")))
            if op == "use_warp":
                known = (self.explored.get(self._where(obs), {}) or {}).get(
                    f"{step.get('x')},{step.get('y')}")
                bad = self.dead_for(self._target_key(sg),
                                    (known or {}).get("to", ""))
                if bad and self._dead_visits < 2:
                    self._dead_visits += 1
                    trace.append(
                        f"use_warp({step.get('x')},{step.get('y')}): REFUSED "
                        f"— it leads to {known['to']}, where this goal has "
                        f"already provably failed {bad}x. Take a different "
                        f"exit.")
                    continue
                # ROOM ALREADY ANSWERED. Advice ("the trigger is not here,
                # take an untried exit") loses to the subgoal's own goal
                # prose, which names a place: enter_oaks_lab kept walking
                # back into the lab while its flag actually fires by
                # travelling north out of town, and the run ping-ponged
                # Pallet<->lab until its rounds ran out. Entering the same
                # map a third time in one subgoal, while DONE_WHEN is still
                # false and an untried way out exists, cannot be new
                # information. Yields after 3 refusals so a genuinely
                # single-exit room is never sealed shut.
                dest_map = next(
                    (w.get("dest") for w in
                     ((obs.get("map") or {}).get("warps") or [])
                     if (w.get("x"), w.get("y")) == (step.get("x"),
                                                     step.get("y"))), None)
                tgt = self._cur_target
                # ALREADY-SEARCHED ROOM. The searched ledger was advice only,
                # and advice keeps losing — the run kept dropping back into
                # the same two Mt Moon rooms it had already worked. Refuse
                # the door, but ONLY when nothing unsearched lies beyond it:
                # a finished room is often the corridor to an unfinished one.
                known_dest = (self.explored.get(self._where(obs), {}) or {}).get(
                    f"{step.get('x')},{step.get('y')}")
                dest_region = (known_dest or {}).get("to")
                worked = self.searched.get("*", {})
                contested = self.contested.get(tgt, {})
                if (dest_region and worked.get(dest_region)
                        and not contested.get(dest_region)
                        # A PURCHASE is not a search: the mart reads "fully
                        # worked" from every pass-through, but an item goal
                        # can only ever be satisfied at its counter. Only a
                        # shop proof ("is not sold here", a dead end) may
                        # shut a door against an item target.
                        and not (tgt or "").startswith("item:")
                        # Nor is HEALING. A Pokemon Center is where the
                        # condition is SATISFIED, not where something is
                        # found, and it stays satisfiable however many
                        # times the party has been inside. Sealing that
                        # door left the run walking to the Center and being
                        # turned away at it, round after round, with a
                        # half-dead lead.
                        and not (tgt or "").startswith("party_healthy")
                        and self._revisit_refusals.get(tgt, 0) < 3):
                    unsearched = sorted(
                        r for r in
                        set(list(self.explored) + list(self.visits))
                        if not worked.get(r))
                    # Reaching unsearched ground by walking BACK OUT through
                    # this door is not "beyond" — B2F|23,21 is a one-exit
                    # room, so everything unsearched was nominally reachable
                    # from it and the refusal never fired. Exclude the room
                    # we are standing in from the path.
                    # Check EVERY unsearched region: a sampled subset in set
                    # order dropped Cerulean from the list and this refusal
                    # then sealed the mountain door — the one route to it —
                    # as "nothing unsearched beyond".
                    here_now = self._where(obs)
                    beyond = any(self._route(dest_region, u,
                                             avoid={here_now})
                                 for u in unsearched)
                    if not beyond:
                        self._revisit_refusals[tgt] = \
                            self._revisit_refusals.get(tgt, 0) + 1
                        trace.append(
                            f"use_warp({step.get('x')},{step.get('y')}): "
                            f"REFUSED — {dest_region} has already been fully "
                            f"searched for this goal and nothing unsearched "
                            f"lies beyond it. Going back in cannot find "
                            f"anything. Try somewhere you have not worked.")
                        continue
                seen_n = self._entered_map.get(f"{tgt}|{dest_map}", 0)
                spent_r = self._revisit_refusals.get(tgt, 0)
                # A SERVICE goal is satisfied by GOING BACK. "You have been
                # there twice and it is still false, so it is not there" is
                # sound for finding a thing and exactly backwards for using
                # one: a hurt party heals at the Center it already knows,
                # and a shopping list is filled at the counter it already
                # walked to. Refused re-entry to Pewter, a heal goal toured
                # the museum, then crossed the forest back to Viridian, and
                # the gym leg after it wandered to Route 22.
                if (dest_map and seen_n >= 2 and spent_r < 3
                        and tgt != f"map:{dest_map}"
                        and not (tgt or "").startswith(("party_healthy",
                                                        "item:"))
                        and not self._fought_at(tgt, obs, step, dest_map)
                        and self._untried_exits(obs)):
                    self._revisit_refusals[tgt] = spent_r + 1
                    trace.append(
                        f"use_warp({step.get('x')},{step.get('y')}): REFUSED "
                        f"— you have already been in {dest_map} {seen_n}x "
                        f"chasing this same goal and the condition is still "
                        f"false, so it is not there. Untried ways out of "
                        f"here: {', '.join(self._untried_exits(obs))}. "
                        f"Take one.")
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
                # Talking again to something that did NOTHING last time is
                # pure repetition — the Pewter Jigglypuff sings and changes
                # no state, and the run kept greeting it. This is narrower
                # than "never interact twice": the Pokemon Center nurse
                # changes party HP, so she never lands here.
                _in = self._inert_objs.get(here_r, {})
                if _in.get(step.get("name")) == self._snapshot(obs):
                    trace.append(
                        f"interact({step.get('name')}): REFUSED — you already "
                        f"interacted with it here and NOTHING changed. It has "
                        f"nothing more to give; spend the turn elsewhere.")
                    continue
                tried = self._tried_objs.setdefault(here_r, set())
                objs = [o for o in ((obs.get("map") or {}).get("objects")
                                    or []) if o.get("reachable")]
                names = {o.get("name") for o in objs}
                spent = bool(names) and names.issubset(
                    self._untaken(obs.get("map") or {}, tried))
                # A ROOM YOU LOST A FIGHT IN IS NOT EXHAUSTED. Talking to
                # Brock IS the fight; losing it leaves him talked-to, so
                # "everything reachable is touched" became true and this
                # refusal evicted the run from the one room the badge is in
                # — gym, backtrack, wander to the forest, gym again, on a
                # loop. Same law note_searched already obeys: a fight that
                # beat us is unfinished business, not an emptied room.
                if self.contested.get(self._cur_target, {}).get(here_r):
                    spent = False
                if spent and step.get("name") in tried:
                    # WARN, don't refuse. The refusal was refusing the
                    # WINNING move (same epitaph as the cross guard below):
                    # Bill's script requires talking to him AGAIN in the
                    # same visit that presses the separator, and `tried`
                    # persists across attempts, so a fresh attempt arrived
                    # pre-banned from the one interaction that arms the
                    # machine. Repeat-interact spam costs the model its own
                    # escalation budget, which is its trade to make.
                    # State the fact; do not counsel against the repeat.
                    # "Doing it AGAIN is only worth it if something has
                    # changed... otherwise take an exit you have not used"
                    # is a strategy claim, and in the Vermilion gym it is
                    # the wrong one: the room IS the puzzle, its locks
                    # re-randomise on every miss, and pressing again is the
                    # only way through. 143 presses went in under a note
                    # telling the run to leave.
                    trace.append(
                        f"interact({step.get('name')}): note — everything "
                        f"reachable here ({len(tried)} things) has been "
                        f"pressed at least once already.")
                # NOTE: marked provisionally, and RETRACTED below if the
                # interact did not actually happen. Marking on intent alone
                # let an unreachable item count as touched, so a floor with
                # item balls still on it reported "everything reachable
                # touched" and was recorded as fully searched.
                if step.get("name"):
                    tried.add(step["name"])
            # A seam PROVEN uncrossable is refused, not retried. The trace
            # said so every time and the model kept proposing cross(east)
            # from the Route 4 stub anyway — advice failed, so this is
            # enforcement, and a refused-only round stays free instead of
            # burning budget.
            if False and op == "cross" and step.get("dir") in \
                    self._no_cross.get(self._where(obs), set()):
                # DISABLED — the refusal was refusing the WINNING move.
                # Route 4's one-way ledges make its east segment's
                # reachable-cell fingerprint identical to the west stub's
                # (from the east you can drop down and reach west cells),
                # so a seam proof earned on the west side sealed the cross
                # from the east side, where it succeeds and IS the way to
                # Cerulean. A region id is not a sound key under one-way
                # passability; until fingerprints are direction-aware the
                # cross must always be allowed to run — the shim's seam
                # search fails fast where it genuinely cannot work.
                here_r = self._where(obs)
                doors = []
                for region, exits in self.frontier.items():
                    if region == here_r:
                        continue
                    done_x = set((self.explored.get(region) or {}).keys())
                    left = [e for e in exits if e not in done_x]
                    if not left:
                        continue
                    path = self._route(here_r, region)
                    if path:
                        doors.append((len(path), region, left, path[0]))
                doors.sort(key=lambda d: d[0])
                extra = ""
                if doors:
                    parts = []
                    for n, region, left, (fk, fd) in doors[:3]:
                        leg = (f"walk {fk}" if not fk[0].isdigit()
                               else f"door ({fk})")
                        parts.append(f"{region} (unopened: "
                                     f"{', '.join(sorted(left))}; {n} "
                                     f"leg(s), first {leg} to {fd})")
                    extra = (" The only ways that can still open new "
                             "ground: " + "; ".join(parts) + ". Proposing "
                             "this cross again changes nothing — pick one "
                             "of those.")
                trace.append(
                    f"cross({step.get('dir')}): REFUSED — that seam is "
                    f"PROVEN uncrossable from this area (terrain blocks "
                    f"every cell of the edge). It will never work from "
                    f"here; the way onward is somewhere else." + extra)
                continue
            # NO IMMEDIATE REVERSAL — the classic search prune, not game
            # knowledge: both directions of a ladder read as "untried" from
            # their own side, so the run oscillated B1F<->B2F until its
            # rounds ran out. Yields after 2 refusals so a true dead end can
            # still be backed out of.
            back = False
            if op == "use_warp" and self._arrived \
                    and self._where(obs) == self._arrived[0]:
                back = (step.get("x"), step.get("y")) == self._arrived[1]
                if not back:
                    # doorways come in TWIN tiles leading to the same place
                    # (gates, building fronts). The obs already states each
                    # warp's destination MAP, so we do not need to have
                    # walked the twin first — checking only the learned
                    # graph let a first-time twin through, which is how the
                    # run kept re-entering Viridian Forest from its north
                    # gate instead of stepping out to Route 2.
                    dest_map = None
                    for w in ((obs.get("map") or {}).get("warps") or []):
                        if (w.get("x"), w.get("y")) == (step.get("x"),
                                                        step.get("y")):
                            dest_map = w.get("dest")
                            break
                    prev_map = (self._came_from or "").split("|")[0]
                    back = bool(dest_map and prev_map
                                and dest_map == prev_map)
                    # ...but "same MAP" only means "same PLACE" on a map
                    # with one region. Mt Moon B1F has four, and its
                    # north-east pocket — the one holding the mountain's
                    # east exit — is reachable ONLY by a B2F ladder whose
                    # destMap is, of course, MT_MOON_B1F. Every time the
                    # model proposed it this guard called it the door it
                    # had just come through and refused the one move that
                    # leads onward. Where the map is known to have several
                    # regions, only the learned graph (below) may conclude
                    # a reversal.
                    if back and dest_map:
                        regions = {r for r in
                                   set(list(self.explored) + list(self.visits))
                                   if r.split("|")[0] == dest_map}
                        if len(regions) > 1:
                            back = False
                    if not back:
                        known = (self.explored.get(self._where(obs), {})
                                 or {}).get(f"{step.get('x')},{step.get('y')}")
                        back = bool(known and self._came_from
                                    and known.get("to") == self._came_from)
            if back and self._reversals < 2:
                self._reversals += 1
                trace.append(
                    f"use_warp({step.get('x')},{step.get('y')}): REFUSED — "
                    "that is the door you just came in through; taking it "
                    "returns you where you were a moment ago. Use a "
                    "different exit.")
                continue
            if self._dead_ops.get(sig, 0) >= 3:
                trace.append(f"{op}: REFUSED — this exact action has already "
                             "failed 3 times in this subgoal; it cannot work "
                             "from here, do something different")
                continue
            pre_obs = obs
            before = self._snapshot(obs)
            traversal = op in ("cross", "walk_to", "use_warp", "grind")
            blackout = None
            for _ in range(12):
                try:
                    obs = self.b.send(op, **step)
                except TimeoutError:
                    obs = self.b.obs()
                    break
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
                        self._tried_objs.get(self._where(pre_obs),
                                             set()).discard(step["name"])
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
                if healed and after[6] > before[6]:
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
            if said and said != self._last_said:
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
                # ATTRIBUTE ONLY WHAT THIS OP PRODUCED. last_text outlives
                # the box that printed it, so an op that said nothing of
                # its own inherits the previous line — and a warp out of
                # the gym duly reported "Nope, there's only trash here."
                # The ledger has always had this smear; putting the words
                # in the round's own feedback would have made the run act
                # on it. Only text that CHANGED across this op is its own.
                heard = said if self._said_ready and said != (
                    ((pre_obs or {}).get("last_text") or "").strip()) else ""
                if said and "None" not in reg and len(said) > 12:
                    lst = self.hints.setdefault(reg, [])
                    line = f"{who}: {said[:220]}"
                    if line not in lst:
                        lst.append(line)
                        del lst[:-8]
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
            if ("asked a QUESTION" in str(r.get("detail") or "")
                    and op == "interact" and step.get("name")):
                self._tried_objs.get(self._where(pre_obs),
                                     set()).discard(step["name"])
            if not r.get("ok"):
                self._dead_ops[sig] = self._dead_ops.get(sig, 0) + 1
                note += f": FAILED — {r.get('detail')}"
                # An interact that never happened leaves the thing UNTOUCHED.
                # Without this the provisional mark stands, and a room whose
                # items could not be reached this time counts as fully
                # worked — a false searched proof that stops the run ever
                # coming back for them.
                if op == "interact" and step.get("name"):
                    self._tried_objs.get(self._where(obs),
                                         set()).discard(step["name"])
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
                if "cannot afford" in det and step.get("item"):
                    import re as _re
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
                            if o.get("reachable") and o.get("kind") != "item"
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
                    if d0:
                        self._no_cross.setdefault(here0, set()).add(d0)
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
                    seen_in = [reg for reg, objs in self.sightings.items()
                               if name in objs and reg != here_now]
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
                if "asked a QUESTION" in det0:
                    note += f": {det0}"
                else:
                    note += ": ran but had NO visible effect (nothing changed)"
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
            if blackout:
                note += (f" — your party FAINTED mid-op (blackout): you "
                         f"respawned at {blackout}, party healed, position "
                         f"progress lost")
            if r.get("ok") and before[0] != after[0] and not blackout:
                self.note_transition(pre_obs, step, obs)
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
            if heard:
                note += f' — it said: "{heard[:160]}"'
            trace.append(note)
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
            rounds = max(1, rounds - prior_fails)
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
        spent, rnd = 0, 0
        redo_from = self._pos(self.settle()) if redo else None
        pardon = False        # one free revisit after a blackout (recovery)
        visits: dict = {}     # round-end maps: re-entering one = circling
        while spent < rounds and rnd < rounds * 3:
            rnd += 1
            start = self.settle()
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
                    self.log("escalate_success", subgoal=sg["id"],
                             round=rnd, proposed=0,
                             distilled=len(progress), verified=False)
                    return True, progress
            sig0 = self._snapshot(start)
            if rnd == 1 and sig0[0]:
                visits[sig0[0]] = 1
            obs = model_view(start)
            atlas = self._atlas_text()
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
            memory = self.exploration_text(start, self._target_key(sg))
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
                     target=self._target_key(sg), memory=memory[:1200])
            user = (f"SUBGOAL: {goal}\nDONE_WHEN: {json.dumps(done)}"
                    f"{redo_note}\n{memory}\n"
                    f"ATLAS (map edges and doors you have observed so far): "
                    f"{atlas or 'nothing yet'}\n"
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
                self.log("escalate_chat_error", subgoal=sg["id"], err=str(e))
                break
            macro = self._parse_macro(reply)
            if not macro:
                self.log("escalate_bad_proposal", subgoal=sg["id"], round=rnd,
                         reply=reply[:600])
                feedback = "Your last reply was not a JSON op array. Return " \
                           "ONLY a JSON array of op objects."
                spent += 1
                continue
            # ONE LEG PER MACRO, enforced: ops after the first map-changing op
            # target a map the model has never seen — always hallucinated.
            cut = next((i for i, s in enumerate(macro)
                        if s.get("op") in ("cross", "use_warp")), None)
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
                     macro=macro)
            self.status(subgoal=sg["id"], goal_text=goal, done_when=done,
                        obs=self.settle(),
                        phase=("REDO " if redo else "") + f"escalation {rnd}",
                        doing=json.dumps(macro)[:150])
            ok, trace, clean = self._run_traced(sg, macro,
                                                ignore_done=redo)
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
                live = [o.get("name") for o in
                        ((cur.get("map") or {}).get("objects") or [])
                        if (o.get("reachable") or o.get("kind") == "item")
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
                        moved = self._route_to_frontier(cur, sg, patient=True)
                        if moved:
                            cur = self.settle() or cur
                            trace.append(
                                f"Nothing here serves this goal and no exit "
                                f"is unopened, so you were walked to {moved}, "
                                f"which still has doors never taken. Take one.")
                            continue
                        print(f"   (target unreachable from {here} — "
                              f"abandoning this area)")
                        break
                    print(f"   (target unreachable from {here} — "
                          f"{len(ways)} untried exit(s) left, keeping on)")
                    trace.append(
                        f"PROVEN: what this goal needs is NOT in {here}. "
                        f"But {len(ways)} way(s) out of here have never been "
                        f"taken: {', '.join(ways)}. Take one — do not give "
                        f"up and do not re-search this area.")
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
            # TRAINING A FAINTED POKEMON IS NOT TRAINING. It cannot be sent
            # out, so it earns nothing and the lead soaks every battle while
            # the condition never moves. The party screen says so; say it
            # here too, before the round is spent.
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
            refused_only = bool(trace) and all("REFUSED" in t for t in trace)
            if refused_only and free_rounds < 3:
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
                done_x = set((self.explored.get(here_r) or {}).keys())
                untried = [e for e in (self.frontier.get(here_r) or [])
                           if e not in done_x]
                if (not retalked_now and untried
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
                        scored = sorted(
                            (self._goal_score(redges[e], want_m, blocked), e)
                            for e in sorted(untried) if redges.get(e))
                        # A known exit still wins outright when it IS the
                        # door to the target; short of that, an unopened
                        # door beats another lap through walked ground.
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
                    if "," in key:
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
                    if o2 and (pre.get("map") or {}).get("id") != \
                            (o2.get("map") or {}).get("id"):
                        self.note_transition(pre, step, o2)
                    self.log("free_round_exit", subgoal=sg["id"],
                             via=key, to=self._where(o2))
                    trace.append(
                        f"(every proposal was refused, so the free round "
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
                    loop_note = (
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
                        touched.add(name)
                        cur = o2 or cur
                        if pred_holds(done, cur):
                            break
                    trace.append(
                        f"(swept this area: pressed A on "
                        f"{', '.join(loose[:8])} — everything reachable "
                        f"here has now been tried)")
                    if pred_holds(done, self.settle() or cur):
                        self.log("escalate_success", subgoal=sg["id"],
                                 round=rnd, proposed=0,
                                 distilled=len(progress), verified=False)
                        return True, progress
            moved_itself = bool(progress)
            if not moved_itself and (patient
                                     or not self._untried_exits(cur)):
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
                        + self._logged_exploration(cur, sg)
                        + (("\nWarps you can currently WALK TO from here: "
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
                               f"{d}->{m}"
                               + (" (PROVEN uncrossable from THIS part of "
                                  "the map — the connection exists on the "
                                  "far side of a barrier)"
                                  if d in self._no_cross.get(
                                      self._where(cur), set()) else "")
                               for d, m in conns.items())
                           if conns else "")
                        + (f"\nObjects here you can interact: {objs}" if objs
                           else "")
                        + (f"\nThese targets did NOTHING — do NOT repeat them, "
                           f"pick a DIFFERENT one: {inert}" if inert else "")
                        + (f"\nThese ops moved you BACKWARD to already-"
                           f"visited maps — never use them again this "
                           f"subgoal: {backward}" if backward else ""))
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

    def distill(self, sg: dict, ops: list):
        """Write the escalation's successful op sequence back as the macro,
        with provenance (the claim needs to show the model authored it)."""
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
            self.plan_path.write_text(json.dumps(self.plan, indent=2))
        self.log("distilled", subgoal=sg["id"], n_ops=len(ops))

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
                    self.log("step", subgoal=sg["id"], op=op, params=step,
                             ok=r.get("ok"), detail=r.get("detail"),
                             map=(obs.get("map") or {}).get("id")
                             if obs else None,
                             # WHERE it stood, not just which map: a cross
                             # that fails "seam unreachable" is a claim
                             # about the TILE, and pinning down whether the
                             # party was on the east or west half of Route 4
                             # cannot be done from the map id alone
                             at=(f"{(obs or {}).get('x')},{(obs or {}).get('y')}"
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
                    break
            if pred_holds(done, self.settle()):
                self.log("subgoal_done", subgoal=sg["id"], attempt=attempt,
                         via="post-macro")
                return True
        self.log("subgoal_failed", subgoal=sg["id"])
        return False

    def _attempt(self, sg) -> bool:
        """Replay the macro; escalate if that fails."""
        try:
            ok = self.run_subgoal(sg) if sg.get("macro") else False
        except TimeoutError as e:
            self.log("subgoal_timeout", subgoal=sg["id"], err=str(e))
            ok = False
        if not ok and self.can_escalate:
            print(f"   -> escalating {sg['id']} to the model")
            self.escalations += 1
            try:
                success, ops = self.escalate(sg)
            except TimeoutError as e:
                self.log("escalate_timeout", subgoal=sg["id"], err=str(e))
                success, ops = False, []
            if success:
                self.distill(sg, ops)
                ok = True
                print(f"   distilled {sg['id']} ({len(ops)} ops)")
        return ok

    def run_plan(self, plan: dict) -> bool:
        self.log("plan_start", goal=plan.get("goal"), escalate=self.can_escalate)
        fails = 0
        backtracks = 0
        subgoals = plan["subgoals"]
        # WAYPOINTS ALREADY WALKED THIS CAMPAIGN STAY WALKED. A resumed
        # journey-plan re-litigated go_to_cerulean_city from its first
        # line and marched the party from the captain's doorstep back
        # north. A subgoal id completed under this goal in an earlier
        # attempt is honored — except the final one, which is the leg's
        # objective and must hold NOW.
        goal_key = str(plan.get("goal") or "")
        if not hasattr(self, "_plan_done"):
            self._plan_done = {}
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
                print(f"== subgoal: {sg['id']} (holds from where the "
                      f"party stands — honored)")
                self.log("subgoal_prior_done", subgoal=sg["id"])
                continue
            has_macro = bool(sg.get("macro"))
            print(f"== subgoal: {sg['id']}" + ("" if has_macro else " (no macro)"))
            ok = self._attempt(sg)
            if ok:
                self._plan_done.setdefault(goal_key, [])
                if sg["id"] not in self._plan_done[goal_key]:
                    self._plan_done[goal_key].append(sg["id"])
                    self._save_memory()
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
                print(f"   <- backtracking: redoing {prev['id']} "
                      f"(it may have finished in the wrong place)")
                self.log("backtrack", failed=sg["id"], redoing=prev["id"])
                try:
                    moved, ops = self.escalate(
                        prev, redo=True, avoid_region=stuck_region,
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
                                prev, redo=True, avoid_region=stuck_region,
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
        # a finished leg's sticky waypoints must not leak into a future
        # campaign that happens to reuse the goal wording
        self._plan_done.pop(goal_key, None)
        self._save_memory()
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
            "party": [{"species": m.get("species"), "level": m.get("level"),
                       "hp": m.get("hp"), "max_hp": m.get("max_hp"),
                       "status": m.get("status")}
                      for m in (o.get("party") or [])],
            "badges": o.get("badges") or [],
            "bag": o.get("bag") or {},
            "money": o.get("money"),
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
    SCORE_BATTLES = args.score_battles
    VERIFY_MACROS = args.verify_macros
    b = Bridge()
    if args.bootstrap:
        bootstrap(b, cont=args.cont)
    ex = Executor(b, max_battle_turns=args.max_battle_turns,
                  can_escalate=args.escalate, model=args.model,
                  run_id=args.run_id)
    ex.save_each = args.save_after_each
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
    print(f"\nRESULT: {'ALL PLANS COMPLETE' if ok else 'PLAN FAILED'} | "
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
