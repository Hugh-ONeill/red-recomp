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
        elif key == "has_item":
            bag = obs.get("bag") or {}
            for item, n in (want or {}).items():
                if not bag or bag.get(item, 0) < n:
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
    ctx = {"turn": 0, "used": {}, "intent": intent,
           "journal": DAMAGE_JOURNAL}
    while obs and obs.get("mode") == "battle" and turns < max_turns:
        turns += 1
        ctx["turn"] = turns
        if (flees < 3 and battle_policy.should_flee(obs, spec, ctx)):
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
        # ATLAS: map edges observed so far this run ({map_id: {dir: dest}}).
        # Pure memory of past observations (the obs already showed each map's
        # connections while standing on it), re-served to the model so multi-
        # leg routing uses seen geography instead of its shaky world prior
        # (brock9: it kept hunting for Pallet WEST of Viridian, on ROUTE_22).
        self.atlas: dict = {}
        self.logf = open(RUN / "executor_log.jsonl", "a")
        self.t0 = time.time()

    def _note(self, obs):
        m = (obs or {}).get("map") or {}
        if m.get("id") and (m.get("connections") or m.get("warps")):
            e = self.atlas.setdefault(m["id"], {})
            if m.get("connections"):
                e["edges"] = m["connections"]
            if m.get("warps"):
                e["warps"] = [{"x": w.get("x"), "y": w.get("y"),
                               "dest": w.get("dest")} for w in m["warps"]]
        return obs

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

    def log(self, kind, **kw):
        self.logf.write(json.dumps(
            {"dt": round(time.time() - self.t0, 1), "kind": kind, **kw}) + "\n")
        self.logf.flush()

    def handle_battle(self, subgoal: dict, obs: dict) -> dict:
        name = subgoal.get("battle_policy", "default")
        self.log("battle_start", subgoal=subgoal["id"], policy=name)
        obs = BATTLE_POLICIES[name](self.b, obs, self.log,
                                    self.max_battle_turns)
        # spec-rule field cure/heal after the battle (no turn cost): the
        # model's rules decide when an item beats walking on. Cure first —
        # poison keeps chipping until it is.
        item = battle_policy.should_field_cure(obs, ACTIVE_SPEC)
        if item:
            self.log("field_cure", subgoal=subgoal["id"], item=item)
            obs = self._send_safe("use_item", item=item) or obs
        item = battle_policy.should_field_heal(obs, ACTIVE_SPEC)
        if item:
            self.log("field_heal", subgoal=subgoal["id"], item=item)
            obs = self._send_safe("use_item", item=item) or obs
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
grass; each battle is fought and the op repeats until the subgoal's level
target is met — use when the goal is to TRAIN/level up),
{"op":"buy","item":"POTION","count":N} (buy from THIS map's mart clerk —
it talks to the clerk ITSELF, no interact needed first; obs.money is your
budget), {"op":"use_item","item":"POTION"} (use a bag item on your lead in
the field), {"op":"wait"}. Battles are auto-handled.

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
                len((obs or {}).get("flags") or []))

    def _run_traced(self, sg, macro):
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
            if pred_holds(done, obs):
                return True, trace, clean
            if when and not pred_holds(when, obs):
                # honor when-guards on replay (verify runs the same guarded
                # macro run_subgoal will): a misplaced op skips, not misfires
                trace.append(f"{op}: skipped (when-guard)")
                continue
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
                    obs = self.handle_battle(sg, obs)
                    obs = self.settle()
                    post_map = ((obs or {}).get("map") or {}).get("id")
                    # a won battle never changes the map; a party wipe blacks
                    # out and respawns at home/last Center — silently warping
                    # the trajectory (brock15 died in the forest and the next
                    # rounds unknowingly ran from Pallet)
                    if post_map and pre_map and post_map != pre_map:
                        blackout = post_map
                        self.log("blackout", subgoal=sg["id"], op=op,
                                 respawn=post_map)
                        break
                    if traversal and not pred_holds(done, obs):
                        continue
                break
            r = (obs or {}).get("result") or {}
            after = self._snapshot(obs)
            note = f"{op}({','.join(f'{k}={v}' for k, v in step.items())})"
            if not r.get("ok"):
                note += f": FAILED — {r.get('detail')}"
            elif before == after:
                note += ": ran but had NO visible effect (nothing changed)"
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
            trace.append(note)
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
            if pred_holds(done, self.settle()):
                return True, trace, clean
        return pred_holds(done, self.settle()), trace, clean

    def escalate(self, sg: dict) -> tuple[bool, list]:
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
        feedback = "This is the first attempt."
        inert = []          # targets that ran but did nothing / failed
        backward = []       # ops that moved us to an already-visited map
        progress = []       # clean ops accumulated across rounds
        self.log("escalate_start", subgoal=sg["id"], goal=goal)
        cap = self._send_safe("checkpoint_capture", token="esc") or {}
        can_reset = bool((cap.get("result") or {}).get("ok"))
        self.log("escalate_checkpoint", subgoal=sg["id"], captured=can_reset)
        # A round that CHANGED something (map/party/flags) is progress and
        # does not spend budget — multi-leg subgoals need one leg per round.
        # The absolute cap bounds oscillation (A<->B crossings are each "a
        # map change" yet go nowhere).
        spent, rnd = 0, 0
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
            user = (f"SUBGOAL: {goal}\nDONE_WHEN: {json.dumps(done)}\n"
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
            ok, trace, clean = self._run_traced(sg, macro)
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
                if can_reset:
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
            sig1 = self._snapshot(cur)
            loop_note = ""
            had_blackout = any("blackout" in t for t in trace)
            if (sig1[0], sig1[4], sig1[5]) == (sig0[0], sig0[4], sig0[5]):
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
                        + loop_note
                        + open_prompt
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
            self.log("escalate_feedback", subgoal=sg["id"], round=rnd,
                     spent=spent, trace=trace, inert=inert,
                     progress_ops=len(progress))
        self.log("escalate_end", subgoal=sg["id"], success=False)
        return False, sg.get("macro", [])

    def distill(self, sg: dict, ops: list):
        """Write the escalation's successful op sequence back as the macro,
        with provenance (the claim needs to show the model authored it)."""
        sg["macro"] = ops
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

    def run_plan(self, plan: dict) -> bool:
        self.log("plan_start", goal=plan.get("goal"), escalate=self.can_escalate)
        for sg in plan["subgoals"]:
            has_macro = bool(sg.get("macro"))
            print(f"== subgoal: {sg['id']}" + ("" if has_macro else " (no macro)"))
            try:
                ok = self.run_subgoal(sg) if has_macro else False
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
            if not ok:
                print(f"!! FAILED: subgoal {sg['id']}")
                self.log("plan_failed_at", subgoal=sg["id"])
                return False
            print(f"   done: {sg['id']}")
        self.log("plan_complete", goal=plan.get("goal"),
                 escalations=self.escalations)
        return True


def bootstrap(b: Bridge):
    print("[bootstrap] new_game (decision-free ceremony skip)")
    b.send("new_game")
    for _ in range(8):
        if b.send("mash_a", times=30)["mode"] == "overworld":
            return
    raise RuntimeError("bootstrap failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--max-battle-turns", type=int, default=40)
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

    global SCORE_BATTLES
    SCORE_BATTLES = args.score_battles
    plan = json.loads(args.plan.read_text())
    b = Bridge()
    if args.bootstrap:
        bootstrap(b)
    ex = Executor(b, max_battle_turns=args.max_battle_turns,
                  can_escalate=args.escalate, model=args.model,
                  plan=plan, plan_path=args.plan, run_id=args.run_id)
    ok = ex.run_plan(plan)
    o = b.obs() or {}
    print(f"\nRESULT: {'PLAN COMPLETE' if ok else 'PLAN FAILED'} | "
          f"map={(o.get('map') or {}).get('id')} "
          f"party={[(m.get('species'), m.get('level')) for m in o.get('party') or []]} "
          f"badges={o.get('badges')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
