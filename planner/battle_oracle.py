#!/usr/bin/env python3
"""Battle oracle: the measuring stick for the battle policy (CLAIM_RULES §2).

The oracle uses engine-truth damage (the battle_probe op -> obs.battle.probe)
to pick the EV-best action: a guaranteed KO if one exists (min-roll damage
>= foe HP), else the highest mid-roll damage. It is a 1-ply damage referee;
a full checkpoint-search playout oracle (opponent replies, reseeded RNG,
multi-turn) is the heavier follow-up. The oracle NEVER pilots the record run
— it only scores the policy.

score_turn compares the policy's move to the oracle's on one decision and
returns the agreement + the EV (damage) gap, so a battle set yields an
agreement rate and total damage left on the table.
"""

from __future__ import annotations


def oracle_pick(probe: dict) -> dict | None:
    """Best move index by engine-truth damage. probe = obs.battle.probe."""
    moves = [m for m in (probe or {}).get("moves") or []
             if (m.get("pp") or 0) > 0 and m.get("dmg_mid") is not None]
    if not moves:
        return None
    kos = [m for m in moves if m.get("ko_min")]      # guaranteed KO
    if kos:
        # cheapest guaranteed KO = fewest wasted, but any KO ends the turn;
        # pick the highest mid dmg among guaranteed KOs (robust to bad luck)
        best = max(kos, key=lambda m: m.get("dmg_mid") or 0)
        return {"index": best["index"], "id": best["id"], "reason": "ko_min",
                "dmg_mid": best.get("dmg_mid")}
    best = max(moves, key=lambda m: m.get("dmg_mid") or 0)
    return {"index": best["index"], "id": best["id"], "reason": "max_dmg",
            "dmg_mid": best.get("dmg_mid")}


def score_turn(policy_index: int, probe: dict) -> dict:
    """Compare the policy's chosen move-index to the oracle's on one turn."""
    o = oracle_pick(probe)
    if not o:
        return {"scoreable": False}
    by_idx = {m["index"]: m for m in probe.get("moves") or []}
    pol_dmg = (by_idx.get(policy_index) or {}).get("dmg_mid") or 0
    ora_dmg = o.get("dmg_mid") or 0
    return {
        "scoreable": True,
        "agree": policy_index == o["index"],
        "policy_index": policy_index, "oracle_index": o["index"],
        "oracle_reason": o["reason"],
        "policy_dmg": pol_dmg, "oracle_dmg": ora_dmg,
        "dmg_gap": max(0.0, ora_dmg - pol_dmg),   # EV left on the table
    }
