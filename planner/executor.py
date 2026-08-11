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
        self._dead_ops: dict = {}   # (op,target) -> consecutive failures
        self._st: dict = {}         # live status (run/status.txt)
        # exploration memory: {"MAP|region": {(x,y): {"n": k, "to": "MAP|reg"}}}
        # Without it the run re-takes the same ladder forever (thin8 spent 12
        # redo rounds ping-ponging one warp). This is memory, not reward
        # shaping: it says where you HAVE been, the model still chooses.
        self.explored: dict = {}
        self.dead_ends: dict = {}   # subgoal id -> {region: failures}
        self.visits: dict = {}      # region -> times arrived
        self._arrived = None        # (region, (x,y)) — the door we came in by
        self._reversals = 0
        self._dead_visits = 0
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
            edges = sum(len(v) for v in self.explored.values())
            if edges:
                print(f"[memory] {len(self.explored)} areas, {edges} known "
                      f"exits from previous runs")
        except (OSError, ValueError):
            self.explored, self.dead_ends, self.visits = {}, {}, {}

    def _save_memory(self):
        try:
            self.MEMORY.write_text(json.dumps(
                {"explored": self.explored, "dead_ends": self.dead_ends,
                 "visits": self.visits},
                indent=1))
        except OSError:
            pass

    def note_dead_end(self, sg_id: str, region: str):
        """This area could not achieve that subgoal — remember it."""
        if not region or "None" in region:
            return
        d = self.dead_ends.setdefault(sg_id, {})
        d[region] = d.get(region, 0) + 1
        self.log("dead_end", subgoal=sg_id, region=region, times=d[region])
        self._save_memory()

    @staticmethod
    def _where(obs) -> str:
        m = (obs or {}).get("map") or {}
        return f"{m.get('id')}|{m.get('region')}"

    def note_transition(self, before_obs, step, after_obs):
        """Record: from this area, that exit led there."""
        src, dst = self._where(before_obs), self._where(after_obs)
        if src == dst or "None" in src:
            return
        key = (f"{step.get('x')},{step.get('y')}"
               if step.get("x") is not None else step.get("dir"))
        if key is None:
            return
        self.visits[dst] = self.visits.get(dst, 0) + 1
        ap = (after_obs or {}).get("player") or {}
        if ap.get("x") is not None:
            self._arrived = (dst, (ap["x"], ap["y"]))
            self._reversals = 0
        node = self.explored.setdefault(src, {})
        e = node.setdefault(key, {"n": 0, "to": dst})
        e["n"] += 1
        e["to"] = dst
        self.log("explored", frm=src, via=str(key), to=dst, times=e["n"])
        self._save_memory()

    def exploration_text(self, obs, sg_id: str = "") -> str:
        """Untried vs already-taken exits from where we stand."""
        here = self._where(obs)
        taken = self.explored.get(here, {})
        warps = ((obs or {}).get("map") or {}).get("warps") or []
        untried, tried = [], []
        for w in warps:
            if not w.get("reachable"):
                continue
            k = f"{w.get('x')},{w.get('y')}"
            if k in taken:
                dest = taken[k]["to"]
                bad = (self.dead_ends.get(sg_id, {}) or {}).get(dest, 0)
                tried.append(
                    f"({k}) -> {dest} [taken {taken[k]['n']}x"
                    + (f"; that area is a KNOWN DEAD END for this goal, "
                       f"failed there {bad}x — do NOT go back" if bad else "")
                    + "]")
            else:
                untried.append(f"({k})->{w.get('dest')}")
        been = self.visits.get(here, 0)
        warned = ""
        if been >= 2:
            warned = (f"\nYOU HAVE BEEN IN THIS EXACT AREA {been} TIMES "
                      f"ALREADY ({here}). Arriving here again is not "
                      f"progress — if the last thing you did brought you "
                      f"back here, undo that choice and take a different "
                      f"exit.")
        for sg_id, regions in self.dead_ends.items():
            if here in regions:
                warned = (f"\nNOTE: earlier attempts failed to achieve "
                          f"'{sg_id}' from this exact area "
                          f"({regions[here]}x). Whatever you need is NOT "
                          f"reachable from here — leave first.")
                break
        if not (untried or tried):
            return warned
        out = warned + "\nEXITS FROM HERE — "
        out += ("UNTRIED (prefer these, they are the only way to find "
                f"anything new): {', '.join(untried)}. " if untried
                else "none untried. ")
        if tried:
            out += (f"Already taken from here: {'; '.join(tried)} — retaking "
                    "one returns you where it says, which you have seen.")
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
        name = subgoal.get("battle_policy", "traversal")
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
grass; each battle is fought and the op repeats until the subgoal's level
target is met — use when the goal is to TRAIN/level up),
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
                len((obs or {}).get("flags") or []))

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
            sig = (op, step.get("name") or step.get("dir")
                   or (step.get("x"), step.get("y")))
            if op == "use_warp":
                known = (self.explored.get(self._where(obs), {}) or {}).get(
                    f"{step.get('x')},{step.get('y')}")
                bad = (self.dead_ends.get(sg["id"], {}) or {}).get(
                    (known or {}).get("to", ""), 0)
                if bad and self._dead_visits < 2:
                    self._dead_visits += 1
                    trace.append(
                        f"use_warp({step.get('x')},{step.get('y')}): REFUSED "
                        f"— it leads to {known['to']}, where this goal has "
                        f"already provably failed {bad}x. Take a different "
                        f"exit.")
                    continue
            # NO IMMEDIATE REVERSAL — the classic search prune, not game
            # knowledge: both directions of a ladder read as "untried" from
            # their own side, so the run oscillated B1F<->B2F until its
            # rounds ran out. Yields after 2 refusals so a true dead end can
            # still be backed out of.
            if (op == "use_warp" and self._arrived
                    and self._where(obs) == self._arrived[0]
                    and (step.get("x"), step.get("y")) == self._arrived[1]
                    and self._reversals < 2):
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
                self._dead_ops[sig] = self._dead_ops.get(sig, 0) + 1
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
            if r.get("ok") and before[0] != after[0] and not blackout:
                self.note_transition(pre_obs, step, obs)
                # RECOGNISE A DEAD END ON ARRIVAL. The exit-level warning
                # only covers exits already taken FROM here, so an untried
                # ladder that happens to drop into a known-bad room walked
                # in unchallenged (user watched it happen). Landing is the
                # other moment we can check — and it also teaches the edge,
                # so next time the exit itself carries the warning.
                land = self._where(obs)
                bad = (self.dead_ends.get(sg["id"], {}) or {}).get(land, 0)
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
                 blocked_id: str = "") -> tuple[bool, list]:
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
        if redo:
            # relocating across a dungeon takes many legs; the round budget
            # for a normal subgoal is far too small (thin5 ran out inside
            # the mountain, mid-journey, and reported failure)
            rounds = max(rounds, 20)
        feedback = "This is the first attempt."
        inert = []          # targets that ran but did nothing / failed
        backward = []       # ops that moved us to an already-visited map
        progress = []       # clean ops accumulated across rounds
        self._dead_ops = {}
        self._dead_visits = 0
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
            memory = self.exploration_text(start, sg["id"])
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
                failed_here = (self.dead_ends.get(blocked_id, {})
                               or {}).get(land, 0)
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
                    ok = False
                    trace.append(
                        "(you are back in the SAME walkable area you started "
                        "from — the same places are reachable, so nothing has "
                        "changed. You must reach a DIFFERENT area: a door you "
                        "have not used, the far side of the map.)")
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
            unreachable = [t for t in trace
                           if "no reachable tile adjacent" in t
                           or "cannot be walked to from" in t]
            if unreachable and cur:
                here = self._where(cur)
                self.note_dead_end(sg["id"], here)
                objs = [o for o in ((cur.get("map") or {}).get("objects")
                                    or []) if not o.get("reachable")]
                seam = any("cannot be walked to from" in t for t in trace)
                if objs or seam:
                    self.log("target_unreachable", subgoal=sg["id"],
                             region=here,
                             objects=[o.get("name") for o in objs][:5])
                    # nothing here can achieve it: stop burning rounds
                    print(f"   (target unreachable from {here} — "
                          f"abandoning this area)")
                    break
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
                        + self.exploration_text(cur, sg["id"])
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
            if (not ok and self.can_escalate and idx > 0
                    and backtracks < 2 and not sg.get("optional")):
                prev = subgoals[idx - 1]
                stuck_region = ((self.settle() or {}).get("map")
                                or {}).get("region", "")
                backtracks += 1
                print(f"   <- backtracking: redoing {prev['id']} "
                      f"(it may have finished in the wrong place)")
                self.log("backtrack", failed=sg["id"], redoing=prev["id"])
                try:
                    moved, ops = self.escalate(
                        prev, redo=True, avoid_region=stuck_region,
                        blocked_id=sg["id"],
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
                                blocked_id=sg["id"],
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
                if fails < 3 and not last:
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
        b.send("new_game")
    for _ in range(8):
        if b.send("mash_a", times=30)["mode"] == "overworld":
            return
    raise RuntimeError("bootstrap failed")


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
    ok = True
    for plan_path in args.plans:
        plan = json.loads(plan_path.read_text())
        ex.plan, ex.plan_path = plan, plan_path
        ex.status(plan=plan_path.name)
        print(f"\n===== PLAN: {plan_path.name} =====")
        ok = ex.run_plan(plan)
        if not ok:
            break
        if args.save_after_each:
            r = (ex._send_safe("save_game") or {}).get("result") or {}
            print(f"[save] {r.get('detail') or 'save failed'}")
    o = b.obs() or {}
    print(f"\nRESULT: {'ALL PLANS COMPLETE' if ok else 'PLAN FAILED'} | "
          f"map={(o.get('map') or {}).get('id')} "
          f"party={[(m.get('species'), m.get('level')) for m in o.get('party') or []]} "
          f"badges={o.get('badges')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
