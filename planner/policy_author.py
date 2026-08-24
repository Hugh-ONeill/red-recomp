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
import re as _re
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
  switch: list of mid-battle switch rules, each:
      {"to": 1-6, "first_turns": 1-8, "max_uses": 1-6,
       "vs": "trainer"|"wild"|"any", "hp_below": null or 0.0-1.0,
       "only_if_lead": null or 1-6}
    (bring party slot `to` in, in the battle's first `first_turns` turns,
     up to max_uses times, only against that battle kind, only while the
     ACTIVE mon's hp fraction is below hp_below if given, and only when
     the mon that STARTED the battle was slot only_if_lead. A switch
     costs the turn and the foe gets a free hit — whether that price is
     worth paying, and what you would be paying it FOR, is yours)
  flee_wild: {"when_traversal": true/false, "hp_below": null or 0.0-1.0}
    (when_traversal: flee wild battles while traveling to save HP;
     hp_below: also flee ANY wild when own hp fraction is below this.
     Trainers can never be fled. Fleeing can fail; after 3 fails we fight.)
  battle_items: list of in-battle heal rules, each:
      {"item": "POTION", "hp_below": 0.0-1.0, "max_uses": 1-6}
    (use the item — costing the turn — when own hp fraction is below
     hp_below; at most max_uses per battle; only if the bag has it.
     IT IS A LIST, AND NAMING ONE ITEM IS HOW THESE RULES DIE. A rule
     naming an item you have run out of does nothing at all: v1 named
     POTION and by the Elite Four the party carried none, so `battle_item`
     fired ONCE in 6041 battle turns while three MAX_REVIVEs sat in the
     bag; v2 named HYPER_POTION and went dead the same way two fights
     later. Name every healing item you would actually spend, strongest
     last, and the party keeps healing as the bag empties.)
  field_heal: null or {"item": "POTION", "hp_below": 0.0-1.0}
    (one item only here — so pick one you will still have)
    (after a battle ends while traveling: if own hp fraction is below
     hp_below and the item is in the bag, use it in the FIELD — no turn
     cost — before walking on)
  field_cure: list of {"status": "PSN"|"PAR"|"BRN"|"SLP"|"FRZ",
                       "item": "ANTIDOTE"}
    (after a battle: cure that status with that item if the bag has one —
     poison keeps draining HP every few steps until cured. Field item
     rules cover the WHOLE party, neediest mon first.)
  catch: {"ball": "POKE_BALL", "throw_at_hp_frac": 0.0-1.0,
          "max_balls": 1-10}
    (during a CATCH task: weaken the wild mon with the gentlest non-KO
     move until it is below that fraction of the hp it appeared with,
     then throw — gen1 catch odds scale with missing hp)
  replacement: {"order": "healthiest"|"first_alive"}
    (when your active mon faints and a backup lives, which one comes in —
     a replacement instead of a blackout, which would HALVE your money)"""

# ------------------------------------------------------- context, from evidence
# WHAT USED TO BE HERE. A hand-written CONTEXT block that told the model
# Brock's roster and levels, that Onix is Rock/Ground and weak to water, the
# rival's moveset, the Viridian Forest encounter table, and which items
# Viridian stocks versus Pewter and in what order to buy them. Per
# fresh_run.sh the spec authored under that prompt fights EVERY BATTLE OF THE
# RECORD RUN, which made it the widest claim breach in the runtime path: the
# open model was supposed to bring the Pokemon knowledge, and we were
# handing it the answers to the two fights the early game turns on.
#
# It was also, by then, describing a different run. It opened "Squirtle
# lead"; this run has led with a Charmander since the first morning.
#
# Everything below is assembled from the run's own battle log — foes it has
# actually met, damage it has actually watched land, deaths it has actually
# died. The model still brings the type chart, the mechanics and the
# judgment. We bring what happened.

_MOVE_RE = _re.compile(r"\b([A-Z][A-Z_]{2,})\b")


def _move_of(why: str):
    """The move a battle_turn line played. `why` is the policy's own reason
    string — "SCRATCH score=40.0 eff=1.0", "KO with BUBBLE", "setup
    TAIL_WHIP (use 1)" — and the move id is the one SHOUTED token in it."""
    m = _MOVE_RE.search(why or "")
    return m.group(1) if m else None


def battle_evidence(log_path: Path = None) -> dict:
    """Read the run's battle log into facts. Nothing here is knowledge about
    Pokemon Red; it is a transcript of this party's fights."""
    log_path = Path(log_path or LOG)
    foes: dict = {}          # species -> {"n", "lv_min", "lv_max"}
    dealt: dict = {}         # (move, foe species) -> [damage, ...]
    taken: dict = {}         # foe species -> [damage, ...]
    blackouts: list = []
    turns: list = []
    cur = None
    if not log_path.exists():
        return {"foes": foes, "dealt": dealt, "taken": taken,
                "blackouts": blackouts, "turns": turns, "battles": 0}
    battles = 0
    with open(log_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            k = d.get("kind")
            if k == "battle_start":
                battles += 1
                sp, _, lv = (d.get("foe") or "").rpartition(" L")
                try:
                    lv = int(lv)
                except ValueError:
                    lv = None
                if sp:
                    e = foes.setdefault(sp, {"n": 0, "lv_min": lv,
                                             "lv_max": lv})
                    e["n"] += 1
                    if lv is not None:
                        e["lv_min"] = min(e["lv_min"] or lv, lv)
                        e["lv_max"] = max(e["lv_max"] or lv, lv)
                # OUR level too, or a damage range is unreadable: "EMBER vs
                # GEODUDE: 5-42" is one move at L9 and the same move at L33,
                # and a rule written off the top of that range walks into
                # fights it cannot win.
                mlv = (d.get("me") or "").split(" L")
                try:
                    mlv = int(mlv[1].split()[0]) if len(mlv) > 1 else None
                except ValueError:
                    mlv = None
                cur = {"foe": sp, "fhp": None, "mhp": None, "mv": None,
                       "mlv": mlv}
            elif k == "battle_turn" and cur:
                fhp, mhp = d.get("foe_hp"), d.get("me_hp")
                # ONLY THE MON THAT STARTED. battle_start names one level,
                # but a switch or a faint replacement puts a different
                # Pokemon on the field — and then GUST, which only PIDGEY
                # knows, gets filed under CHARMELEON's level. A switch op or
                # an HP bar that RISES means the active mon changed; from
                # there the level is unknown and gets recorded as such.
                # A faint replacement is logged as `pick_party`, not
                # `battle_switch` — that one omission filed sixteen PIDGEY
                # GUSTs under a level-19 CHARMELEON.
                if d.get("op") in ("battle_switch", "pick_party") or (
                        cur["mhp"] is not None and mhp is not None
                        and mhp > cur["mhp"]):
                    cur["mlv"] = None
                if cur["mv"] and cur["fhp"] is not None and fhp is not None:
                    dmg = cur["fhp"] - fhp
                    if dmg > 0:
                        dealt.setdefault((cur["mv"], cur["foe"]),
                                         []).append((dmg, cur["mlv"]))
                if cur["mhp"] is not None and mhp is not None:
                    hurt = cur["mhp"] - mhp
                    if hurt > 0:
                        taken.setdefault(cur["foe"], []).append(hurt)
                cur["fhp"], cur["mhp"] = fhp, mhp
                # only a MOVE can be credited with damage: "heal with POTION"
                # and "throw POKE_BALL" both carry a shouted token too
                cur["mv"] = (_move_of(d.get("why"))
                             if d.get("op") == "battle_move" else None)
            elif k == "battle_done":
                if d.get("turns"):
                    turns.append(d["turns"])
                cur = None
            elif k == "blackout":
                blackouts.append((d.get("subgoal"), d.get("respawn"),
                                  d.get("op")))
    return {"foes": foes, "dealt": dealt, "taken": taken,
            "blackouts": blackouts, "turns": turns, "battles": battles}


def evidence_context(obs: dict | None = None,
                     log_path: Path = None) -> str:
    """The brief the policy author is given: this run's own record."""
    ev = battle_evidence(log_path)
    out = ["THE RUN THIS POLICY PLAYS. Everything below is what this party "
           "has already been through — read out of its own battle log, not "
           "out of a book. The Pokemon knowledge is yours to bring."]

    party = (obs or {}).get("party") or []
    if party:
        out.append("\nYOUR PARTY AS IT STANDS:")
        for i, m in enumerate(party, 1):
            mv = ", ".join(str(x.get("id")) for x in (m.get("moves") or []))
            out.append(f"  {i}. {m.get('species')} L{m.get('level')} "
                       f"{m.get('hp')}/{m.get('max_hp')}hp"
                       + (f" — {mv}" if mv else ""))
    bag = (obs or {}).get("bag") or {}
    if bag:
        out.append("\nWHAT IS IN THE BAG (a rule that spends an item you do "
                   "not carry never fires): "
                   + ", ".join(f"{k} x{v}" for k, v in sorted(bag.items())))

    if ev["foes"]:
        top = sorted(ev["foes"].items(), key=lambda kv: -kv[1]["n"])[:14]
        rows = ", ".join(
            f"{sp} L{e['lv_min']}"
            + (f"-{e['lv_max']}" if e["lv_max"] != e["lv_min"] else "")
            + f" ({e['n']}x)" for sp, e in top)
        out.append(f"\nWHAT YOU HAVE ACTUALLY FOUGHT, most often first "
                   f"({ev['battles']} battles on record): {rows}.")
    if ev["turns"]:
        t = sorted(ev["turns"])
        med = t[len(t) // 2]
        out.append(f"A battle has run {med} turn{'' if med == 1 else 's'} at "
                   f"the median and {t[-1]} at the longest.")

    if ev["dealt"]:
        rows = sorted(ev["dealt"].items(), key=lambda kv: -len(kv[1]))[:14]
        out.append("\nDAMAGE YOUR MOVES HAVE BEEN SEEN TO DO (the HP bar is "
                   "on screen; this is what it moved by):")
        for (mv, sp), v in rows:
            dmg = [x for x, _l in v]
            lv = [l for _x, l in v if l is not None]
            span = (f" at your L{min(lv)}" + (f"-{max(lv)}"
                    if max(lv) != min(lv) else "")) if lv else ""
            out.append(f"  {mv} vs {sp}: {min(dmg)}-{max(dmg)} over "
                       f"{len(v)} use(s){span}")
    if ev["taken"]:
        rows = sorted(ev["taken"].items(),
                      key=lambda kv: -max(kv[1]))[:8]
        out.append("\nDAMAGE THEY HAVE DONE TO YOU, worst hitters first: "
                   + ", ".join(f"{sp} up to {max(v)}" for sp, v in rows)
                   + ".")

    if ev["blackouts"]:
        where: dict = {}
        for sg, respawn, _op in ev["blackouts"]:
            where[sg or "?"] = where.get(sg or "?", 0) + 1
        rows = ", ".join(f"{k} ({v}x)" for k, v in
                         sorted(where.items(), key=lambda kv: -kv[1])[:6])
        out.append(f"\nHOW THIS PARTY HAS DIED: {len(ev['blackouts'])} "
                   f"blackout(s) on record, during — {rows}. A blackout "
                   f"ends the leg wherever it happens.")
    else:
        out.append("\nThis party has no blackouts on record.")
    return "\n".join(out)


SYS_HEAD = ("You AUTHOR a Pokemon Red battle policy as a JSON SPEC in the "
            "DSL below. A deterministic interpreter executes your rules; "
            "you are writing the decision rules, not playing turns. Use "
            "your knowledge of gen-1 mechanics. Reply with ONLY the JSON "
            "spec object.\n\n")


def sys_prompt(obs: dict | None = None, log_path: Path = None) -> str:
    return SYS_HEAD + DSL_DOC + "\n\n" + evidence_context(obs, log_path)


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

    def __init__(self, plan_path: Path, run_id: str, model: str = "",
                 from_save: Path | None = None, arena: str = "brock"):
        self.plan_path = plan_path
        self.run_id = run_id
        self.model = model
        self.game = None
        self.rival_ok = False
        # THE ARENA HAS TO BE THE FIGHT YOU CARE ABOUT. This gym replays
        # plans/brock.json and scores candidates on the L5 rival and the
        # walk to the Boulder Badge, which is why v1 came back healing with
        # POTION below 30% — true of a Charmander, useless to a level-50
        # party carrying hyper potions, and `battle_item` fired ONCE in
        # 6041 battle turns as a result (user, 2026-08-24: "yeah we never
        # did make that policy v2"). `--from-save` boots an ISOLATED copy
        # of a real save — never the campaign's own game — and `--arena e4`
        # scores a candidate on the Elite Four instead.
        self.from_save = from_save
        self.arena = arena
        self.run_dir = RUN

    def _load_plan(self):
        self.plan = json.loads(self.plan_path.read_text())
        self.sgs = {s["id"]: s for s in self.plan["subgoals"]}

    def boot(self):
        self._load_plan()   # fresh copy: setup escalation mutates in-memory
        if (RUN / "obs.json").exists():
            (RUN / "obs.json").unlink()
        if self.from_save:
            # contract.py's isolation: own love identity, own bridge dir,
            # a COPY of the save. The campaign's game is untouchable.
            sys.path.insert(0, str(REPO / "tests"))
            from contract import start_game            # noqa: E402
            self.run_dir = REPO / "run/policyarena"
            self.game = start_game(self.run_dir, self.from_save, "200")
            os.environ["RED_BRIDGE_DIR"] = str(self.run_dir)
        else:
            self.game = subprocess.Popen(
                [str(REPO / "run.sh"), "200"], cwd=REPO,
                start_new_session=True)
        atexit.register(self.shutdown)
        for _ in range(60):
            if (self.run_dir / "obs.json").exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError("game did not come up")
        self.b = Bridge(self.run_dir) if self.from_save else Bridge()
        ex_mod.SCORE_BATTLES = True
        # escalation available during SETUP only (plan_path=None: authored
        # fixes stay in-memory, the plan file is never touched by eval)
        self.ex = ex_mod.Executor(self.b, plan=self.plan, plan_path=None,
                                  can_escalate=bool(self.model),
                                  model=self.model, run_id=self.run_id)
        ex_mod.bootstrap(self.b, cont=bool(self.from_save))

    def shutdown(self):
        if self.game and self.game.poll() is None:
            try:
                os.killpg(self.game.pid, signal.SIGTERM)
            except Exception:
                pass

    # ------------------------------------------------------ the E4 arena
    E4_ROOMS = ["LORELEIS_ROOM", "BRUNOS_ROOM", "AGATHAS_ROOM",
                "LANCES_ROOM", "CHAMPIONS_ROOM"]

    def prepare_e4(self):
        """Checkpoint the save exactly as it stands, and score from there.

        THE SAVEPOINT IS THE CONTROL SURFACE (user, 2026-08-24: "can we
        just control everything from a savepoint?"). The first version of
        this walked back down the room chain and healed, which bakes an
        assumption about where the save sits into the gym; park the save
        where you want the trial to begin instead and this stays four
        lines. Whatever the save holds — which room, what HP, which party
        — is the arena, restored fresh for every candidate.
        """
        obs = self.ex.settle()
        here = ((obs or {}).get("map") or {}).get("id")
        party = [f"{p.get('species')} L{p.get('level')} "
                 f"{p.get('hp')}/{p.get('max_hp')}"
                 for p in (obs.get("party") or [])]
        print(f"[gym] arena: {here}")
        for p in party:
            print(f"[gym]   {p}")
        self.b.send("checkpoint_capture", token="eval_e4")
        self.rival_ok = False

    def eval_spec_e4(self, spec: dict, k: int = 3) -> dict:
        """How far up the Elite Four does this policy get, from healed?"""
        ex_mod.set_active_spec(spec)
        res = {"rival_wins": 0, "rival_trials": 0, "pewter": 0, "badge": 0,
               "gauntlet_trials": 0, "blackouts": 0, "agree": 0,
               "scored": 0, "dmg_gap": 0.0, "rival_detail": [],
               "gauntlet_detail": [], "rooms": 0}
        for _ in range(k):
            self.b.send("checkpoint_restore", token="eval_e4", reseed=True)
            res["gauntlet_trials"] += 1
            start = LOG.stat().st_size
            got = 0
            cleared = 0
            try:
                for _ in range(len(self.E4_ROOMS)):
                    obs = self.ex.settle()
                    here = ((obs or {}).get("map") or {}).get("id")
                    if here not in self.E4_ROOMS:
                        break            # blacked out, or fell out of the run
                    got = max(got, self.E4_ROOMS.index(here) + 1)
                    # THE LEADER IS AN NPC AND YOU CANNOT WALK ONTO ONE.
                    # This walked to (5,2), which is exactly where Bruno
                    # STANDS, so the walk failed, no fight started, and
                    # every trial scored "reached room 2" without a single
                    # punch thrown. Press him instead.
                    boss = next((o.get("name") for o in
                                 ((obs.get("map") or {}).get("objects") or [])
                                 if o.get("kind") in ("trainer", "npc")
                                 and o.get("name")), None)
                    if boss:
                        self.b.send("interact", name=boss)
                        obs = self.ex.settle()
                    while (obs or {}).get("mode") == "battle":
                        obs = self.ex.handle_battle(
                            {"id": "e4", "done_when": {}}, obs)
                        obs = self.ex.settle()
                    # beaten? the north door opens
                    self.b.send("use_warp", x=4, y=0)
                    obs = self.ex.settle()
                    nxt = ((obs or {}).get("map") or {}).get("id")
                    if nxt == here:
                        break            # still shut: the leader stands
                    cleared += 1
            except TimeoutError:
                pass
            obs = self.ex.settle()
            alive = [p for p in (obs.get("party") or [])
                     if (p.get("hp") or 0) > 0]
            res["rooms"] += cleared
            res["gauntlet_detail"].append(
                f"cleared {cleared} room(s), stopped in "
                f"{((obs.get('map') or {}).get('id'))} with "
                f"{len(alive)}/{len(obs.get('party') or [])} standing")
            for d in self._log_delta(start):
                if d.get("kind") == "blackout":
                    res["blackouts"] += 1
                elif d.get("kind") == "oracle_score":
                    res["scored"] += 1
                    res["agree"] += 1 if d.get("agree") else 0
                    res["dmg_gap"] += d.get("dmg_gap") or 0.0
        return res

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
                    if ops:              # in-memory only; [] is not a route
                        sg["macro"] = ops
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

    def _run_or_author(self, sg) -> bool:
        """Mirror record-config behavior inside eval trials: replay the
        macro; on failure, escalate ONCE per eval session (in-memory) —
        e.g. the shop leg ends inside the mart and the next subgoal's
        macro assumes the street (itemauthor5: every trial died 'entering
        the gym')."""
        ok = self.ex.run_subgoal(sg)
        if not ok and self.model and not sg.get("_esc_tried"):
            sg["_esc_tried"] = True
            succ, ops = self.ex.escalate(sg)
            if succ:
                # AN EMPTY SEQUENCE IS NOT A ROUTE — same rule as
                # Executor.distill. Escalation can succeed having proposed
                # nothing (the pathfinder walked it, a fight settled it),
                # and writing that back makes trials 2 and 3 replay a macro
                # of no ops, which changes nothing and then fails.
                if ops:
                    sg["macro"] = ops
                ok = True
        return ok

    def score(self, spec: dict) -> dict:
        """Whichever arena this gym was built for."""
        if self.arena == "e4":
            return self.eval_spec_e4(spec)
        return self.eval_spec(spec)

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
                if self._run_or_author(self.sgs["reach_pewter_city"]):
                    res["pewter"] += 1
                    shop = self.sgs.get("buy_pewter_potions")
                    if shop:
                        self._run_or_author(shop)
                    if self._run_or_author(self.sgs["enter_pewter_gym"]):
                        if not self._run_or_author(self.sgs["defeat_brock"]):
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
    if r.get("rooms") or r.get("gauntlet_detail") and not r.get("pewter") \
            and not r.get("rival_trials"):
        # the E4 arena measures one thing: how far up the rooms it got
        n = max(1, r.get("gauntlet_trials", 1))
        out = (f"{name}: Elite Four rooms cleared "
               f"{r.get('rooms', 0)}/{n * 5} across {n} trial(s), "
               f"blackouts {r['blackouts']}; oracle agreement {ag}, "
               f"damage left on the table {r['dmg_gap']:.0f}")
        for i, g in enumerate(r.get("gauntlet_detail") or []):
            out += f"\n  trial {i+1}: {g}"
        return out
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
    # ROOMS is the E4 arena's own measure and is absent from a brock run,
    # so it simply sorts first when it is there.
    return (r.get("rooms", 0), r["badge"], r["pewter"],
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
    ap.add_argument("--from-save", type=Path, default=None,
                    help="boot an ISOLATED COPY of this save and use it as "
                         "the arena, instead of replaying --plan. Make one "
                         "with planner/make_savepoint.py")
    ap.add_argument("--arena", default="brock", choices=("brock", "e4"),
                    help="brock: the L5 rival and the Boulder Badge run. "
                         "e4: how far up the Elite Four a candidate gets "
                         "from the savepoint")
    args = ap.parse_args()

    gym = Gym(args.plan, args.run_id, model=args.model,
              from_save=args.from_save, arena=args.arena)
    for attempt in (1, 2):
        try:
            print(f"[gym] booting + replaying to the eval checkpoints "
                  f"(attempt {attempt})...")
            gym.boot()
            if args.arena == "e4":
                gym.prepare_e4()
            else:
                gym.prepare()
            break
        except Exception as e:
            print(f"[gym] setup attempt {attempt} failed: {e}")
            gym.shutdown()
            if attempt == 2:
                raise
            time.sleep(3)
    print(f"[gym] ready (rival fight re-armable: {gym.rival_ok})")
    # The brief is assembled AFTER the boot, so the party and bag in it are
    # the ones this spec will actually be handed. It used to be a module
    # constant written months ago describing a Squirtle that never existed
    # in this run.
    _ex = getattr(gym, "ex", None)
    sys_msg = sys_prompt(_ex.settle() if _ex else None)
    print(f"[gym] evidence brief: {len(sys_msg)} chars")

    if args.eval_only:
        spec = battle_policy.load_spec(args.eval_only)
        print(f"[eval-only] {spec.get('name')}")
        r = gym.score(spec)
        print(feedback_text(spec.get("name", "artifact"), r))
        base = gym.score(battle_policy.DEFAULT_SPEC)
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
            [{"role": "system", "content": sys_msg},
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
        r = gym.score(spec)
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
    base = gym.score(battle_policy.DEFAULT_SPEC)
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
