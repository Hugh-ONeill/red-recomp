#!/usr/bin/env python3
"""LAST_MAP doors are auditable, and the recorder refuses their one lie.

The 2026-08-19 TODO feared "where the door leads depends on how you
entered" and sketched three graph-model rebuilds. Checked against the
engine and against run 14's own 155 recorded LAST_MAP edges, the premise
is narrower: the sentinel resolves to the last OUTDOOR ground stood on,
wLastMap is written only on outside-tileset maps, gates force it by rule
(FieldDefaults LAST_MAP_REWRITES), and every interior's mouths in vanilla
feed from ONE outdoor map — so every LAST_MAP door is destination-stable
and no graph rebuild is warranted. What WAS missing:

  * the offline audit treated LAST_MAP as "agrees with anything", so the
    doors most likely to carry a drift-class lie were the ones it could
    not see. It now decides them: rewrite rule > unique outdoor feeder >
    feeder set > at-least-outdoors.
  * the live recorder would write a returns-door edge that landed
    indoors — a respawn or script, never the door. It now drops it, the
    same way it drops blackout teleports.

The one-outdoor-feeder fact is asserted here against the shipped data:
if a mod or data change ever breaks it, this test reopens the question
instead of letting the audit quietly mis-judge.

Audit rules run against the real engine data (skipped without it); the
recorder guard runs on synthetic worlds.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

import audit_doors as A       # noqa: E402
from seam_cell import ex_with, obs_at, check, FAILS   # noqa: E402

GAME = Path.home() / "Developer/gen1recomp"


def audit_cases():
    tbl = A.warp_tables(GAME)
    ts = A.tilesets(GAME)
    rew = A.lastmap_rewrites(GAME)
    fs = A.outdoor_feeders(tbl, ts)

    check("the rewrite table parses whole (Route 22's gate has 2 rules)",
          len(rew["ROUTE_22_GATE"]["rules"]) == 2
          and rew["UNDERGROUND_PATH_ROUTE_5"]["rules"][0][2] == "ROUTE_5",
          rew)
    check("a Pokemon Center's one outdoor feeder is its town",
          fs.get("VERMILION_POKECENTER") == {"VERMILION_CITY"},
          fs.get("VERMILION_POKECENTER"))
    check("Victory Road's mouths all feed from Route 23",
          fs.get("VICTORY_ROAD_1F") == {"ROUTE_23"}
          and fs.get("VICTORY_ROAD_2F") == {"ROUTE_23"},
          (fs.get("VICTORY_ROAD_1F"), fs.get("VICTORY_ROAD_2F")))
    # THE STABILITY CLAIM ITSELF: every interior with several outdoor
    # feeders must carry a rewrite that decides between them. Today that
    # is ROUTE_22_GATE alone. If this ever fails, LAST_MAP doors have a
    # genuinely history-dependent case and the graph-model question the
    # 2026-08-19 TODO asked reopens.
    multi = {k for k, v in fs.items() if len(v) > 1}
    check("every multi-feeder interior is decided by a rewrite",
          all(k in rew for k in multi), sorted(multi))

    def v(mp, x, y, got):
        return A.lastmap_verdict(mp, x, y, got, ts, rew, fs)[0]

    check("gate north door recorded as Route 23 agrees",
          v("ROUTE_22_GATE", 4, 0, "ROUTE_23"))
    check("gate north door recorded as Route 22 is a lie",
          not v("ROUTE_22_GATE", 4, 0, "ROUTE_22"))
    check("gate south door recorded as Route 22 agrees",
          v("ROUTE_22_GATE", 4, 7, "ROUTE_22"))
    check("a Center door recorded as its town agrees",
          v("VERMILION_POKECENTER", 3, 7, "VERMILION_CITY"))
    check("a Center door recorded as another city is a lie",
          not v("VERMILION_POKECENTER", 3, 7, "SAFFRON_CITY"))
    check("Victory Road recorded as the Plateau is a lie",
          not v("VICTORY_ROAD_1F", 8, 17, "INDIGO_PLATEAU"))
    check("an unknown interior may still not claim an indoor landing",
          v("SOME_MODDED_HOUSE", 2, 7, "PALLET_TOWN")
          and not v("SOME_MODDED_HOUSE", 2, 7, "VERMILION_POKECENTER"))


CENTER = "VERMILION_POKECENTER|0,3"


def door_obs(returns=True):
    o = obs_at(CENTER)
    o["map"]["warps"] = [{"x": 3, "y": 7, "dest": "VERMILION_CITY",
                          "returns": returns or None, "reachable": True}]
    return o


def landing(region, outdoor):
    o = obs_at(region)
    if outdoor is not None:
        o["map"]["outdoor"] = outdoor
    return o


def recorder_cases():
    step = {"x": 3, "y": 7}

    ex = ex_with()
    ex.note_transition(door_obs(), step, landing("CELADON_MART_1F|1,1",
                                                 outdoor=False))
    check("a returns-door crossing that settles indoors is not recorded",
          "3,7" not in (ex.explored.get(CENTER) or {}),
          ex.explored.get(CENTER))

    ex = ex_with()
    ex.note_transition(door_obs(), step, landing("VERMILION_CITY|18,0",
                                                 outdoor=True))
    check("...while its honest outdoor crossing records as ever",
          (ex.explored.get(CENTER, {}).get("3,7") or {}).get("to")
          == "VERMILION_CITY|18,0", ex.explored.get(CENTER))

    ex = ex_with()
    ex.note_transition(door_obs(), step, landing("CELADON_MART_1F|1,1",
                                                 outdoor=None))
    check("an obs from an older shim (no outdoor field) changes nothing",
          (ex.explored.get(CENTER, {}).get("3,7") or {}).get("to")
          == "CELADON_MART_1F|1,1", ex.explored.get(CENTER))

    ex = ex_with()
    ex.note_transition(door_obs(returns=False), step,
                       landing("CELADON_MART_1F|1,1", outdoor=False))
    check("an ordinary door may land indoors (guard is returns-only)",
          (ex.explored.get(CENTER, {}).get("3,7") or {}).get("to")
          == "CELADON_MART_1F|1,1", ex.explored.get(CENTER))


def main():
    print("the audit's LAST_MAP rules:")
    if GAME.is_dir():
        audit_cases()
    else:
        print("  SKIPPED — no engine checkout at " + str(GAME))
    print("\nthe recorder's guard:")
    recorder_cases()

    print(f"\n{'-' * 60}")
    if FAILS:
        print(f"LAST_MAP DOORS ARE BEING MISJUDGED: {len(FAILS)} case(s)")
        return 1
    print("every LAST_MAP door is decidable, the audit decides it, and "
          "the recorder refuses the one landing it can never have")
    return 0


if __name__ == "__main__":
    sys.exit(main())
