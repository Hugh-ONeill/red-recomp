#!/usr/bin/env python3
"""The missing rung refuses a reason that bars the way into a place the
run has already walked in, and "indicating" is a hedge like "implying".

Two failures in one evening, both on "Travel through Rock Tunnel".

The missing rung inserted "Give a FRESH WATER to the guards at the Route
5 and 6 gates" ahead of it, because "the guards at the gates of Route 5
and 6 block access to the Rock Tunnel until they are given a drink" --
not true of this game, and refuted by the run's own ledger, which held
four chambers of Rock Tunnel walked. The leg was pushed two places back
and the chain set off the long way round.

Then check-done crossed the leg off before it ran: "The run has
previously exited Rock Tunnel to Route 10, indicating the tunnel has been
traversed". What it had exited onto was ROUTE_10|0,4, the part it went IN
from; coming back out the way you came in is not traversing. The word
doing the work was a hedge the inference list did not hold.

Only the place the way is barred TO is refused, never every place the
sentence mentions: a guard who really does bar a road stands on a route
the run has walked, and saying so has to stay sayable.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                        # noqa: E402
from pinned_world import pinned                           # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

WALKED = {"ROCK_TUNNEL_1F|14,2": 2, "ROCK_TUNNEL_B1F|26,2": 1,
          "ROUTE_5|6,0": 3, "ROUTE_9|50,6": 9, "ROUTE_10|0,4": 4,
          "CERULEAN_CITY|26,7": 7}

def barred(why):
    with pinned(explored={r: {} for r in WALKED}, visits=WALKED):
        return A._blocks_a_place_you_have_walked(why)

# ---- the reason that moved the leg -------------------------------------------
ck("a way barred into a place already walked is caught",
   barred("The guards at the gates of Route 5 and 6 block access to the "
          "Rock Tunnel until they are given a drink.") == "ROCK_TUNNEL", "")
ck("...naming the place, not the guards' own route",
   barred("The guards at the gates of Route 5 and 6 block access to the "
          "Rock Tunnel until they are given a drink.") != "ROUTE_5")
ck("a floor is one place with its building",
   barred("something seals the entrance to Rock Tunnel") == "ROCK_TUNNEL")
ck("other barring words count too",
   all(barred(f"the gate {v} the way into Cerulean City") == "CERULEAN_CITY"
       for v in ("blocks", "bars", "seals", "prevents", "closes", "locks")), "")

# ---- what must stay sayable ---------------------------------------------------
ck("a guard standing on a route the run has walked is not itself a bar",
   barred("Give a FRESH WATER to the guards at the Route 5 and 6 gates") is None)
ck("...nor is a place merely mentioned",
   barred("The Rock Tunnel is dark and a Pokemon must know FLASH") is None)
ck("a way barred into somewhere never walked is allowed",
   barred("the guards block the way into Saffron City until given a drink") is None)
ck("an empty reason says nothing", barred("") is None and barred(None) is None)

# ---- the hedge ----------------------------------------------------------------
ck("'indicating' is inference",
   A._inferred("The run has previously exited Rock Tunnel to Route 10, "
               "indicating the tunnel has been traversed."))
ck("...in every ending", all(A._inferred(f"X, which {w} it is done")
                             for w in ("indicates", "indicated")))
ck("...and 'indicative of' too", A._inferred("this is indicative of a cleared tunnel"))
ck("a fact you can point at is still not inference",
   not A._inferred("EVENT_BEAT_LT_SURGE has fired and the THUNDERBADGE is in the bag")
   and not A._inferred("the party stands in LAVENDER_TOWN, visited twice"))

# ---- it sits in the rung, before the model is asked anything more -------------
src = (ROOT / "planner" / "author.py").read_text()
i_inf = src.index("if _inferred(_why):")
i_new = src.index("_walked_in = _blocks_a_place_you_have_walked(_why, observed)")
i_done = src.index("if check_already_done(ins, start, model, observed=observed):")
ck("the rung asks it after the inference gate and before the done question",
   i_inf < i_new < i_done)
ck("...and a turned-down proposal is quoted back, so the re-ask is not a re-roll",
   'turned_down.append((ins, f"you have already walked in {_walked_in}"))' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
