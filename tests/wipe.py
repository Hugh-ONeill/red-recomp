#!/usr/bin/env python3
"""A knockout is said out loud, whatever op was in flight.

There was a wipe detector and it lived on the battle-resume path inside
run_op, so it only fired when the op handed back a battle it could read.
On Route 10 the walk south to Lavender was engaged eight cells from the
edge, the party lost, and:

  * the cross op came back with a terrain theory — "couldn't reach south
    edge gap (9,71), stuck at (10,64) ... 2 LEDGE tile(s) lie along that
    line" — which is a claim about ground, made about a walk a fight
    stopped;
  * the settle that followed found no map at all (the blackout sequence is
    not the overworld), so post_map was None and the guard fell through;
  * nothing was recorded, and fourteen rounds later the model was still
    reasoning "I have already tried the south exit of Route 10 and was
    blocked by ledges", hunting an imaginary other way out of Rock Tunnel.

gen1 blacks you out by halving your money to the exact rupee, healing the
party, and putting you at the Center you last healed at. Nothing else in
the game does all three. No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E          # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def bare():
    ex = object.__new__(E.Executor)
    ex._faint_at = None
    ex._cur_target = "map:LAVENDER_TOWN"
    ex._blackouts = {}
    ex._blackout_lead = {}
    ex._wipe_note = None
    ex._wipe_watch = None
    ex.log = lambda *a, **k: None
    return ex


def obs(map_id, region, money, hp, maxhp=78, n=2):
    return {"map": {"id": map_id, "region": region},
            "money": money,
            "party": [{"hp": hp, "max_hp": maxhp, "level": 24}] * n}


def main():
    print("the knockout the op talked over:")
    ex = bare()
    ex._watch_for_a_wipe(obs("ROUTE_10", "14,52", 18264, 30))
    note = ex._watch_for_a_wipe(
        obs("ROCK_TUNNEL_POKECENTER", "0,3", 9132, 78))
    check("money halved + party healed + a new map is a wipe", bool(note))
    check("...and it names where it happened",
          note and "ROUTE_10" in note, note)
    check("...and where you woke",
          note and "ROCK_TUNNEL_POKECENTER" in note, note)
    check("...and retracts the last op's reason",
          note and "WHATEVER THE LAST OP SAID" in note, note)
    check("...and arms the walk-back to where it happened",
          ex._faint_at == "ROUTE_10|14,52", ex._faint_at)
    check("...and counts against this goal",
          ex._blackouts.get("map:LAVENDER_TOWN") == 1, ex._blackouts)

    print("\nthings that are not a wipe:")
    ex = bare()
    ex._watch_for_a_wipe(obs("VERMILION_CITY", "18,0", 9000, 78))
    check("a heal at a Center: healed and a new map, but no money lost",
          not ex._watch_for_a_wipe(obs("VERMILION_POKECENTER", "0,3",
                                       9000, 78)))
    ex = bare()
    ex._watch_for_a_wipe(obs("VERMILION_CITY", "18,0", 9000, 78))
    check("a purchase: money down and healed, but not HALVED",
          not ex._watch_for_a_wipe(obs("VERMILION_MART", "0,2", 5600, 78)))
    ex = bare()
    ex._watch_for_a_wipe(obs("ROUTE_10", "14,52", 9000, 30))
    check("a won battle mid-warp: a new map, but nothing else holds",
          not ex._watch_for_a_wipe(obs("ROCK_TUNNEL_1F", "4,2", 9000, 30)))
    ex = bare()
    ex._watch_for_a_wipe(obs("ROUTE_10", "14,52", 9000, 78))
    check("standing still: no map change, no claim",
          not ex._watch_for_a_wipe(obs("ROUTE_10", "14,52", 4500, 78)))
    ex = bare()
    ex._watch_for_a_wipe(obs("ROUTE_10", "14,52", 18264, 30))
    check("halved and moved, but somebody is still hurt",
          not ex._watch_for_a_wipe(
              obs("ROCK_TUNNEL_POKECENTER", "0,3", 9132, 40)))

    print("\n" + "-" * 60)
    if FAILS:
        print(f"A WIPE CAN STILL PASS UNSAID: {len(FAILS)} case(s)")
        return 1
    print("a wipe is named where it is noticed, and nothing else is")
    return 0


if __name__ == "__main__":
    sys.exit(main())
