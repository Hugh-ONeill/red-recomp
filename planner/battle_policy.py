#!/usr/bin/env python3
"""Battle policy: choose a battle action from the observation.

The policy is driven by a SPEC (a small dict of rules/params) — "rules as
data" per CLAIM_RULES v1, so it is the model-authorable artifact. This file
provides the interpreter + a hand-seeded v0 spec for spine/oracle validation;
the record run requires a model-authored spec.

choose(obs, spec) -> op dict for the executor (e.g. {"op":"battle_move",
"index":2}). Reads only battle-visible fields: both actives' species, level,
types, stats, hp, status, and our move list with type/power/category.
"""

from __future__ import annotations

import json
from pathlib import Path

_CHART = json.loads((Path(__file__).parent / "type_chart.json").read_text())

# hand-seeded starting spec; a model authors/tunes this for the record run.
DEFAULT_SPEC = {
    "name": "typed_v0",
    "stab": 1.5,          # same-type attack bonus
    "prefer_ko": True,     # a move estimated to KO wins over raw score
    "avoid_status_moves": True,   # don't burn turns on 0-power moves
    "switch_when": None,   # v0 never switches voluntarily (forced only)
}


def effectiveness(move_type: str, foe_types) -> float:
    mult = 1.0
    for t in foe_types or []:
        mult *= _CHART.get(move_type, {}).get(t, 1.0)
    return mult


def _gen1_damage(level, power, atk, dfn, stab, eff) -> float:
    """Rough gen1 damage (no random spread / crit) for KO detection."""
    if not power or not atk or not dfn:
        return 0.0
    base = ((2 * level / 5 + 2) * power * atk / dfn) / 50 + 2
    return base * stab * eff


def score_move(mv: dict, me: dict, foe: dict, spec: dict) -> dict:
    mtype = mv.get("type")
    power = mv.get("power") or 0
    eff = effectiveness(mtype, foe.get("types"))
    stab = spec.get("stab", 1.5) if mtype in (me.get("types") or []) else 1.0
    my_stats = me.get("stats") or {}
    foe_stats = foe.get("stats") or {}
    if mv.get("category") == "special":
        atk, dfn = my_stats.get("special"), foe_stats.get("special")
    else:
        atk, dfn = my_stats.get("attack"), foe_stats.get("defense")
    dmg = _gen1_damage(me.get("level") or 5, power, atk, dfn, stab, eff)
    acc = (mv.get("accuracy") or 100) / 100.0
    return {
        "index": mv.get("index"), "id": mv.get("id"),
        "power": power, "eff": eff, "stab": stab,
        "damage": dmg, "acc": acc,
        # ranking score: expected damage, weighted by accuracy
        "score": power * eff * stab * acc,
        "kos": dmg >= (foe.get("hp") or 1e9),
    }


def choose(obs: dict, spec: dict | None = None) -> dict:
    """Return a battle op. Falls back to slot-1 fight if no data."""
    spec = spec or DEFAULT_SPEC
    b = obs.get("battle") or {}
    me, foe = b.get("me") or {}, b.get("foe") or {}
    moves = [m for m in (me.get("moves") or [])
             if (m.get("pp") or 0) > 0]
    if not moves:
        return {"op": "battle_move", "index": 1}   # Struggle / no PP
    scored = [score_move(m, me, foe, spec) for m in moves]
    damaging = [s for s in scored if (s["power"] or 0) > 0]
    pool = damaging or scored     # only status moves left -> use them
    if spec.get("avoid_status_moves") and damaging:
        pool = damaging
    # prefer a KO if available and the spec asks for it
    if spec.get("prefer_ko"):
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
        "me": {"level": 10, "types": ["WATER"],
               "stats": {"attack": 20, "special": 25, "defense": 18},
               "moves": [
                   {"index": 1, "id": "TACKLE", "type": "NORMAL", "power": 35,
                    "category": "physical", "accuracy": 95, "pp": 30},
                   {"index": 2, "id": "BUBBLE", "type": "WATER", "power": 20,
                    "category": "special", "accuracy": 100, "pp": 30}]},
        "foe": {"level": 10, "types": ["ROCK", "GROUND"], "hp": 30,
                "stats": {"defense": 25, "special": 15}}}}
    print(choose(demo))
