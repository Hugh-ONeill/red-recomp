#!/usr/bin/env python3
"""Who comes in after a faint can be about the FIGHT, not just about hp.

The whole vocabulary for this was `order: "healthiest" | "first_alive"`,
and neither says anything about what is standing across from you. Run 16
replaced a fainted mon 86 times and every one was the healthiest rule; of
101 party reorders the model wrote for itself, 96 said in their own words
they were putting a low-level member in front to TRAIN it and NOT ONE was
about the matchup (user, 2026-09-12: "it only switches around the team to
put mons in first to train them").

Some of that is the round economy, which is not this file's to fix. But
part of it was that the language had no words for it: the type chart has
sat in battle_policy.py the whole time, read one way, to score OUR moves.
`resists` and `best_matchup` read it the other way.

WHAT IS AND IS NOT READ. The FOE's types, not its moves — a moveset is not
on screen until it is used, so its own types are the honest proxy. But OUR
side is read from THE MOVES IT HOLDS, because that is the half we can
see: GYARADOS is the right lead into LORELEI for carrying THUNDERBOLT, and
by typing alone WATER/FLYING into ICE/WATER reads neutral and it looks
like nobody special (user, 2026-09-12: "it should be considering the moves
it has not just the types"). Type and power are on the summary screen for
every party member; the shim publishes them for the bench as of the same
day, having previously carried them only for the two mons in the fight.
Which order to use, and whether any of this should decide, stays the
model's: this only knows how to carry out the four it can name.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import battle_policy as B                                  # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


def mon(sp, types, hp, mx=100):
    return {"species": sp, "types": types, "hp": hp, "max_hp": mx}


# a WATER foe: the GRASS type walls it, the FIRE type is eaten by it
FOE = {"battle": {"foe": {"species": "STARMIE", "types": ["WATER"]}}}
PARTY = [mon("CHARIZARD", ["FIRE", "FLYING"], 0),      # 1 fainted
         mon("VILEPLUME", ["GRASS", "POISON"], 40),    # 2 resists water
         mon("DODRIO", ["NORMAL", "FLYING"], 95),      # 3 healthiest
         mon("NIDOQUEEN", ["POISON", "GROUND"], 60)]   # 4 neutral
OBS = dict(FOE, party=PARTY)


def pick(order, **rp):
    return B.choose_replacement(
        OBS, {"replacement": dict(order=order, **rp)})


# ---- the chart, both ways ----------------------------------------------
ck("water lands soft on a grass type", B.incoming(["WATER"], ["GRASS"]) < 1.0)
ck("water lands hard on a fire type", B.incoming(["WATER"], ["FIRE"]) > 1.0)
ck("a dual type takes the WORST of the foe's types",
   B.incoming(["WATER", "PSYCHIC"], ["POISON", "GROUND"]) > 1.0)
ck("bare types still work for a caller that has only those",
   B.outgoing(["GRASS"], ["WATER"]) > 1.0
   and B.outgoing(["FIRE"], ["WATER"]) < 1.0)

# THE MOVES IT HOLDS. Gyarados into Lorelei: WATER/FLYING is neutral into
# ICE/WATER and the typing says nothing, while THUNDERBOLT is double
# against her WATER half.
GYARA = {"species": "GYARADOS", "types": ["WATER", "FLYING"],
         "hp": 60, "max_hp": 100,
         "moves": [{"id": "THUNDERBOLT", "type": "ELECTRIC", "power": 95},
                   {"id": "BITE", "type": "NORMAL", "power": 60}]}
ck("a move it holds beats the typing it happens to be",
   B.outgoing(GYARA, ["WATER"]) == 2.0
   and B.outgoing(["WATER", "FLYING"], ["WATER"]) < 2.0)
ck("a status move lands no multiplier",
   B.outgoing({"types": ["NORMAL"],
               "moves": [{"id": "GROWL", "type": "NORMAL", "power": 0}]},
              ["WATER"]) == 0.0)
ck("a mon whose moves carry no types falls back to its own",
   B.outgoing({"types": ["GRASS"], "moves": [{"id": "ABSORB"}]},
              ["WATER"]) > 1.0)
ck("...and so does one with no moves at all",
   B.outgoing({"types": ["GRASS"], "moves": []}, ["WATER"]) > 1.0)
ck("no types either way is neutral, not an error",
   B.incoming([], ["GRASS"]) == 1.0 and B.outgoing(["GRASS"], []) == 1.0)

# ---- the four orders ----------------------------------------------------
ck("healthiest still means healthiest", pick("healthiest") == 3)
ck("first_alive still means the first one standing", pick("first_alive") == 2)
ck("resists sends the one the foe's types hurt least", pick("resists") == 2)
ck("best_matchup sends the one that hits back hardest for what it takes",
   pick("best_matchup") == 2)
ck("a fainted member is never sent in",
   all(pick(o) != 1 for o in
       ("healthiest", "first_alive", "resists", "best_matchup")))

# THE TWO ORDERS ARE NOT THE SAME RULE. Both of these resist the WATER foe
# exactly as well, so `resists` falls to its tie-break and takes the
# healthier one — which cannot hurt the foe at all. `best_matchup` takes
# the one that trades.
SWAP = [mon("CHARIZARD", ["FIRE"], 0),
        mon("VILEPLUME", ["GRASS", "POISON"], 50),   # resists AND hits back
        mon("VAPOREON", ["WATER"], 95)]              # resists, hits for half
W = {"battle": {"foe": {"species": "STARMIE", "types": ["WATER"]}},
     "party": SWAP}
ck("resists ties on damage taken and breaks it on health",
   B.choose_replacement(W, {"replacement": {"order": "resists"}}) == 3)
ck("...while best_matchup takes the one that can actually hurt it",
   B.choose_replacement(W, {"replacement": {"order": "best_matchup"}}) == 2)

# AN IMMUNITY IS WORTH MORE THAN A DOUBLE RESIST, so the ratio's floor
# sits below the chart's smallest real multiplier instead of on it.
# THE CASE THAT PROMPTED IT: by typing, the Lapras walls her better and
# Gyarados reads neutral; by the moves they hold, Gyarados is the answer.
LOR = {"battle": {"foe": {"species": "DEWGONG", "types": ["WATER", "ICE"]}},
       "party": [dict(GYARA),
                 {"species": "LAPRAS", "types": ["WATER", "ICE"],
                  "hp": 90, "max_hp": 100,
                  "moves": [{"id": "SURF", "type": "WATER", "power": 95}]}]}
ck("resists reads the typing and takes the wall",
   B.choose_replacement(LOR, {"replacement": {"order": "resists"}}) == 2)
ck("...and best_matchup takes the one holding the move that hurts",
   B.choose_replacement(LOR, {"replacement": {"order": "best_matchup"}}) == 1)

ck("a foe that cannot touch you at all outscores one that barely can",
   B.choose_replacement(
       {"battle": {"foe": {"species": "JOLTEON", "types": ["ELECTRIC"]}},
        "party": [mon("DUGTRIO", ["GROUND"], 50),        # immune
                  mon("VICTREEBEL", ["GRASS", "POISON"], 50)]},
       {"replacement": {"order": "best_matchup"}}) == 1)

# ---- the health floor ---------------------------------------------------
THIN = [mon("CHARIZARD", ["FIRE"], 0),
        mon("VILEPLUME", ["GRASS", "POISON"], 4),   # walls it, nearly dead
        mon("DODRIO", ["NORMAL", "FLYING"], 95)]
T = dict(FOE, party=THIN)
ck("without a floor the wall goes in however thin it is",
   B.choose_replacement(T, {"replacement": {"order": "resists"}}) == 2)
ck("a floor keeps it on the bench",
   B.choose_replacement(
       T, {"replacement": {"order": "resists", "min_hp_frac": 0.2}}) == 3)
ALL_THIN = [mon("A", ["GRASS"], 0), mon("B", ["GRASS"], 3),
            mon("C", ["FIRE"], 2)]
ck("...but a floor nobody clears sends SOMEBODY, never nobody",
   B.choose_replacement(dict(FOE, party=ALL_THIN),
                        {"replacement": {"order": "resists",
                                         "min_hp_frac": 0.9}}) is not None)

# ---- no foe to read -----------------------------------------------------
ck("outside a fight a type order falls back to health, not to slot 1",
   B.choose_replacement({"party": PARTY},
                        {"replacement": {"order": "resists"}}) == 3)
ck("a whole party fainted picks nobody",
   B.choose_replacement(dict(FOE, party=[mon("X", ["FIRE"], 0)]),
                        {"replacement": {"order": "resists"}}) is None)

# ---- the model can write it, and cannot write nonsense ------------------
for o in ("healthiest", "first_alive", "resists", "best_matchup"):
    ck(f"a spec may say {o}",
       not [p for p in B.validate_spec({"replacement": {"order": o}})
            if "replacement" in p])
ck("...and may not say something else",
   any("replacement.order" in p for p in
       B.validate_spec({"replacement": {"order": "prettiest"}})))
ck("the floor is checked too",
   any("min_hp_frac" in p for p in B.validate_spec(
       {"replacement": {"order": "resists", "min_hp_frac": 5}})))

# ---- and the model is TOLD the words exist -----------------------------
ck("the spec DSL the author is handed names them",
   "best_matchup" in (ROOT / "planner" / "policy_author.py").read_text())
ck("...and says which facts they weigh",
   "its moves are not visible until it uses them"
   in (ROOT / "planner" / "policy_author.py").read_text())

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
