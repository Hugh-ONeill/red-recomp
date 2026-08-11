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
                             the item if the lead has it and the bag has one

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
    "flee_wild": {"when_traversal": True, "hp_below": None},
    "battle_items": [],
    "field_heal": None,
    "field_cure": [],
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


def should_field_heal(obs: dict, spec: dict | None = None) -> str | None:
    """After a battle: spec-rule field heal (no turn cost). Returns the
    item to use, or None."""
    spec = spec or DEFAULT_SPEC
    fh = spec.get("field_heal")
    if not fh:
        return None
    if (obs or {}).get("mode") != "overworld":
        return None
    lead = ((obs or {}).get("party") or [{}])[0]
    if (lead.get("hp") or 0) <= 0:
        return None
    if _hp_frac(lead) >= fh.get("hp_below", 0.5):
        return None
    item = fh.get("item")
    bag = (obs or {}).get("bag") or {}
    return item if bag and bag.get(item, 0) > 0 else None


def should_field_cure(obs: dict, spec: dict | None = None) -> str | None:
    """After a battle: cure the lead's status per the spec's rules.
    Returns the item to use, or None."""
    spec = spec or DEFAULT_SPEC
    if (obs or {}).get("mode") != "overworld":
        return None
    lead = ((obs or {}).get("party") or [{}])[0]
    if (lead.get("hp") or 0) <= 0:
        return None
    status = lead.get("status")
    if status in (None, "", "0", "NONE", "OK"):
        return None
    bag = (obs or {}).get("bag") or {}
    for rule in spec.get("field_cure") or []:
        if rule.get("status") == status and bag \
                and bag.get(rule.get("item"), 0) > 0:
            return rule["item"]
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
    moves = [m for m in (me.get("moves") or [])
             if (m.get("pp") or 0) > 0]
    if not moves:
        return {"op": "battle_move", "index": 1}   # Struggle / no PP
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
    by_index = {m.get("index"): m for m in moves}
    best_dmg = max(damaging, key=lambda s: s["score"]) if damaging else None
    best_is_physical = bool(
        best_dmg
        and (by_index.get(best_dmg["index"]) or {}).get("category")
        != "special")
    # deliberate setup-move rules come before damage ranking
    kind = b.get("kind") or "wild"
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
