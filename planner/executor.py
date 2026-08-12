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


def pred_holds(pred: dict | None, obs: dict) -> bool:
    if not pred:
        return True
    if not obs:
        return False
    for key, want in pred.items():
        if key == "map":
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
        log("battle_turn", turn=turns, op=name, params=op, why=why)
        before_b = (obs or {}).get("battle") or {}
        move_id = None
        if name == "battle_move":
            mv = next((m for m in ((before_b.get("me") or {}).get("moves")
                                   or []) if m.get("index") == idx), None)
            move_id = (mv or {}).get("id")
        obs = bridge.send(name, **op)
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
        self.searched: dict = {}    # target -> {region: fully worked}
        self.contested: dict = {}   # target -> {region: a fight ran here}
        self._arrived = None        # (region, (x,y)) — the door we came in by
        self._came_from = None      # the region we were in a moment ago
        self._reversals = 0
        self._dead_visits = 0
        self._entered_map: dict = {}   # "target|map" -> entries for target
        self._revisit_refusals: dict = {}   # target -> refusals spent
        self._battle_regions: set = set()   # "target|region" a fight ran in
        self._blackouts: dict = {}          # target -> party wipes
        self._faint_at = None               # region we were in when wiped
        self._ui_pending = 0                # rounds a prompt has sat open
        self._dead_ops: dict = {}           # (target, op, arg) -> failures
        self.save_each = False              # in-game SAVE after each subgoal
        self._tried_objs: dict = {}         # region -> objects interacted
        self._inert_objs: dict = {}         # region -> {object: state it was inert in}
        self._cant_afford: dict = {}        # item -> unit price we lack
        self._no_cross: dict = {}           # region -> dirs proven uncrossable
        self._cur_target = ""
        self._load_memory()
        # ATLAS: map edges observed so far this run ({map_id: {dir: dest}}).
        # Pure memory of past observations (the obs already showed each map's
        # connections while standing on it), re-served to the model so multi-
        # leg routing uses seen geography instead of its shaky world prior
        # (brock9: it kept hunting for Pallet WEST of Viridian, on ROUTE_22).
        self.atlas: dict = {}
        self.logf = open(RUN / "executor_log.jsonl", "a")
        self.t0 = time.time()

    def _note(self, obs):
        self.note_frontier(obs)
        self.note_sightings(obs)
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
            anyd0 = self.searched.get("*", {})
            for tgt in [t for t in self.searched if t.startswith("item:")]:
                for r in self.searched.pop(tgt, {}):
                    anyd0.pop(r, None)
            # every entry was recorded under the fully-worked condition, so
            # the union of all targets IS the set of worked rooms
            anyd = self.searched.setdefault("*", {})
            for tgt, rooms in list(self.searched.items()):
                if tgt != "*":
                    for r in rooms:
                        anyd[r] = True
            self._tried_objs = {r: set(v) for r, v in
                                (data.get("touched") or {}).items()}
            self._no_cross = {r: set(v) for r, v in
                              (data.get("no_cross") or {}).items()}
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
                              for r, s in self._no_cross.items()}},
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
        by_map: dict = {}
        for region, exits in (self.frontier or {}).items():
            if not exits:
                continue
            by_map.setdefault(region.split("|")[0], []).append(
                (region, set(exits)))
        AREA_ALIASES.clear()
        for regions in by_map.values():
            for i, (ra, ea) in enumerate(regions):
                for rb, eb in regions[i + 1:]:
                    if ea & eb:
                        AREA_ALIASES.setdefault(ra, set()).add(rb)
                        AREA_ALIASES.setdefault(rb, set()).add(ra)

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
        """Every exit visible from where we stand — the inventory that makes
        'all ways out are dead' a justified conclusion rather than a guess."""
        here = self._where(obs)
        if "None" in here:
            return
        m = (obs or {}).get("map") or {}
        keys = [f"{w.get('x')},{w.get('y')}" for w in (m.get("warps") or [])
                if w.get("reachable")]
        keys += list((m.get("connections") or {}).keys())
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

    def note_searched(self, target: str, region: str):
        """This area has been fully worked for that target: every exit taken,
        everything reachable touched. Distinct from a dead end — it stops the
        room being SEARCHED again without stopping the run PASSING through."""
        if not region or "None" in region or not target:
            return
        # Also record it under "*": FULLY WORKED (every exit taken, every
        # reachable object touched) is a fact about the ROOM, not the goal.
        # Keying it only by target fragmented the ledger — B2F's dead-end
        # rooms were marked under the nerd flag, so a later subgoal aiming at
        # map:MT_MOON_B2F saw them as untouched and walked straight back in.
        # A room where a FIGHT ran for this goal is not exhausted — losing
        # to the Mt Moon nerd marked his room worked, and the refusal then
        # blocked the ladder leading back to him. A lost fight is unfinished
        # business, not an emptied room.
        if self.contested.get(target, {}).get(region):
            return
        d = self.searched.setdefault(target, {})
        anyd = self.searched.setdefault("*", {})
        fresh = region not in d or region not in anyd
        d[region] = True
        anyd[region] = True
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
        e = node.setdefault(key, {"n": 0, "to": dst})
        e["n"] += 1
        e["to"] = dst
        self.log("explored", frm=src, via=str(key), to=dst, times=e["n"])
        self._save_memory()

    def _untried_exits(self, obs) -> list:
        """Ways out of here never taken — doors and roads alike. Map edges
        count: a town's road out is the exit an event most often hides on."""
        m = (obs or {}).get("map") or {}
        taken = self.explored.get(self._where(obs), {}) or {}
        seen_maps = {a.split("|")[0] for a in self.visits}
        out = []
        for w in (m.get("warps") or []):
            if not w.get("reachable"):
                continue
            k = f"{w.get('x')},{w.get('y')}"
            if k not in taken:
                out.append((w.get("dest") in seen_maps,
                            f"({k})->{w.get('dest')}"))
        for d, t in (m.get("connections") or {}).items():
            if d not in taken:
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
                self.log("blackout_return_noroute", subgoal=sg.get("id"),
                         frm=here, want=want)
                self._faint_at = None
                return None
            for key, nxt in path:
                if "," in key:
                    x, y = key.split(",")
                    self.b.send("use_warp", x=int(x), y=int(y))
                else:
                    self.b.send("cross", dir=key)
                o = self.settle()
                if o and o.get("mode") == "battle":
                    o = self.handle_battle(sg, o)
                    o = self.settle()
                total += 1
                got = self._where(o)
                if got != nxt and got not in AREA_ALIASES.get(nxt, ()):
                    self.log("blackout_return_replan", subgoal=sg.get("id"),
                             wanted=nxt, got=got, attempt=attempt)
                    break          # re-plan from wherever we actually are
        self.log("blackout_return_lost", subgoal=sg.get("id"),
                 want=want, gave_up_after=total)
        self._faint_at = None
        return None

    def _route_to_frontier(self, obs, sg):
        """Walk back to the NEAREST region that still has exits never taken.

        Knowing where the unopened ladders are is useless if you cannot get
        there: reaching MT_MOON_1F from deep in B2F is several legs and
        escalation authors ONE leg per macro, so the model could never spend
        the knowledge. Navigation over already-walked ground is harness work
        (same as walk_to pathfinding inside a map) — the model still decides
        what to do on arrival."""
        here = self._where(obs)
        cur_map = (obs.get("map") or {}).get("id")
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
        tried_here = self._tried_objs.get(here, set())
        if [o for o in ((obs.get("map") or {}).get("objects") or [])
                if o.get("reachable") and o.get("name") not in tried_here]:
            return None
        best = None
        for region, exits in self.frontier.items():
            if region == here:
                continue
            done_x = set((self.explored.get(region) or {}).keys())
            if not [e for e in exits if e not in done_x]:
                continue
            path = self._route(here, region)
            if path is not None and (best is None or len(path) < len(best[1])):
                best = (region, path)
        if not best or not best[1]:
            return None
        region, path = best
        for key, nxt in path:
            if "," in key:
                x, y = key.split(",")
                self.b.send("use_warp", x=int(x), y=int(y))
            else:
                self.b.send("cross", dir=key)
            o = self.settle()
            if o and o.get("mode") == "battle":
                o = self.handle_battle(sg, o)
                o = self.settle()
            if self._where(o) != nxt:
                self.log("reroute_lost", subgoal=sg["id"], wanted=nxt,
                         got=self._where(o))
                return None
        self.log("rerouted", subgoal=sg["id"], to=region, hops=len(path))
        return region

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
        untried, tried = [], []
        for w in warps:
            if not w.get("reachable"):
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
                    f"have already walked. That area is a SPECIFIC ROOM, not "
                    f"the whole floor; arriving elsewhere on the same floor "
                    f"is not arriving.")
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
        # Rooms already worked for THIS goal: nothing left to find in them,
        # but you may still walk through — that distinction is why they are
        # not dead ends.
        done_rooms = [r for r in (self.searched.get(target) or {})
                      if r != here]
        searched_line = ""
        if self.searched.get(target, {}).get(here):
            searched_line = ("\nYou have ALREADY fully searched this exact "
                             "area for this goal — every exit taken, "
                             "everything touched. Do not search it again; "
                             "pass through or go somewhere new.")
        elif done_rooms:
            searched_line = ("\nAlready fully searched for this goal (walk "
                             "through if you must, but nothing is left in "
                             "them): " + ", ".join(sorted(done_rooms)[:5]) + ".")
        been = self.visits.get(here, 0)
        warned = ""
        if been >= 2:
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
        for region, exits in self.frontier.items():
            if region == here:
                continue
            done_x = set((self.explored.get(region) or {}).keys())
            left = [e for e in exits if e not in done_x]
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
        taken_objs = self._tried_objs.get(here, set())
        loot = [o.get("name") for o in (m.get("objects") or [])
                if o.get("reachable") and o.get("name")
                and o.get("name") not in taken_objs]
        loot_line = ""
        if loot:
            loot_line = (f"\nTHINGS within reach here you have NOT touched "
                         f"yet: {', '.join(loot[:6])}. Press A on them before "
                         f"you leave — it is free, and a thing sitting in a "
                         f"passage can be exactly what is blocking it, so "
                         f"interacting with it may open the way.")
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
        if not (untried or tried):
            if elsewhere:
                return (warned + route_line
                        + "\nNothing here is new, but these places "
                        "you have already been still have ways you have "
                        "NEVER taken: " + "; ".join(sorted(elsewhere)[:6])
                        + ". Go back to one and take it." + near_hint
                        + loot_line)
            return warned + route_line + searched_line + loot_line
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
        out += route_line + searched_line + loot_line
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
        self.log("battle_start", subgoal=subgoal["id"], policy=name)
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
door/stairs), {"op":"interact","name":"OBJECT_NAME"}, {"op":"menu","index":N}
(1-based: 1=YES/first, 2=NO/second), {"op":"grind"} (pace this map's wild
grass; each battle is fought and the op repeats until the subgoal's
DONE_WHEN is met, whatever it is — levels, or party size. Wild Pokemon
appear by WALKING in tall grass, never by standing still, so this is the
op for TRAINING *and* for finding something to CATCH; {"op":"wait"} will
never produce an encounter),
{"op":"buy","item":"POTION","count":N} (own N total of the item, buying
the difference from THIS map's mart clerk — it talks to the clerk ITSELF,
no interact needed first; obs.money is your budget),
{"op":"use_item","item":"POTION"} (use a bag item on your lead in the
field), {"op":"wait"}. Battles are auto-handled.

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
            sig = (self._cur_target, op,
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
                        and self._revisit_refusals.get(tgt, 0) < 3):
                    unsearched = [r for r in
                                  set(list(self.explored) + list(self.visits))
                                  if not worked.get(r)]
                    # Reaching unsearched ground by walking BACK OUT through
                    # this door is not "beyond" — B2F|23,21 is a one-exit
                    # room, so everything unsearched was nominally reachable
                    # from it and the refusal never fired. Exclude the room
                    # we are standing in from the path.
                    here_now = self._where(obs)
                    beyond = any(self._route(dest_region, u,
                                             avoid={here_now})
                                 for u in unsearched[:12])
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
                if (dest_map and seen_n >= 2 and spent_r < 3
                        and tgt != f"map:{dest_map}"
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
                spent = bool(names) and names.issubset(tried)
                if spent and step.get("name") in tried:
                    trace.append(
                        f"interact({step.get('name')}): REFUSED — you have "
                        f"already interacted with everything reachable in "
                        f"this area ({len(tried)} things) and the condition "
                        f"is still false. It is not in this room. LEAVE: "
                        f"take an exit you have not used.")
                    continue
                if step.get("name"):
                    tried.add(step["name"])
            # A seam PROVEN uncrossable is refused, not retried. The trace
            # said so every time and the model kept proposing cross(east)
            # from the Route 4 stub anyway — advice failed, so this is
            # enforcement, and a refused-only round stays free instead of
            # burning budget.
            if op == "cross" and step.get("dir") in \
                    self._no_cross.get(self._where(obs), set()):
                trace.append(
                    f"cross({step.get('dir')}): REFUSED — that seam is "
                    f"PROVEN uncrossable from this area (terrain blocks "
                    f"every cell of the edge). It will never work from "
                    f"here; the way onward is somewhere else.")
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
                    if self._cur_target and pre_map:
                        self._battle_regions.add(
                            f"{self._cur_target}|{self._where(pre_obs)}")
                        if self._cur_target:
                            reg = self._where(pre_obs)
                            c = self.contested.setdefault(self._cur_target, {})
                            if reg and "None" not in reg and not c.get(reg):
                                c[reg] = True
                                self.searched.get(self._cur_target, {}).pop(reg, None)
                                self.searched.get("*", {}).pop(reg, None)
                                self._save_memory()
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
            # faint marker and the walk-back never armed (user: "party wipe
            # in mt moon returned us to viridian pokecenter then its stuck").
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
                    self.log("blackout", subgoal=sg["id"], op=op,
                             respawn=after[0], detected="state")
                    self.log("faint_marked", subgoal=sg["id"],
                             at=self._faint_at)
            note = f"{op}({','.join(f'{k}={v}' for k, v in step.items())})"
            if not r.get("ok"):
                self._dead_ops[sig] = self._dead_ops.get(sig, 0) + 1
                note += f": FAILED — {r.get('detail')}"
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
                note += ": ran but had NO visible effect (nothing changed)"
                if op == "interact" and step.get("name"):
                    # remember WHICH state it was useless in; if the world
                    # changes (hp drops, a flag fires) it is worth another go
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
        # An EVENT GATE is load-bearing: failing it now ENDS the plan (a
        # missed event cannot be walked past), so giving it the same budget
        # as a trivial map hop meant whole attempts died in ~60s on the one
        # subgoal that actually needed searching. Gates get a deeper budget.
        _dw = sg.get("done_when") or {}
        if "flag" in _dw or "badge" in _dw:
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
            # reconsidering them (user: "they're not getting labelled")
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
                live = [o.get("name") for o in
                        ((cur.get("map") or {}).get("objects") or [])
                        if o.get("reachable") and o.get("name") not in _tried]
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
                          or (not self._untried_exits(cur) and not live)):
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
                if not self._untried_exits(cur) and not live:
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
                    first_key, first_dest = routed[0]
                    leg = (f"walk {first_key}" if not first_key[0].isdigit()
                           else f"the door at ({first_key})")
                    trace.append(
                        f"Nothing in THIS room serves the goal — but the "
                        f"goal is to GET SOMEWHERE, and the walked route "
                        f"still exists: take {leg} to {first_dest} "
                        f"({len(routed)} leg(s) to go). Keep moving; do "
                        f"not search this room.")
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
            if self._faint_at and cur.get("mode") == "overworld":
                back = self._return_from_blackout(cur, sg)
                if back:
                    cur = self.settle() or cur
                    stuck_note += (f"\nYour party fainted and you were sent "
                                   f"back to a Pokemon Center. You have been "
                                   f"walked back to {back}, where you were. "
                                   f"You are HEALED — but whatever beat you "
                                   f"is still there, so do not simply repeat "
                                   f"what you just did.")
            sig1 = self._snapshot(cur)
            here_now = self._where(cur)
            self._stuck_in[here_now] = self._stuck_in.get(here_now, 0) + 1
            stuck_note = ""
            if self._blackouts.get(self._target_key(sg), 0) >= 2:
                # Being LOST and being TOO WEAK fail the same way from the
                # executor's side (condition still false), but the remedies
                # are opposite: one says leave, the other says come back
                # stronger. Naming which one this is lets the model author
                # the fix instead of re-entering the same fight unchanged.
                stuck_note = (
                    f"\nYour party has been WIPED OUT "
                    f"{self._blackouts[self._target_key(sg)]}x pursuing this "
                    f"goal. You are not lost — you are TOO WEAK to win this "
                    f"fight as you are. Do not walk back in unchanged. Get "
                    f"stronger first: grind levels, add another Pokemon to "
                    f"the party so one faint does not end the fight, buy and "
                    f"use healing items, or all three. Note that each "
                    f"blackout also costs you half your money.")
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
            if not self._untried_exits(cur):
                went = self._route_to_frontier(cur, sg)
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
                              "reachable warp and come back another way.")
                           if (cur.get("map") or {}).get("warps") else "")
                        + (f"\nEdges from this map (cross that dir to reach): "
                           + ", ".join(f"{d}->{m}" for d, m in conns.items())
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
                             mode=obs.get("mode") if obs else None)
                    if obs and obs.get("mode") == "battle":
                        obs = self.handle_battle(sg, obs)
                        obs = self.settle()
                        if traversal and not pred_holds(done, obs):
                            continue     # battle interrupted travel: resume
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
        for idx, sg in enumerate(subgoals):
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
                # room over (user: "instead of backtracking from B2F it
                # spawns a new version and restarts").
                # And look PAST satisfied gates: with defeat_super_nerd's
                # flag already set, the candidate scan stopped on it with
                # "already holds" while the relocatable descend_to_b2f sat
                # one step further back — so the stored macro kept replaying
                # the wrong ladder and the waypoint leg kept dying in the
                # wrong room (user: "wrong door").
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
                        done = self.searched.get(self._target_key(sg), {})
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
                fails += 1
                last = sg is plan["subgoals"][-1]
                # An EVENT is a gate, not a step you can walk past. When
                # defeat_mt_moon_nerd failed, the plan carried on and
                # "completed" three subgoals that are satisfied by RETREATING
                # (ascend to B1F, ascend to 1F, exit to Route 4), marching to
                # the end having achieved nothing and only noticing at
                # Cerulean. A missed map hop can be carried; a missed event
                # cannot, because everything after it assumes it happened.
                gate = "flag" in (sg.get("done_when") or {}) or \
                       "badge" in (sg.get("done_when") or {})
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
            # mountain (user: "after a blackout it just wandered around
            # pewter"). Save once the party is back where it fell.
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
    # Mash A to get through the title/info box, but CHECK AFTER SETTLING and
    # back out of anything A opened by accident. A save inside a Pokemon
    # Center resumes standing at the nurse, so a blind 30-press burst talks
    # to her (the log even shows "saved game") and the mode at check time is
    # dialog, never overworld — every --continue attempt died here with
    # "bootstrap failed" before playing a single step.
    for i in range(12):
        o = b.send("mash_a", times=6) or {}
        mode = o.get("mode")
        if mode == "overworld":
            return
        if mode in ("ui", "dialog") and i >= 3:
            b.send("tap", btn="b")          # close what A opened
        o = b.obs() or {}
        if o.get("mode") == "overworld":
            return
    raise RuntimeError(
        f"bootstrap failed (stuck in mode={(b.obs() or {}).get('mode')})")


def _write_last_state(b):
    """Snapshot where the run stands, for the campaign's re-author.

    Called on the normal exit path AND from the crash handler: a snapshot
    that is missing is worse than useless, because the loop then reads a
    PREVIOUS campaign's file and plans against a game that no longer exists.
    """
    try:
        o = b.obs() or {}
        (RUN / "last_state.json").write_text(json.dumps({
            "map": (o.get("map") or {}).get("id"),
            "region": (o.get("map") or {}).get("region"),
            "party": [{"species": m.get("species"), "level": m.get("level"),
                       "hp": m.get("hp")} for m in (o.get("party") or [])],
            "badges": o.get("badges") or [],
            "bag": o.get("bag") or {},
            "money": o.get("money"),
            "flags": o.get("flags") or [],
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
    _write_last_state(b)
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
