#!/usr/bin/env python3
"""A condition that settling destroys must not be re-checked after settling.

run_plan's last act is to re-test the final subgoal's done_when against
`ex.settle()`. That guard is right and was written for a real failure: a
leg can walk to the end of its subgoal list without achieving anything,
and the chain then starts the NEXT leg on a premise that was never true —
mountain subgoals running on a fresh Charmander with no badge.

But settle() resolves the game to a clean decision state, which CLOSES
whatever menu is open. So a leg whose objective is a UI screen is failed
by the act of checking it:

    == subgoal: interact_with_pc
       done: interact_with_pc
    !! leg_03_access_the_pc_for_the_first_time.v21.json reached its last
       subgoal but its objective {"any_of":[{"screen":"BoxMenu"},
       {"screen":"PlayerPC"}]} is NOT met
    RESULT: PLAN FAILED

`interact_with_pc` completed FOURTEEN times across twenty-two plan
versions. The run opened the PC every time and was told every time that
it had not. Nothing it did was ever wrong.

The split is durable vs transient. A badge, a flag, an item, a map, a
party size: all still true a moment later, and all still re-checked. A
screen or a mode is true only while it is open, the subgoal's own success
already witnessed it, and there is nothing left to re-witness.

Synthetic: no game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

TRANSIENT = {"screen", "mode"}

CASES = [
    ("the objective that cost 22 plan versions is transient",
     {"any_of": [{"screen": "BoxMenu"}, {"screen": "PlayerPC"}]}, True),
    ("a bare screen goal too", {"screen": "BoxMenu"}, True),
    ("and a bare mode goal", {"mode": "ui"}, True),

    # everything the guard was actually written for must STILL be re-checked
    ("a badge is durable", {"badge": "BOULDERBADGE"}, False),
    ("a flag is durable", {"flag": "EVENT_GOT_POKEDEX"}, False),
    ("a map is durable", {"map": "PEWTER_CITY"}, False),
    ("an area is durable", {"area": "MT_MOON_B2F|20,5"}, False),
    ("an item is durable", {"has_item": ["HM_CUT"]}, False),
    ("a party size is durable", {"party_size": 3}, False),
    ("a level is durable", {"lead_level": 12}, False),

    # a MIXED objective keeps its re-check: the durable half is still worth
    # confirming, and skipping it would reopen the hole the guard closed
    ("screen AND a flag together is still re-checked",
     {"screen": "BoxMenu", "flag": "EVENT_GOT_POKEDEX"}, False),
    ("...and inside an any_of as well",
     {"any_of": [{"screen": "BoxMenu"}, {"map": "PEWTER_CITY"}]}, False),
]


def main():
    fails = []
    for name, dw, want_skip in CASES:
        skip = E.pred_keys(dw) <= TRANSIENT
        ok = skip is want_skip
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          keys {sorted(E.pred_keys(dw))} -> "
                  f"skip={skip}, want {want_skip}")
            fails.append(name)

    # the executor must use exactly this test, not a copy of it
    src = (ROOT / "planner" / "executor.py").read_text()
    ok = 'pred_keys(final) <= {"screen", "mode"}' in src
    print(f"  {'ok  ' if ok else 'FAIL'}  run_plan skips the re-check by "
          f"this same rule")
    if not ok:
        fails.append("rule not wired in")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"A CHECK IS STILL DESTROYING WHAT IT CHECKS: {len(fails)}")
        return 1
    print(f"transient objectives are witnessed once, durable ones are "
          f"re-checked ({len(CASES) + 1} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
