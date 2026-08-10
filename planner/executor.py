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
def _run_policy(spec, bridge, obs, log, max_turns):
    """Drive a battle turn-by-turn with a battle_policy spec (rules as data)."""
    turns = 0
    while obs and obs.get("mode") == "battle" and turns < max_turns:
        turns += 1
        op = battle_policy.choose(obs, spec)
        why = op.pop("_why", None)
        name = op.pop("op")
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
    def __init__(self, bridge: Bridge, max_battle_turns: int = 40):
        self.b = bridge
        self.max_battle_turns = max_battle_turns
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
        self.log("plan_start", goal=plan.get("goal"))
        for sg in plan["subgoals"]:
            print(f"== subgoal: {sg['id']}")
            if not self.run_subgoal(sg):
                print(f"!! ESCALATE: subgoal {sg['id']} failed its predicate "
                      f"after {sg.get('max_attempts', 3)} attempts")
                self.log("plan_failed_at", subgoal=sg["id"])
                return False
            print(f"   done: {sg['id']}")
        self.log("plan_complete", goal=plan.get("goal"))
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
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text())
    b = Bridge()
    if args.bootstrap:
        bootstrap(b)
    ex = Executor(b, max_battle_turns=args.max_battle_turns)
    ok = ex.run_plan(plan)
    o = b.obs() or {}
    print(f"\nRESULT: {'PLAN COMPLETE' if ok else 'PLAN FAILED'} | "
          f"map={(o.get('map') or {}).get('id')} "
          f"party={[(m.get('species'), m.get('level')) for m in o.get('party') or []]} "
          f"badges={o.get('badges')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
