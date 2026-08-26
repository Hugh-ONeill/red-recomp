#!/usr/bin/env python3
"""Drive a real Executor over a real macro, against a copy of the save.

The contract test proves the SHAPE of an observation. This proves the
executor still plays: bootstrap, settle, a macro replayed step by step,
a predicate satisfied, the walked map written. Between them they cover the
paths that a whole afternoon of edits keeps touching.

It also runs two predicates that used to end the process — a `player_at`
that is not an object, and a `slot_level` written with `level` instead of
`min` — because "an unattended run must never die of a predicate it could
have understood" is a rule that deserves a test rather than a comment.

Runs under its own love identity against a COPY of the save, so it can
never reach the campaign's game. Exits non-zero if any expectation fails.

  tests/replay_smoke.py             use the pinned fixture save
  tests/replay_smoke.py --save P    start from a specific save
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "planner"))

import contract as C            # noqa: E402  (owns the boot + isolation)

RUN = ROOT / "run/contract"
FIXTURE = ROOT / "tests/fixtures/outdoor_cerulean.lua"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--speed", default="200")
    args = ap.parse_args()
    # A PINNED SAVE, NOT THE LIVE ONE. Resuming from wherever the campaign
    # happens to be makes the test a moving target: it passed from Cerulean,
    # then the run boarded the S.S. Anne and it "failed" because every door
    # in a cabin leads to another cabin. A regression test that reports the
    # harness broken for standing in a ship is worse than no test. The
    # fixture is outdoors with a party of five and it does not move.
    save = args.save or FIXTURE
    if not save.exists():
        save = C.LIVE_SAVE
        print(f"[replay] fixture missing, falling back to the live save")
    if not save.exists():
        sys.exit(f"no save to replay from: {save}")

    proc = C.start_game(RUN, save, args.speed)
    os.environ["RED_BRIDGE_DIR"] = str(RUN)
    fails = []
    try:
        from bridge import Bridge                       # noqa: E402
        import executor as E                            # noqa: E402
        b = Bridge(RUN)
        E.bootstrap(b, cont=True)
        here = ((b.obs() or {}).get("map") or {}).get("id")
        if not (b.obs() or {}).get("party"):
            sys.exit(f"CONTINUE did not take — came up in {here} with no "
                     f"party. Nothing below would mean anything.")
        print(f"[replay] resumed in {here}")

        # A REAL MACRO, chosen from where the party actually is: cross the
        # first map edge this map has and require the map to change.
        # INDOORS IS A NORMAL PLACE TO BE. The first version demanded a map
        # EDGE, so the moment the campaign save moved onto the S.S. Anne the
        # test reported failure at the harness for standing in a ship. A
        # door is just as good a macro to replay; take whichever this map
        # has, and only give up when it has neither.
        _m = (b.obs() or {}).get("map") or {}
        conns = dict(_m.get("connections") or {})
        # THE FOOTPRINT: a party standing on a doormat has not seen the
        # city's edges, and a seam is listed only once a cell on that edge
        # has been on screen. Coverage first, then choose — the same order
        # the run itself now follows ({"op":"explore"} = sweep).
        # BOUNDED sweeps: an open-ended sweep walked the fixture party from
        # (25,26) to a pocket at (0,18) north of the CUT_TREE, where the
        # west strip is unreachable, and the test called the harness
        # broken (2026-08-26). Look around a little; if no edge shows, a
        # door will do — the property is that a replayed macro changes
        # the map.
        for _ in range(3):
            if conns:
                break
            r = b.send("sweep", steps=10)
            print(f"[replay] sweep: "
                  f"{str(((r or {}).get('result') or {}).get('detail'))[:100]}")
            _m = (b.obs() or {}).get("map") or {}
            conns = dict(_m.get("connections") or {})
            if not (_m.get("frontier") or []):
                break
        if not conns:
            for w in (_m.get("warps") or []):
                if not w.get("reachable"):
                    continue
                k = f"{w.get('x')},{w.get('y')}"
                conns[k] = None
            if not conns:
                sys.exit(f"{here} has neither a map edge nor a reachable "
                         f"door; nothing to replay")
        # NOT simply the first edge. Cerulean's east seam is held shut by
        # two cooltrainers standing in the gap, so "take conns[0]" tested
        # the harness against a wall and called the harness broken. Any one
        # edge crossing is the property under test; which one is the map's
        # business.
        plan = {"goal": "replay smoke", "subgoals": [
            {"id": "crashing_shape", "goal_text": "player_at as a list",
             "done_when": {"player_at": [5, 7]}, "max_attempts": 1,
             "macro": [{"op": "wait", "frames": 5}]},
            {"id": "silent_shape", "goal_text": "slot 2 to level 15",
             "done_when": {"slot_level": {"slot": 2, "level": 15}},
             "max_attempts": 1, "macro": [{"op": "wait", "frames": 5}]},
        ]}
        ex = E.Executor(b, plan=plan, plan_path=None, can_escalate=False,
                        model="", run_id="replaysmoke")
        ex.MEMORY = RUN / "explored.json"
        ex._load_memory()

        # UNDER THE FOOTPRINT ONLY SEEN EDGES ARE LISTED, and the fixture's
        # one seen edge (west) sits behind the CUT_TREE at (19,28) with no
        # CUT in the party — before the footprint the test simply took
        # another listed edge. The cross op refuses an edge the map does
        # not have, honestly, so every direction is a fair try; the seen
        # doors come after.
        for d in ("north", "south", "east", "west"):
            conns.setdefault(d, None)
        for w in (_m.get("warps") or []):
            if w.get("reachable"):
                conns.setdefault(f"{w.get('x')},{w.get('y')}", None)
        crossed = None
        for d in sorted(conns, key=str):
            door = "," in str(d)
            # a door's destination is UNKNOWN until walked, so for those the
            # test asserts only that the map CHANGED, which is the property
            # under test either way
            want = conns[d] if not door else None
            # a condition that is ALREADY TRUE is passed on the pre-check
            # and the macro never runs (no_battle was that: the door path
            # had silently never been exercised, 2026-08-26); a known
            # destination is asserted, an unknown one gets a condition
            # that cannot pre-satisfy so the replay is forced to happen
            sg = {"id": f"leave_{d}",
                  "goal_text": f"leave {here} by {d}",
                  "done_when": ({"map": want} if want
                                else {"party_size": 99}),
                  "max_attempts": 1,
                  "macro": ([{"op": "cross", "dir": d}] if not door else
                            [{"op": "use_warp",
                              "x": int(str(d).split(",")[0]),
                              "y": int(str(d).split(",")[1])}])}
            ex._attempt(sg)
            now_m = ((b.obs() or {}).get("map") or {}).get("id")
            if now_m and now_m != here:
                crossed = (d, now_m)
                break
            print(f"        {d}: did not open, trying another")
        if not crossed:
            # every listed edge refused (a bush, a pocket): a reachable
            # door is the same property, a map change by a replayed macro
            for w in (((b.obs() or {}).get("map") or {}).get("warps") or []):
                if not w.get("reachable"):
                    continue
                sg = {"id": f"leave_door_{w.get('x')}_{w.get('y')}",
                      "goal_text": "leave by a door", "done_when": {"party_size": 99},
                      "max_attempts": 1,
                      "macro": [{"op": "use_warp", "x": w.get("x"), "y": w.get("y")}]}
                ex._attempt(sg)
                now_m = ((b.obs() or {}).get("map") or {}).get("id")
                if now_m and now_m != here:
                    crossed = (f"door {w.get('x')},{w.get('y')}", now_m)
                    break
        if crossed:
            print(f"  ok    replayed a macro and walked {here} -> "
                  f"{crossed[1]} ({crossed[0]})")
        else:
            print(f"  FAIL  no edge of {here} crossed: {sorted(conns)}")
            fails.append("cross")

        got = {sg["id"]: ex._attempt(sg) for sg in plan["subgoals"]}
        for sid, want in (("crashing_shape", False), ("silent_shape", False)):
            ok = got.get(sid) is want
            print(f"  {'ok  ' if ok else 'FAIL'}  {sid} -> {got.get(sid)} "
                  f"(want {want})")
            if not ok:
                fails.append(sid)

        # the malformed predicate must have been NAMED, not just refused
        if not any("player_at" in k for k in E.PRED_MALFORMED):
            print("  FAIL  the malformed predicate was never reported")
            fails.append("silent malformation")
        else:
            print("  ok    malformation reported: "
                  + "; ".join(f"{k} — {v}"
                              for k, v in E.PRED_MALFORMED.items()))

        # ...and the walked map survived, with its fallback beside it
        wrote = sorted(p.name for p in RUN.iterdir()
                       if p.name.startswith("explored.json"))
        if "explored.json" not in wrote:
            print("  FAIL  no ledger written")
            fails.append("ledger")
        else:
            print(f"  ok    ledger written: {', '.join(wrote)}")
    finally:
        C.stop_game(proc)

    print(f"\n{'-' * 60}")
    if fails:
        print(f"REPLAY SMOKE FAILED: {', '.join(fails)}")
        return 1
    print("replay smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
