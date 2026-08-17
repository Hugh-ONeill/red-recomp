#!/usr/bin/env python3
"""Battle policy: choose a battle action from the observation.

The policy is driven by a SPEC (a dict of rules/params) — "rules as data"
per CLAIM_RULES v1, so it is the model-authorable artifact. This file is
the deterministic INTERPRETER; the rules/values come from the spec. The
hand-seeded DEFAULT_SPEC exists for spine/oracle validation only; the
record run requires a model-authored spec (policy_author.py).

SPEC DSL v1 (all keys optional; unknown keys are validation errors):
  name: str
  stab: float 1.0-2.0        same-type attack bonus weight in move scoring
  accuracy_weight: bool      weight move score by accuracy
  prefer_ko: bool            a move OBSERVED to KO wins over raw score
  ko_margin: float >= 1.0    trust a KO only if the least damage this move
                             has been SEEN to do (this species, our level)
                             >= foe hp*margin — empirical, no formulas
  avoid_status_moves: bool   never pick 0-power moves by score
  setup: [ { move: str       deliberate status-move use, e.g. TAIL_WHIP
             max_uses: int      per battle (default 1)
             first_turns: int   only in the battle's first N turns (def. 2)
             min_hp_frac: float only while own hp/max >= this (default 0.5)
             vs: "trainer"|"wild"|"any" (default "trainer")
             only_if_best_physical: bool  only when our best damage move is
                physical (e.g. TAIL_WHIP helps TACKLE, not BUBBLE) } ]
  switch: [ { to: int          bring in this party slot MID-BATTLE, e.g.
              first_turns: int   only in the battle's first N turns (def. 1)
              max_uses: int      per battle (default 1)
              vs: "trainer"|"wild"|"any" (default "any")
              hp_below: float|null  only when the ACTIVE mon's hp frac is
                 below this — omit to switch regardless of health
              only_if_lead: int|null  only when the mon that STARTED this
                 battle was that slot } ]
            A switch costs the turn and the foe gets a free hit. Whether
            that price is worth paying, and what for, is yours to decide
            and to write down as conditions.
  flee_wild: { when_traversal: bool   flee wilds during traversal subgoals
               hp_below: float|null } flee ANY wild when own hp frac below
  battle_items: [ { item: str          use a healing item IN battle (costs
                    hp_below: float    the turn) when own hp frac < this
                    max_uses: int } ]  per battle (default 2)
  field_heal: { item: str, hp_below: float } | null
                             after a battle ends, if own hp frac < this and
                             the item is in the bag, use it in the field
                             (no turn cost) before travel resumes
  field_cure: [ { status: "PSN"|"PAR"|"BRN"|"SLP"|"FRZ", item: str } ]
                             after a battle: cure the listed status with
                             the item if any party mon has it (field item
                             rules cover the WHOLE party, neediest first)
  catch: { ball: str          throw this ball at wild mons during a CATCH
           throw_at_hp_frac:  subgoal; weaken with the gentlest non-KO
             float (def 0.7)  move until the foe is below this fraction of
           max_balls: int }   the hp it appeared with, then throw (gen1
                              catch odds scale with missing hp)
  replacement: { order: "healthiest"|"first_alive" }
                             when the active mon faints with a backup
                             alive, which party slot comes in

choose(obs, spec, ctx) -> op dict for the executor. ctx carries per-battle
state the executor owns: {"turn": n, "used": {move: count},
"intent": "fight"|"traversal"}. Reads only battle-visible fields.
"""

from __future__ import annotations

import json
from pathlib import Path

_CHART = json.loads((Path(__file__).parent / "type_chart.json").read_text())

# hand-seeded starting spec; a model authors/tunes this for the record run.
DEFAULT_SPEC = {
    "name": "typed_v0",
    "stab": 1.5,
    "accuracy_weight": True,
    "prefer_ko": True,
    "ko_margin": 1.0,
    "avoid_status_moves": True,
    "setup": [],
    "switch": [],
    "flee_wild": {"when_traversal": True, "hp_below": None},
    "battle_items": [],
    "field_heal": None,
    "field_cure": [],
    # functional placeholder so the plan's catch subgoal works under the
    # baseline spec too; the record run's values come from the model
    "catch": {"ball": "POKE_BALL", "throw_at_hp_frac": 0.7, "max_balls": 3},
    "replacement": {"order": "healthiest"},
}

_SPEC_KEYS = set(DEFAULT_SPEC) | {"name", "provenance"}   # provenance = metadata


def validate_spec(spec) -> list:
    """Return a list of problems (empty = valid)."""
    probs = []
    if not isinstance(spec, dict):
        return ["spec is not an object"]
    for k in spec:
        if k not in _SPEC_KEYS:
            probs.append(f"unknown key '{k}'")
    if "stab" in spec and not (isinstance(spec["stab"], (int, float))
                               and 1.0 <= spec["stab"] <= 2.0):
        probs.append("stab must be a number in [1.0, 2.0]")
    if "ko_margin" in spec and not (isinstance(spec["ko_margin"], (int, float))
                                    and spec["ko_margin"] >= 1.0):
        probs.append("ko_margin must be a number >= 1.0")
    for k in ("accuracy_weight", "prefer_ko", "avoid_status_moves"):
        if k in spec and not isinstance(spec[k], bool):
            probs.append(f"{k} must be true/false")
    if "switch" in spec:
        if not isinstance(spec["switch"], list):
            probs.append("switch must be a list")
        else:
            for i, r in enumerate(spec["switch"]):
                if not isinstance(r, dict) or not isinstance(r.get("to"), int):
                    probs.append(f"switch[{i}] needs to=<party slot int>")
                    continue
                if not (1 <= r["to"] <= 6):
                    probs.append(f"switch[{i}].to must be a slot in [1,6]")
                if r.get("vs") not in (None, "trainer", "wild", "any"):
                    probs.append(f"switch[{i}].vs must be trainer/wild/any")
                for fk, lo, hi in (("max_uses", 1, 6), ("first_turns", 1, 8),
                                   ("only_if_lead", 1, 6)):
                    if fk in r and r[fk] is not None and not (
                            isinstance(r[fk], int) and lo <= r[fk] <= hi):
                        probs.append(f"switch[{i}].{fk} must be int "
                                     f"in [{lo},{hi}]")
                if r.get("hp_below") is not None and not (
                        isinstance(r["hp_below"], (int, float))
                        and 0.0 <= r["hp_below"] <= 1.0):
                    probs.append(f"switch[{i}].hp_below must be 0.0-1.0")
    if "setup" in spec:
        if not isinstance(spec["setup"], list):
            probs.append("setup must be a list")
        else:
            for i, r in enumerate(spec["setup"]):
                if not isinstance(r, dict) or not r.get("move"):
                    probs.append(f"setup[{i}] needs a move name")
                    continue
                if r.get("vs") not in (None, "trainer", "wild", "any"):
                    probs.append(f"setup[{i}].vs must be trainer/wild/any")
                if "only_if_best_physical" in r and not isinstance(
                        r["only_if_best_physical"], bool):
                    probs.append(f"setup[{i}].only_if_best_physical must "
                                 "be true/false")
                for fk, lo, hi in (("max_uses", 1, 6), ("first_turns", 1, 8)):
                    if fk in r and not (isinstance(r[fk], int)
                                        and lo <= r[fk] <= hi):
                        probs.append(f"setup[{i}].{fk} must be int "
                                     f"in [{lo},{hi}]")
                if "min_hp_frac" in r and not (
                        isinstance(r["min_hp_frac"], (int, float))
                        and 0.0 <= r["min_hp_frac"] <= 1.0):
                    probs.append(f"setup[{i}].min_hp_frac must be in [0,1]")
    if "battle_items" in spec:
        if not isinstance(spec["battle_items"], list):
            probs.append("battle_items must be a list")
        else:
            for i, r in enumerate(spec["battle_items"]):
                if not isinstance(r, dict) or not r.get("item"):
                    probs.append(f"battle_items[{i}] needs an item name")
                    continue
                hb = r.get("hp_below")
                if hb is not None and not (isinstance(hb, (int, float))
                                           and 0.0 <= hb <= 1.0):
                    probs.append(f"battle_items[{i}].hp_below in [0,1]")
                if "max_uses" in r and not (isinstance(r["max_uses"], int)
                                            and 1 <= r["max_uses"] <= 6):
                    probs.append(f"battle_items[{i}].max_uses int in [1,6]")
    if "field_heal" in spec and spec["field_heal"] is not None:
        fh = spec["field_heal"]
        if not isinstance(fh, dict) or not fh.get("item"):
            probs.append("field_heal must be null or {item, hp_below}")
        else:
            hb = fh.get("hp_below")
            if hb is not None and not (isinstance(hb, (int, float))
                                       and 0.0 <= hb <= 1.0):
                probs.append("field_heal.hp_below in [0,1]")
    if "field_cure" in spec:
        if not isinstance(spec["field_cure"], list):
            probs.append("field_cure must be a list")
        else:
            for i, r in enumerate(spec["field_cure"]):
                if not isinstance(r, dict) or not r.get("item") \
                        or r.get("status") not in ("PSN", "PAR", "BRN",
                                                   "SLP", "FRZ"):
                    probs.append(f"field_cure[{i}] needs status "
                                 "PSN/PAR/BRN/SLP/FRZ and an item")
    if "catch" in spec and spec["catch"] is not None:
        ca = spec["catch"]
        if not isinstance(ca, dict) or not ca.get("ball"):
            probs.append("catch must be null or {ball, throw_at_hp_frac, "
                         "max_balls}")
        else:
            th = ca.get("throw_at_hp_frac")
            if th is not None and not (isinstance(th, (int, float))
                                       and 0.0 < th <= 1.0):
                probs.append("catch.throw_at_hp_frac in (0,1]")
            if "max_balls" in ca and not (isinstance(ca["max_balls"], int)
                                          and 1 <= ca["max_balls"] <= 10):
                probs.append("catch.max_balls int in [1,10]")
    if "replacement" in spec and spec["replacement"] is not None:
        rp = spec["replacement"]
        if not isinstance(rp, dict) or rp.get("order") not in (
                None, "healthiest", "first_alive"):
            probs.append("replacement.order must be healthiest/first_alive")
    if "flee_wild" in spec:
        fw = spec["flee_wild"]
        if not isinstance(fw, dict):
            probs.append("flee_wild must be an object")
        else:
            if set(fw) - {"when_traversal", "hp_below"}:
                probs.append("flee_wild keys: when_traversal, hp_below")
            if "when_traversal" in fw and not isinstance(
                    fw["when_traversal"], bool):
                probs.append("flee_wild.when_traversal must be true/false")
            hb = fw.get("hp_below")
            if hb is not None and not (isinstance(hb, (int, float))
                                       and 0.0 <= hb <= 1.0):
                probs.append("flee_wild.hp_below must be null or in [0,1]")
    return probs


def load_spec(path) -> dict:
    spec = json.loads(Path(path).read_text())
    probs = validate_spec(spec)
    if probs:
        raise ValueError(f"invalid spec {path}: {probs}")
    return spec


def effectiveness(move_type: str, foe_types) -> float:
    mult = 1.0
    for t in foe_types or []:
        mult *= _CHART.get(move_type, {}).get(t, 1.0)
    return mult


def journal_key(move_id: str, species: str, level) -> tuple:
    return (move_id, species, level)


def observed_min_damage(journal: dict | None, move_id: str,
                        species: str, level) -> float | None:
    """Least damage this move has been SEEN to do to this species at our
    current level — the player's remembered experience (HP bars are on
    screen; no computed internals). None until observed."""
    obs = (journal or {}).get(journal_key(move_id, species, level))
    return min(obs) if obs else None


def _hp_frac(mon: dict) -> float:
    hp, mx = mon.get("hp") or 0, mon.get("max_hp") or 0
    return hp / mx if mx else 1.0


def score_move(mv: dict, me: dict, foe: dict, spec: dict,
               journal: dict | None = None) -> dict:
    mtype = mv.get("type")
    power = mv.get("power") or 0
    eff = effectiveness(mtype, foe.get("types"))
    stab = spec.get("stab", 1.5) if mtype in (me.get("types") or []) else 1.0
    acc = (mv.get("accuracy") or 100) / 100.0
    score = power * eff * stab
    if spec.get("accuracy_weight", True):
        score *= acc
    # KO detection is EMPIRICAL (pamphlet standard, no computed internals):
    # the least damage this move has been observed to do to this species at
    # our level, gated by the spec's ko_margin. Unseen matchup -> no KO call.
    seen = observed_min_damage(journal, mv.get("id"),
                               foe.get("species"), me.get("level"))
    kos = (seen is not None
           and seen >= (foe.get("hp") or 1e9) * spec.get("ko_margin", 1.0))
    return {
        "index": mv.get("index"), "id": mv.get("id"),
        "power": power, "eff": eff, "stab": stab,
        "damage": seen, "acc": acc, "score": score, "kos": kos,
    }


def should_field_heal(obs: dict,
                      spec: dict | None = None) -> tuple[str, int] | None:
    """After a battle: spec-rule field heal (no turn cost) for the NEEDIEST
    party mon below the threshold. Returns (item, slot) or None."""
    spec = spec or DEFAULT_SPEC
    fh = spec.get("field_heal")
    if not fh:
        return None
    if (obs or {}).get("mode") != "overworld":
        return None
    item = fh.get("item")
    bag = (obs or {}).get("bag") or {}
    if not bag or bag.get(item, 0) < 1:
        return None
    worst, slot = 1.0, None
    for i, mon in enumerate((obs or {}).get("party") or []):
        if (mon.get("hp") or 0) <= 0:
            continue
        f = _hp_frac(mon)
        if f < fh.get("hp_below", 0.5) and f < worst:
            worst, slot = f, i + 1
    return (item, slot) if slot else None


def should_field_cure(obs: dict,
                      spec: dict | None = None) -> tuple[str, int] | None:
    """After a battle: cure a statused party mon per the spec's rules.
    Returns (item, slot) or None."""
    spec = spec or DEFAULT_SPEC
    if (obs or {}).get("mode") != "overworld":
        return None
    bag = (obs or {}).get("bag") or {}
    if not bag:
        return None
    for i, mon in enumerate((obs or {}).get("party") or []):
        if (mon.get("hp") or 0) <= 0:
            continue
        status = mon.get("status")
        if status in (None, "", "0", "NONE", "OK"):
            continue
        for rule in spec.get("field_cure") or []:
            if rule.get("status") == status \
                    and bag.get(rule.get("item"), 0) > 0:
                return (rule["item"], i + 1)
    return None


def choose_replacement(obs: dict, spec: dict | None = None) -> int | None:
    """The active mon fainted: which party slot comes in (1-based)."""
    spec = spec or DEFAULT_SPEC
    order = (spec.get("replacement") or {}).get("order", "healthiest")
    best, slot = -1.0, None
    for i, mon in enumerate((obs or {}).get("party") or []):
        if (mon.get("hp") or 0) <= 0:
            continue
        if order == "first_alive":
            return i + 1
        f = _hp_frac(mon)
        if f > best:
            best, slot = f, i + 1
    return slot


def should_switch(obs: dict, spec: dict | None = None,
                  ctx: dict | None = None) -> int | None:
    """Spec-driven mid-battle switch: which party slot comes in, or None.

    The policy could only ever fight with whoever was sent out, so the one
    lever on who fights was party order, and a Pokemon too weak to survive
    a turn could never be in a battle at all. That rules out a whole class
    of play the game itself supports.

    WHAT THE HARNESS SUPPLIES IS THE VERB. This asks the spec — which the
    model writes (policy_author.py, CLAIM_RULES) — and does what it says.
    No rule here knows why a switch might be worth a turn; the reasons are
    the model's, and it has to write them down as conditions to get them.

    A switch costs the turn and gives the foe a free hit. That is a fact
    about the game, not a rule about play, and the model prices it.
    """
    spec = spec or DEFAULT_SPEC
    ctx = ctx or {}
    b = (obs or {}).get("battle") or {}
    me = b.get("me") or {}
    kind = b.get("kind") or "wild"
    party = (obs or {}).get("party") or []
    used = ctx.setdefault("switched", {})
    for n, rule in enumerate(spec.get("switch") or []):
        to = rule.get("to")
        if not isinstance(to, int) or not (1 <= to <= len(party)):
            continue
        if used.get(n, 0) >= rule.get("max_uses", 1):
            continue
        if (ctx.get("turn") or 1) > rule.get("first_turns", 1):
            continue
        vs = rule.get("vs", "any")
        if vs != "any" and vs != kind:
            continue
        hb = rule.get("hp_below")
        if hb is not None and _hp_frac(me) >= hb:
            continue
        lead = rule.get("only_if_lead")
        if lead is not None and ctx.get("started_as") != lead:
            continue
        cand = party[to - 1]
        # switching to a fainted slot is not a decision, it is a no-op the
        # game refuses — and a refused input burns the turn without ticking
        # anything, the DISABLE deadlock all over again
        if (cand.get("hp") or 0) <= 0:
            continue
        if cand.get("species") == me.get("species"):
            continue        # already out
        used[n] = used.get(n, 0) + 1
        return to
    return None


def should_flee(obs: dict, spec: dict | None = None,
                ctx: dict | None = None) -> bool:
    """Spec-driven wild-flee decision. Trainers can never be fled."""
    spec = spec or DEFAULT_SPEC
    ctx = ctx or {}
    b = obs.get("battle") or {}
    if b.get("kind") != "wild":
        return False
    fw = spec.get("flee_wild") or {}
    if fw.get("when_traversal") and ctx.get("intent") == "traversal":
        return True
    hb = fw.get("hp_below")
    if hb is not None and _hp_frac(b.get("me") or {}) < hb:
        return True
    return False


def choose(obs: dict, spec: dict | None = None,
           ctx: dict | None = None) -> dict:
    """Return a battle op. Falls back to slot-1 fight if no data."""
    spec = spec or DEFAULT_SPEC
    ctx = ctx or {}
    b = obs.get("battle") or {}
    me, foe = b.get("me") or {}, b.get("foe") or {}
    kind = b.get("kind") or "wild"
    # DISABLE makes a slot unselectable. Choosing it anyway is not a wasted
    # turn — the game refuses the input, so the turn never resolves and the
    # disable counter never ticks down: a permanent deadlock. pure26 sat in
    # one trainer battle re-picking a disabled SCRATCH against a 9 HP foe,
    # no EXP, HP frozen, for thousands of logged "turns". Play anything
    # legal (even GROWL) and Disable expires on its own.
    dis = me.get("disabledSlot") or 0
    moves = [m for m in (me.get("moves") or [])
             if (m.get("pp") or 0) > 0 and m.get("index") != dis]
    if not moves:
        # nothing legal left: Struggle, but never by re-picking the
        # disabled slot, which would deadlock again
        alt = next((m.get("index") for m in (me.get("moves") or [])
                    if m.get("index") != dis), 1)
        return {"op": "battle_move", "index": alt}
    # in-battle item rules come first: spending the turn to heal beats
    # fainting (the model's rule decides the threshold and budget)
    bag = obs.get("bag") or {}
    items_used = ctx.setdefault("items_used", {})
    for rule in spec.get("battle_items") or []:
        item = rule.get("item")
        if not item or not bag or bag.get(item, 0) < 1:
            continue
        if items_used.get(item, 0) >= rule.get("max_uses", 2):
            continue
        if _hp_frac(me) >= rule.get("hp_below", 0.3):
            continue
        items_used[item] = items_used.get(item, 0) + 1
        return {"op": "battle_item", "item": item,
                "_why": f"heal with {item}"}
    scored = [score_move(m, me, foe, spec, ctx.get("journal")) for m in moves]
    damaging = [s for s in scored if (s["power"] or 0) > 0]
    # CATCH intent on a wild foe: weaken with the gentlest non-KO move to
    # the throw threshold (gen1 catch odds scale with missing hp), then
    # throw. The foe's first-seen hp stands in for its max.
    ca = spec.get("catch")
    if ctx.get("intent") == "catch" and kind == "wild" and ca:
        # IS THIS EVEN THE THING WE CAME FOR? The catch branch checked only
        # that the foe was wild and a ball was in the bag, so a subgoal
        # reading "the party holds a WATER or GRASS type" threw at whatever
        # walked into it — a WEEDLE joined the party and the objective it
        # was authored for stayed unmet, with the balls meant for an Oddish
        # spent on bugs. `want` comes from the subgoal's own done_when
        # (species from has_species, types from party_type, read through
        # any_of); a goal that just wants MORE Pokemon sends None and
        # nothing changes. Run rather than fight: knocking it out is a
        # wasted battle either way, and the grass will offer another.
        want = ctx.get("want")
        if want:
            sp = str(foe.get("species") or "").upper()
            ty = {str(t).upper() for t in (foe.get("types") or [])}
            if not ((want.get("species") and sp in want["species"])
                    or (want.get("types") and ty & want["types"])):
                return {"op": "battle_run",
                        "_why": f"{sp or 'this'} is not what this subgoal "
                                f"is for"}
        hp0 = ctx.setdefault("foe_hp0", foe.get("hp") or 1)
        frac = (foe.get("hp") or 0) / max(1, hp0)
        balls = ctx.get("balls", 0)
        bag = obs.get("bag") or {}
        have_ball = bag and bag.get(ca.get("ball"), 0) > 0
        if have_ball and balls < ca.get("max_balls", 3):
            safe = [s for s in damaging if not s["kos"]]
            safe.sort(key=lambda s: s["score"])
            # A NAMED TARGET IS NOT WORTH SOFTENING UP. Weakening pays only
            # if the damage can be controlled, and it cannot: this is a
            # PREDICTION that a move will not KO, made for a L32 starter
            # swinging at a L7 wild, and it is wrong exactly once before the
            # thing the subgoal was authored to catch is dead. The trade is
            # not close — a wasted ball is recoverable and a corpse is not —
            # so when we know what we came for, throw at whatever hp it has.
            if ctx.get("want"):
                safe = []
            if frac <= ca.get("throw_at_hp_frac", 0.7) or not safe:
                ctx["balls"] = balls + 1
                return {"op": "throw_ball", "ball": ca["ball"],
                        "_why": f"throw (foe at {frac:.0%})"}
            return {"op": "battle_move", "index": safe[0]["index"],
                    "_why": f"weaken with {safe[0]['id']}"}
        # THE BALLS FOR THIS BATTLE ARE SPENT — AND KILLING IT IS THE ONE
        # OUTCOME THAT HELPS NOTHING. Falling through to normal move
        # selection meant a L32 CHARMELEON knocking out the very ODDISH the
        # subgoal was authored to catch, so the wild that finally matched
        # was destroyed and the hunt started over. Leave it alive: the
        # grass will offer another, and the party keeps its balls for it.
        # Only when a target was NAMED — a party_size goal that will take
        # anything has nothing to protect.
        if ctx.get("want") and have_ball is not None:
            return {"op": "battle_run",
                    "_why": "out of balls for this one; leave it alive"}
    by_index = {m.get("index"): m for m in moves}
    best_dmg = max(damaging, key=lambda s: s["score"]) if damaging else None
    best_is_physical = bool(
        best_dmg
        and (by_index.get(best_dmg["index"]) or {}).get("category")
        != "special")
    # deliberate setup-move rules come before damage ranking
    used = ctx.setdefault("used", {})
    for rule in spec.get("setup") or []:
        mid = rule.get("move")
        mv = next((m for m in moves if m.get("id") == mid), None)
        if not mv:
            continue
        if used.get(mid, 0) >= rule.get("max_uses", 1):
            continue
        if (ctx.get("turn") or 1) > rule.get("first_turns", 2):
            continue
        if _hp_frac(me) < rule.get("min_hp_frac", 0.5):
            continue
        vs = rule.get("vs", "trainer")
        if vs != "any" and vs != kind:
            continue
        if rule.get("only_if_best_physical") and not best_is_physical:
            continue
        used[mid] = used.get(mid, 0) + 1
        return {"op": "battle_move", "index": mv["index"],
                "_why": f"setup {mid} (use {used[mid]})"}
    pool = damaging or scored     # only status moves left -> use them
    if spec.get("avoid_status_moves", True) and damaging:
        pool = damaging
    if spec.get("prefer_ko", True):
        kos = [s for s in pool if s["kos"]]
        if kos:
            kos.sort(key=lambda s: -s["acc"])   # surest KO
            return {"op": "battle_move", "index": kos[0]["index"],
                    "_why": f"KO with {kos[0]['id']}"}
    pool.sort(key=lambda s: -s["score"])
    best = pool[0]
    return {"op": "battle_move", "index": best["index"],
            "_why": f"{best['id']} score={best['score']:.1f} eff={best['eff']}"}


SPECS = {"typed_v0": DEFAULT_SPEC}


if __name__ == "__main__":
    # smoke: score Squirtle's Tackle/Bubble vs a Rock/Ground Geodude
    demo = {"battle": {
        "kind": "trainer",
        "me": {"level": 10, "species": "SQUIRTLE", "types": ["WATER"],
               "hp": 20, "max_hp": 30,
               "stats": {"attack": 20, "special": 25, "defense": 18},
               "moves": [
                   {"index": 1, "id": "TACKLE", "type": "NORMAL", "power": 35,
                    "category": "physical", "accuracy": 95, "pp": 30},
                   {"index": 2, "id": "BUBBLE", "type": "WATER", "power": 20,
                    "category": "special", "accuracy": 100, "pp": 30}]},
        "foe": {"level": 10, "species": "GEODUDE",
                "types": ["ROCK", "GROUND"], "hp": 30,
                "stats": {"defense": 25, "special": 15}}}}
    print("cold (score only):", choose(demo))
    seen = {journal_key("BUBBLE", "GEODUDE", 10): [34, 31]}
    print("after observations:", choose(demo, ctx={"journal": seen}))
    tw = {"battle": dict(demo["battle"],
                         me=dict(demo["battle"]["me"], moves=demo["battle"]["me"]["moves"] + [
                             {"index": 3, "id": "TAIL_WHIP", "type": "NORMAL",
                              "power": 0, "category": "status",
                              "accuracy": 100, "pp": 30}]))}
    spec = dict(DEFAULT_SPEC,
                setup=[{"move": "TAIL_WHIP", "max_uses": 1, "vs": "any"}])
    ctx = {"turn": 1, "intent": "fight"}
    print(choose(tw, spec, ctx), "then", choose(tw, spec, dict(ctx, turn=2)))
