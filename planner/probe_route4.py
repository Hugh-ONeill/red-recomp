#!/usr/bin/env python3
"""Live probe: replay to Route 4, then interrogate its pathing reality.

chain1/chain2 both died on reach_cerulean_city ("east seam cannot be walked
to"). Route 4 is a plateau whose east seam sits below one-way ledges, and
ledges are walls to Collision.canMove (the engine hops BEFORE tryMove), so
the question is whether the ledge-aware BFS now composes a path east.

Owns its own game process; replays the chained plans (macros only, no model
calls) skipping the failing subgoal, then dumps map_probe diagnostics.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import executor as ex_mod
from bridge import Bridge, RUN

REPO = Path(__file__).resolve().parent.parent
SKIP = {"reach_cerulean_city"}


def main():
    if (RUN / "obs.json").exists():
        (RUN / "obs.json").unlink()
    game = subprocess.Popen([str(REPO / "run.sh"), "200"], cwd=REPO,
                            start_new_session=True)
    atexit.register(lambda: os.killpg(game.pid, signal.SIGTERM))
    for _ in range(60):
        if (RUN / "obs.json").exists():
            break
        time.sleep(1)
    else:
        sys.exit("game did not come up")

    b = Bridge()
    ex_mod.set_active_spec(
        ex_mod.battle_policy.load_spec(REPO / "plans/policy_model_v1.json"))
    ex = ex_mod.Executor(b, run_id="probe4")
    ex_mod.bootstrap(b)

    for plan_path in (REPO / "plans/brock.json", REPO / "plans/mtmoon.json"):
        plan = json.loads(plan_path.read_text())
        print(f"== replaying {plan_path.name}")
        for sg in plan["subgoals"]:
            if sg["id"] in SKIP:
                continue
            ok = ex.run_subgoal(sg) if sg.get("macro") else False
            print(f"   {sg['id']}: {'ok' if ok else 'FAILED'}")
            if not ok and sg["id"] not in ("buy_pewter_potions",):
                obs = ex.settle() or {}
                print(f"   stopped on {(obs.get('map') or {}).get('id')}")
                break

    obs = ex.settle() or {}
    here = (obs.get("map") or {}).get("id")
    print(f"\n== probing from {here} at {obs.get('player')}")
    for side in ("east", "south"):
        r = (b.send("map_probe", dir=side) or {}).get("result") or {}
        print(f"\n[{side}] {r.get('detail')}")
    b.send("quit")


if __name__ == "__main__":
    main()
