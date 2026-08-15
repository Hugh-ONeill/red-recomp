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
# shops/catch are irrelevant to a PATHING probe, and the
# probe's own escalation wander bankrupts the wallet (money 75
# at the Viridian mart, probe 2) — skip them and just travel
SKIP = {"reach_cerulean_city", "buy_status_heals", "catch_backup",
        "buy_potions", "buy_pewter_potions"}


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
    # a DIAGNOSTIC wants to reach Route 4 reliably, not measure replay:
    # give it escalation (pure replay stalled on Route 3, chain-probe 1)
    ex = ex_mod.Executor(b, run_id="probe4", can_escalate=True,
                         model="gemma4:31b-it-q4_K_M")
    save = (Path.home() / ".local/share/love/pokemon-love2d/saves/red"
            / "slot1.lua")
    ex_mod.bootstrap(b, cont=save.exists())
    print(f"[boot] {'continued from save' if save.exists() else 'new game'}: "
          f"{(b.obs() or {}).get('map', {}).get('id')}")

    last_saved = None
    for plan_path in (REPO / "plans/brock.json", REPO / "plans/mtmoon.json"):
        plan = json.loads(plan_path.read_text())
        print(f"== {plan_path.name}")
        for sg in plan["subgoals"]:
            if sg["id"] in SKIP:
                continue
            obs = ex.settle() or {}
            if (obs.get("map") or {}).get("id") == "ROUTE_4":
                print("   reached ROUTE_4 — stopping to probe")
                break
            ex.plan, ex.plan_path = plan, None
            ok = ex.run_subgoal(sg) if sg.get("macro") else False
            if not ok:
                ok, ops = ex.escalate(sg)
                if ok and ops:       # [] is not a route (see distill)
                    sg["macro"] = ops
            print(f"   {sg['id']}: {'ok' if ok else 'FAILED'}")
            here = ((ex.settle() or {}).get("map") or {}).get("id")
            if ok and here != last_saved:
                # RATCHET: save on each new MAP (not each subgoal — the save
                # menu can linger, and saving constantly multiplied that)
                r = (ex._send_safe("save_game") or {}).get("result") or {}
                last_saved = here
                for _ in range(3):        # make sure the field is back
                    o = ex.settle() or {}
                    if o.get("mode") == "overworld":
                        break
                    ex._send_safe("tap", btn="b")
                print(f"      [saved on {here}] {r.get('detail')}")
        else:
            continue
        break


    obs = ex.settle() or {}
    here = (obs.get("map") or {}).get("id")
    # SAVE where we ended up, so the next probe boots with --continue and
    # skips the whole replay (the probe's real cost)
    r = (b.send("save_game") or {}).get("result") or {}
    print(f"\n[save on {here}] {r.get('detail')}")
    # the save menu can linger (save_game's own close is unreliable — see
    # its comments); clear it with B before the field probe, or map_probe
    # answers "not in overworld" from inside a menu
    for _ in range(12):
        o = b.obs() or {}
        if o.get("mode") == "overworld":
            break
        b.send("tap", btn="b")
    obs = ex.settle() or {}
    here = (obs.get("map") or {}).get("id")
    print(f"\n== probing from {here} at {obs.get('player')}")
    for side in ("east", "south"):
        r = (b.send("map_probe", dir=side) or {}).get("result") or {}
        print(f"\n[{side}] {r.get('detail')}")
    b.send("quit")


if __name__ == "__main__":
    main()
