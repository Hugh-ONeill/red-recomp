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


def _run_policy(spec, bridge, obs, log, max_turns):
    """Drive a battle turn-by-turn with a battle_policy spec (rules as data).
    With SCORE_BATTLES, also probe the oracle each turn and log policy-vs-
    oracle agreement — the measuring stick, which does not alter play."""
    turns = 0
    while obs and obs.get("mode") == "battle" and turns < max_turns:
        turns += 1
        op = battle_policy.choose(obs, spec)
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
        obs = bridge.send(name, **op)
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
        battle_policy.DEFAULT_SPEC, b, o, lg, mt),
    "typed_v0": lambda b, o, lg, mt: _run_policy(
        battle_policy.SPECS["typed_v0"], b, o, lg, mt),
    "slot1": battle_slot1,
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
        self.logf = open(RUN / "executor_log.jsonl", "a")
        self.t0 = time.time()

    def log(self, kind, **kw):
        self.logf.write(json.dumps(
            {"dt": round(time.time() - self.t0, 1), "kind": kind, **kw}) + "\n")
        self.logf.flush()

    def handle_battle(self, subgoal: dict, obs: dict) -> dict:
        name = subgoal.get("battle_policy", "default")
        self.log("battle_start", subgoal=subgoal["id"], policy=name)
        return BATTLE_POLICIES[name](self.b, obs, self.log,
                                     self.max_battle_turns)

    def settle(self) -> dict:
        """Resolve to a clean decision state before checking guards/predicates.
        A step can leave the game mid-dialogue (e.g. the 'got the PARCEL!' box,
        after which the event flag sets only once it closes), where map reads
        None and map-keyed when-guards would wrongly skip. A `wait` triggers
        the shim's auto-advance, which rides plain text to the next decision."""
        obs = self.b.obs()
        for _ in range(12):
            if not obs or obs.get("mode") != "dialog":
                return obs
            obs = self.b.send("wait", frames=6)
        return obs

    MACRO_AUTHOR_SYS = """You AUTHOR a macro — an ordered list of ops — to
achieve one Pokemon Red subgoal, then the executor RUNS it. You do NOT pilot
live; you write the whole sequence up front, reading the observation for exact
coordinates. Read:
  obs.map.warps      doors/stairs as {x,y,dest} — use_warp their x,y to exit
  obs.map.objects    interactables as {kind,name,x,y} — interact by name
  obs.map.connections adjacent maps by direction — cross that direction
Ops: {"op":"walk_to","x":N,"y":N} (within-map), {"op":"cross","dir":"north|
south|east|west"} (to the adjacent map), {"op":"use_warp","x":N,"y":N} (a
door/stairs), {"op":"interact","name":"OBJECT_NAME"}, {"op":"menu","index":N}
(1-based: 1=YES/first, 2=NO/second), {"op":"wait"}. Battles are auto-handled.
Reply with ONLY a JSON array of ops, e.g.
[{"op":"use_warp","x":7,"y":1},{"op":"use_warp","x":2,"y":7}]"""

    @staticmethod
    def _parse_macro(text: str):
        import re
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return None
        try:
            arr = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        out = []
        for step in arr if isinstance(arr, list) else []:
            if isinstance(step, dict) and "op" in step:
                out.append(step)
        return out or None

    @staticmethod
    def _snapshot(obs):
        p = (obs or {}).get("player") or {}
        return ((obs or {}).get("map", {}).get("id") if obs else None,
                p.get("x"), p.get("y"), (obs or {}).get("mode"),
                len((obs or {}).get("party") or []),
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
            step.pop("when", None)
            op = step.pop("op", None)
            if not op:
                continue
            obs = self.settle()
            if obs and obs.get("mode") == "battle":
                obs = self.handle_battle(sg, obs)
                obs = self.settle()
            if pred_holds(done, obs):
                return True, trace, clean
            before = self._snapshot(obs)
            traversal = op in ("cross", "walk_to")
            for _ in range(12):
                try:
                    obs = self.b.send(op, **step)
                except TimeoutError:
                    obs = self.b.obs()
                    break
                if obs and obs.get("mode") == "battle":
                    obs = self.handle_battle(sg, obs)
                    obs = self.settle()
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
                note += ": ok" + (f" ({', '.join(chg)})" if chg else "")
            trace.append(note)
            # distill an op if it ran OK *or* changed the state — cross via the
            # Oak escort reports ok=False ("cross attempted") yet the map
            # changes, and menu ops have delayed effects; only genuinely-failed
            # no-ops (interact 'stairs') are both not-ok and inert, so dropped.
            if r.get("ok") or before != after:
                clean.append({"op": op, **step})
            if pred_holds(done, self.settle()):
                return True, trace, clean
        return pred_holds(done, self.settle()), trace, clean

    def escalate(self, sg: dict) -> tuple[bool, list]:
        """SPD escalation: the model AUTHORS a candidate macro (its strength),
        the executor RUNS it with a per-step trace, and on success distills.
        On failure the DIAGNOSTIC trace (which ops did nothing / where it
        ended) is fed back so the model can rethink — not just 'try again'."""
        goal = sg.get("goal_text", sg["id"])
        done = sg.get("done_when")
        rounds = sg.get("escalation_rounds", 4)
        feedback = "This is the first attempt."
        self.log("escalate_start", subgoal=sg["id"], goal=goal)
        # capture the subgoal's start so each round retries from a clean state
        # (a failed proposal otherwise corrupts the state and later rounds
        # compound the mess — the 2F<->1F house bounce).
        cap = self.b.send("checkpoint_capture", token="esc")
        can_reset = bool((cap.get("result") or {}).get("ok"))
        self.log("escalate_checkpoint", subgoal=sg["id"], captured=can_reset)
        for rnd in range(1, rounds + 1):
            if rnd > 1 and can_reset:
                self.b.send("checkpoint_restore", token="esc")
            obs = model_view(self.settle())
            user = (f"SUBGOAL: {goal}\nDONE_WHEN: {json.dumps(done)}\n"
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
                         reply=reply[:160])
                feedback = "Your last reply was not a JSON op array. Return " \
                           "ONLY a JSON array of op objects."
                continue
            self.log("escalate_proposal", subgoal=sg["id"], round=rnd,
                     macro=macro)
            ok, trace, clean = self._run_traced(sg, macro)
            if ok:
                # DISTILL-THEN-VERIFY: a macro is only trustworthy if it
                # reproduces the subgoal from the clean start (walk_to onto a
                # door mat can fire the warp once by luck and fail on replay;
                # use_warp is reliable). Replay the clean ops from the start
                # checkpoint; commit only if they reach done_when again.
                restored = False
                if can_reset:
                    rr = self.b.send("checkpoint_restore", token="esc")
                    restored = bool((rr.get("result") or {}).get("ok"))
                if restored:
                    v_ok, _, v_clean = self._run_traced(sg, clean)
                    if v_ok:
                        self.log("escalate_verified", subgoal=sg["id"],
                                 round=rnd, ops=len(v_clean))
                        return True, v_clean
                    self.log("escalate_unverified", subgoal=sg["id"], round=rnd)
                    feedback = (
                        "Your macro reached the goal ONCE but did NOT reproduce "
                        "it on a clean replay — some op relied on luck or "
                        "approach. For doors/stairs/exits use use_warp{x,y} "
                        "(reliable), NOT walk_to onto the tile. Re-author.")
                    self.b.send("checkpoint_restore", token="esc")
                    continue
                # couldn't restore to verify (some states refuse it) — commit
                # the first run's clean ops best-effort rather than a bogus
                # 0-op "verified" from an un-reset replay.
                self.log("escalate_success", subgoal=sg["id"], round=rnd,
                         proposed=len(macro), distilled=len(clean),
                         verified=False)
                return True, clean
            cur = self.settle() or {}
            feedback = ("Per-step results of your last macro:\n"
                        + "\n".join(f"  {i + 1}. {t}"
                                    for i, t in enumerate(trace))
                        + f"\nAfter it, DONE_WHEN was NOT met. Now: map="
                        f"{(cur.get('map') or {}).get('id')}, mode="
                        f"{cur.get('mode')}, party size="
                        f"{len(cur.get('party') or [])}.")
            self.log("escalate_feedback", subgoal=sg["id"], round=rnd,
                     trace=trace)
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
                traversal = op in ("cross", "walk_to")
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
            ok = self.run_subgoal(sg) if has_macro else False
            if not ok and self.can_escalate:
                print(f"   -> escalating {sg['id']} to the model")
                self.escalations += 1
                success, ops = self.escalate(sg)
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
    args = ap.parse_args()

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
