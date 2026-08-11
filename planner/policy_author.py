#!/usr/bin/env python3
"""Model-authored battle policy: the model writes the SPEC, the game
referees it.

CLAIM_RULES: the battle-policy artifact must be authored by the local open
model. This driver runs that authoring loop:
  1. the model writes a spec in the battle_policy DSL (its Pokemon
     knowledge -> deterministic rules; knowledge-in-decisions-out),
  2. each candidate is evaluated LIVE on the run's decisive fights via
     RESEEDED checkpoint trials (the L5 rival fight; the forest gauntlet
     through Pewter Gym to Brock),
  3. results (win rates, blackouts, oracle agreement/damage-gap) feed back
     for revision. The oracle referees; it never plays.
The best spec is saved with provenance for executor.py --policy-spec.

Owns its own game process (fresh_run pattern). Usage:
  policy_author.py --rounds 4 --out plans/policy_model_v1.json
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import battle_policy
import brock_probe
import executor as ex_mod
from bridge import Bridge, RUN

REPO = Path(__file__).resolve().parent.parent
LOG = RUN / "executor_log.jsonl"

DSL_DOC = """SPEC DSL (JSON object; every key optional; no other keys):
  name: short string naming your policy
  stab: number 1.0-2.0 — weight for same-type (STAB) moves in scoring
  accuracy_weight: true/false — weight move scores by accuracy
  prefer_ko: true/false — pick a move estimated to KO over raw score
  ko_margin: number >= 1.0 — only trust a KO if est. damage >= foe hp*this
  avoid_status_moves: true/false — never pick 0-power moves by score
  setup: list of deliberate status-move rules, each:
      {"move": "TAIL_WHIP", "max_uses": 1-6, "first_turns": 1-8,
       "min_hp_frac": 0.0-1.0, "vs": "trainer"|"wild"|"any",
       "only_if_best_physical": true/false}
    (use the move up to max_uses times, only in the battle's first
     first_turns turns, only while own hp fraction >= min_hp_frac,
     only against that battle kind; only_if_best_physical limits the rule
     to fights where our best damage move is PHYSICAL — a Defense-drop
     like TAIL_WHIP does nothing for a special move like BUBBLE)
  flee_wild: {"when_traversal": true/false, "hp_below": null or 0.0-1.0}
    (when_traversal: flee wild battles while traveling to save HP;
     hp_below: also flee ANY wild when own hp fraction is below this.
     Trainers can never be fled. Fleeing can fail; after 3 fails we fight.)
  battle_items: list of in-battle heal rules, each:
      {"item": "POTION", "hp_below": 0.0-1.0, "max_uses": 1-6}
    (use the item — costing the turn — when own hp fraction is below
     hp_below; at most max_uses per battle; only if the bag has it)
  field_heal: null or {"item": "POTION", "hp_below": 0.0-1.0}
    (after a battle ends while traveling: if own hp fraction is below
     hp_below and the item is in the bag, use it in the FIELD — no turn
     cost — before walking on)"""

CONTEXT = """THE RUN this policy plays (one Squirtle, no items, no switches):
  - Rival fight at L5: foe Bulbasaur L5 (Tackle/Growl). Our moves: TACKLE
    (normal 35bp), TAIL_WHIP (status, lowers foe Defense). Roughly a coin
    flip under plain Tackle-spam; this fight is worth thinking about.
  - Wild grinding on Routes 1/22 to L12 (Pidgey/Rattata/Nidoran L2-5):
    grind battles are 'fight' intent — fleeing them starves XP.
  - Viridian Forest traversal: wild Weedle/Kakuna/Caterpie/Metapod L3-6
    plus unavoidable Bug Catcher trainers (Weedle/Caterpie/Kakuna L6-9).
    Poison Sting can poison; there is NO Pokemon Center mid-forest — but
    the plan buys ~5 POTIONs (20 HP each) before entering. A run that
    enters a trainer's sight at low HP with unspent potions is the #1
    recorded death (a potion between fights costs nothing; in a fight it
    costs the turn).
  - Pewter Gym: trainer (Diglett/Sandshrew L11) then BROCK: Geodude L12,
    Onix L14 (Rock/Ground — weak to water). Our kit by then: TACKLE,
    TAIL_WHIP, BUBBLE (water 20bp special), maybe WITHDRAW.
Physical damage uses Attack vs Defense; special (BUBBLE) uses Special vs
Special. TAIL_WHIP lowers foe DEFENSE (helps TACKLE, not BUBBLE)."""

SYS = ("You AUTHOR a Pokemon Red battle policy as a JSON SPEC in the DSL "
       "below. A deterministic interpreter executes your rules; you are "
       "writing the decision rules, not playing turns. Use your knowledge "
       "of gen-1 mechanics. Reply with ONLY the JSON spec object.\n\n"
       + DSL_DOC + "\n\n" + CONTEXT)


def _parse_spec(text: str):
    dec = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            val, _ = dec.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(val, dict):
            return val
        idx = text.find("{", idx + 1)
    return None


# ------------------------------------------------------------- eval harness
class Gym:
    """Boots the game, replays the plan to capture eval checkpoints, then
    scores candidate specs with reseeded restore trials."""

    def __init__(self, plan_path: Path, run_id: str, model: str = ""):
        self.plan_path = plan_path
        self.run_id = run_id
        self.model = model
        self.game = None
        self.rival_ok = False

    def _load_plan(self):
        self.plan = json.loads(self.plan_path.read_text())
        self.sgs = {s["id"]: s for s in self.plan["subgoals"]}

    def boot(self):
        self._load_plan()   # fresh copy: setup escalation mutates in-memory
        if (RUN / "obs.json").exists():
            (RUN / "obs.json").unlink()
        self.game = subprocess.Popen(
            [str(REPO / "run.sh"), "200"], cwd=REPO,
            start_new_session=True)
        atexit.register(self.shutdown)
        for _ in range(60):
            if (RUN / "obs.json").exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError("game did not come up")
        self.b = Bridge()
        ex_mod.SCORE_BATTLES = True
        # escalation available during SETUP only (plan_path=None: authored
        # fixes stay in-memory, the plan file is never touched by eval)
        self.ex = ex_mod.Executor(self.b, plan=self.plan, plan_path=None,
                                  can_escalate=bool(self.model),
                                  model=self.model, run_id=self.run_id)
        ex_mod.bootstrap(self.b)

    def shutdown(self):
        if self.game and self.game.poll() is None:
            try:
                os.killpg(self.game.pid, signal.SIGTERM)
            except Exception:
                pass

    def prepare(self):
        """Replay the plan, capturing eval checkpoints at the two decisive
        fights. Stops before reach_pewter_city."""
        for sg in self.plan["subgoals"]:
            if sg["id"] == "battle_rival_lab":
                self.b.send("checkpoint_capture", token="eval_rival")
            if sg["id"] == "reach_pewter_city":
                self.b.send("checkpoint_capture", token="eval_gate")
                break
            ok = self.ex.run_subgoal(sg)
            if not ok and self.model:
                print(f"[gym] setup: escalating {sg['id']}")
                success, ops = self.ex.escalate(sg)
                if success:
                    sg["macro"] = ops   # in-memory only
                    ok = True
            if not ok:
                raise RuntimeError(f"setup failed at {sg['id']}")
        # verify the rival fight re-arms after a reseeded restore: some
        # event state may not be in the checkpoint
        self.b.send("checkpoint_restore", token="eval_rival", reseed=True)
        obs = self.ex.settle()
        flags = obs.get("flags") or []
        self.rival_ok = "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" not in flags
        # leave the game parked on the gate checkpoint between candidates
        self.b.send("checkpoint_restore", token="eval_gate", reseed=True)

    def _log_delta(self, start: int):
        out = []
        with open(LOG) as f:
            f.seek(start)
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def _lead(self, obs):
        return ((obs or {}).get("party") or [{}])[0]

    def eval_spec(self, spec: dict, k_rival: int = 6,
                  k_gauntlet: int = 3) -> dict:
        ex_mod.set_active_spec(spec)
        res = {"rival_wins": 0, "rival_trials": 0,
               "pewter": 0, "badge": 0, "gauntlet_trials": 0,
               "blackouts": 0, "agree": 0, "scored": 0, "dmg_gap": 0.0,
               "rival_detail": [], "gauntlet_detail": []}
        if self.rival_ok:
            for _ in range(k_rival):
                self.b.send("checkpoint_restore", token="eval_rival",
                            reseed=True)
                res["rival_trials"] += 1
                try:
                    self.ex.run_subgoal(self.sgs["battle_rival_lab"])
                except TimeoutError:
                    res["rival_detail"].append("timeout")
                    continue
                lead = self._lead(self.ex.settle())
                won = (lead.get("level") or 0) >= 6
                res["rival_wins"] += 1 if won else 0
                res["rival_detail"].append(
                    f"{'W' if won else 'L'} (ended {lead.get('hp')}/"
                    f"{lead.get('max_hp')} hp)")
        for _ in range(k_gauntlet):
            self.b.send("checkpoint_restore", token="eval_gate", reseed=True)
            res["gauntlet_trials"] += 1
            start = LOG.stat().st_size
            stopped = None
            try:
                if self.ex.run_subgoal(self.sgs["reach_pewter_city"]):
                    res["pewter"] += 1
                    if self.ex.run_subgoal(self.sgs["enter_pewter_gym"]):
                        if not self.ex.run_subgoal(self.sgs["defeat_brock"]):
                            stopped = "the BROCK fight"
                    else:
                        stopped = "entering the gym"
                else:
                    stopped = "the forest crossing"
            except TimeoutError:
                stopped = "a timeout"
            obs = self.ex.settle()
            lead = self._lead(obs)
            badge = "BOULDERBADGE" in ((obs or {}).get("badges") or [])
            res["badge"] += 1 if badge else 0
            res["gauntlet_detail"].append(
                ("BADGE" if badge else f"FAILED at {stopped}")
                + f" (lead ended {lead.get('hp')}/{lead.get('max_hp')} hp)")
            for d in self._log_delta(start):
                if d.get("kind") == "blackout":
                    res["blackouts"] += 1
                elif d.get("kind") == "oracle_score":
                    res["scored"] += 1
                    res["agree"] += 1 if d.get("agree") else 0
                    res["dmg_gap"] += d.get("dmg_gap") or 0.0
        return res


def feedback_text(name: str, r: dict) -> str:
    ag = f"{r['agree']}/{r['scored']}" if r["scored"] else "n/a"
    rv = (f"{r['rival_wins']}/{r['rival_trials']}" if r["rival_trials"]
          else "not evaluable")
    out = (f"{name}: rival wins {rv}; gauntlet: reached Pewter "
           f"{r['pewter']}/{r['gauntlet_trials']}, Boulder Badge "
           f"{r['badge']}/{r['gauntlet_trials']}, blackouts "
           f"{r['blackouts']}; oracle agreement {ag}, damage left on "
           f"the table {r['dmg_gap']:.0f}")
    if r.get("rival_detail"):
        out += "\n  rival trials: " + "; ".join(r["rival_detail"])
    for i, g in enumerate(r.get("gauntlet_detail") or []):
        out += f"\n  gauntlet trial {i+1}: {g}"
    return out


def rank_key(r: dict):
    return (r["badge"], r["pewter"],
            r["rival_wins"] / max(1, r["rival_trials"]),
            -r["blackouts"], -r["dmg_gap"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--out", type=Path,
                    default=REPO / "plans/policy_model_v1.json")
    ap.add_argument("--plan", type=Path, default=REPO / "plans/brock.json")
    ap.add_argument("--model", default="gemma4:31b-it-q4_K_M")
    ap.add_argument("--run-id", default="policyauthor")
    ap.add_argument("--eval-only", type=Path, default=None,
                    help="skip authoring: evaluate this spec artifact (plus "
                         "the baseline) and report")
    args = ap.parse_args()

    gym = Gym(args.plan, args.run_id, model=args.model)
    for attempt in (1, 2):
        try:
            print(f"[gym] booting + replaying to the eval checkpoints "
                  f"(attempt {attempt})...")
            gym.boot()
            gym.prepare()
            break
        except Exception as e:
            print(f"[gym] setup attempt {attempt} failed: {e}")
            gym.shutdown()
            if attempt == 2:
                raise
            time.sleep(3)
    print(f"[gym] ready (rival fight re-armable: {gym.rival_ok})")

    if args.eval_only:
        spec = battle_policy.load_spec(args.eval_only)
        print(f"[eval-only] {spec.get('name')}")
        r = gym.eval_spec(spec)
        print(feedback_text(spec.get("name", "artifact"), r))
        base = gym.eval_spec(battle_policy.DEFAULT_SPEC)
        print(feedback_text("baseline typed_v0", base))
        gym.shutdown()
        return

    candidates = []   # (spec, results)
    feedback = "This is your first attempt."
    for rnd in range(1, args.rounds + 1):
        user = (f"Author battle-policy spec candidate #{rnd}.\n"
                f"FEEDBACK ON PREVIOUS CANDIDATES:\n{feedback}\n"
                "Author the spec now (JSON only).")
        reply = brock_probe.chat(
            [{"role": "system", "content": SYS},
             {"role": "user", "content": user}], args.model)
        spec = _parse_spec(reply)
        probs = battle_policy.validate_spec(spec) if spec else ["no JSON"]
        if probs:
            print(f"[round {rnd}] invalid spec: {probs}")
            feedback += f"\ncandidate #{rnd}: INVALID ({probs}) — fix these."
            continue
        spec.setdefault("name", f"model_r{rnd}")
        print(f"[round {rnd}] evaluating {spec['name']}: "
              f"{json.dumps(spec, separators=(',', ':'))[:200]}")
        r = gym.eval_spec(spec)
        candidates.append((spec, r))
        fb = feedback_text(f"candidate #{rnd} ({spec['name']})", r)
        print(f"[round {rnd}] {fb}")
        feedback = "\n".join(
            feedback_text(f"candidate #{i+1} ({s['name']})", rr)
            for i, (s, rr) in enumerate(candidates)) + (
            "\nImprove on the best so far; change what the results "
            "suggest is losing fights.")

    if not candidates:
        sys.exit("no valid candidates authored")
    # baseline for reference (not a candidate): the hand-seeded spec
    print("[baseline] evaluating hand-seeded typed_v0 for reference...")
    base = gym.eval_spec(battle_policy.DEFAULT_SPEC)
    print("[baseline] " + feedback_text("typed_v0", base))

    best_spec, best_r = max(candidates, key=lambda c: rank_key(c[1]))
    artifact = dict(best_spec)
    artifact["provenance"] = {
        "authored_by": args.model, "run": args.run_id,
        "via": "policy_author", "rounds": len(candidates),
        "eval": best_r, "baseline_typed_v0": base,
    }
    args.out.write_text(json.dumps(artifact, indent=2))
    print(f"\nBEST: {best_spec['name']} -> {args.out}")
    print(feedback_text(best_spec["name"], best_r))
    gym.shutdown()


if __name__ == "__main__":
    main()
