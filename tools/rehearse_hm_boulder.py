#!/usr/bin/env python3
"""Rehearse the leg 33/34 tool-chain before the chain meets it live.

Everything the next stretch of run 14 needs is code that has either
never run or never run in this order: the MOON STONE evolution scene
under `use_item`'s close loop, an HM taught with `forget=` (yesterday's
fix has only ever seen TMs), `field_move STRENGTH`'s activation, and
`{"op":"push"}` — shipped at the very end of 2026-08-21 and exercised
by nothing but synthetic tests. The first real customer would have been
a Victory Road boulder with four campaign attempts riding on it.

So: walk the whole chain by hand tonight, against a COPY of the save,
under the contract harness's own love identity — nothing here can touch
the campaign.

  STAGE A (the save as it stands, Fuchsia Pokemon Center):
    MOON_STONE on NIDORINA        -> the evolution scene, ridden out
    HM_SURF  taught, forget=      -> NIDOQUEEN knows SURF
    HM_STRENGTH taught, forget=   -> NIDOQUEEN knows STRENGTH
    save_game                     -> stage B starts from this world

  STAGE B (stage A's save, teleported to VICTORY_ROAD_1F 8,16):
    push before activation        -> must REFUSE and say why
    field_move STRENGTH           -> strengthActive readback
    the 18-push journey           -> entrance boulder onto the switch
                                     at 17,13 (the real gen 1 puzzle;
                                     plan solved offline from the
                                     engine's own walkability)
    EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH -> the flag the ledger sees
    out to ROUTE_23 and back      -> map load clears strengthActive:
                                     push must refuse AGAIN, and a
                                     re-issued field_move must revive it

Wild encounters are part of the rehearsal, not noise — VICTORY_ROAD_1F
rolls them on every tile and the chain will face the same interrupts.
The wrapper flees and re-sends, and reports how often it had to.

  tools/rehearse_hm_boulder.py            both stages
  tools/rehearse_hm_boulder.py --stage b  reuse stage A's saved world
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import contract as C                                   # noqa: E402

# the offline sokoban solution: entrance boulder (5,15) -> switch (17,13),
# computed from data/generated/{maps,tilesets}.lua with the engine's own
# defCellTile walkability and the map's other objects as obstacles.
PLAN = [
    ("down", 5, 15), ("right", 5, 16), ("right", 6, 16), ("right", 7, 16),
    ("up", 8, 16), ("right", 8, 15), ("up", 9, 15), ("right", 9, 14),
    ("right", 10, 14), ("right", 11, 14), ("right", 12, 14),
    ("right", 13, 14), ("right", 14, 14), ("right", 15, 14),
    ("up", 16, 14), ("up", 16, 13), ("right", 16, 12), ("down", 17, 12),
]
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
SWITCH_FLAG = "EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"

fails: list[str] = []
fled = 0


def case(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {str(detail)[:200]}")
    if not ok:
        fails.append(name)
    return ok


def mon(o, species):
    for i, m in enumerate(o.get("party") or []):
        if m.get("species") == species:
            return i + 1, m
    return None, None


def moves_of(m):
    return [str(v.get("id") if isinstance(v, dict) else v)
            for v in (m or {}).get("moves") or []]


def clear_battle(b):
    """Flee whatever interrupted us. The campaign has a whole policy for
    this; the rehearsal just runs — L51 CHARIZARD leads and outspeeds
    everything on this floor."""
    global fled
    for _ in range(20):
        o = b.obs() or {}
        if o.get("mode") == "overworld":
            return True
        fled += 1
        b.send("battle_run")
    return False


def send(b, op, **kw):
    clear_battle(b)
    r = (b.send(op, **kw) or {}).get("result") or {}
    return r


def boulder_cells(b):
    o = b.obs() or {}
    return {(d.get("x"), d.get("y"))
            for d in (o.get("map") or {}).get("objects") or []
            if d.get("kind") == "boulder"}


def push_step(b, dir_, x, y):
    """One planned push. A wild mid-walk fails the op without moving the
    boulder, so flee and re-send until the boulder is on the far cell."""
    dx, dy = DIRS[dir_]
    tgt = (x + dx, y + dy)
    det = ""
    for _ in range(6):
        if tgt in boulder_cells(b):
            return True, det
        r = send(b, "push", x=x, y=y, dir=dir_)
        det = str(r.get("detail") or "")
        if tgt in boulder_cells(b):
            return True, det
    return False, det


def teleport(save_in: Path, save_out: Path, map_id: str, x: int, y: int,
             outdoor=("ROUTE_23", 4, 32)):
    """Rewrite the player block of a slot1.lua — and lastOutdoor, because
    the cave's exit warps say LAST_MAP: leave lastOutdoor pointing at
    Fuchsia and walking out of Victory Road lands you there, an exit no
    walk can come back from (the first run of stage B proved it)."""
    txt = save_in.read_text()
    m = re.search(r"(  player = \{.*?\n  \},)", txt, re.S)
    if not m:
        sys.exit("could not find the player block in " + str(save_in))
    blk = m.group(1)
    blk = re.sub(r'map = "[A-Z_0-9]+"', f'map = "{map_id}"', blk)
    blk = re.sub(r"\n    x = -?\d+", f"\n    x = {x}", blk)
    blk = re.sub(r"\n    y = -?\d+", f"\n    y = {y}", blk)
    blk = re.sub(r'facing = "[a-z]+"', 'facing = "up"', blk)
    txt = txt.replace(m.group(1), blk)
    oid, ox, oy = outdoor
    txt = re.sub(
        r"  lastOutdoor = \{.*?\n  \},",
        f'  lastOutdoor = {{\n    id = "{oid}",\n    x = {ox},'
        f"\n    y = {oy},\n  }},",
        txt, count=1, flags=re.S)
    save_out.write_text(txt)


def boot(run_dir, save, speed):
    proc = C.start_game(run_dir, save, speed)
    os.environ["RED_BRIDGE_DIR"] = str(run_dir)
    from bridge import Bridge                          # noqa: E402
    from executor import bootstrap                     # noqa: E402
    b = Bridge(run_dir)
    bootstrap(b, cont=True)
    return proc, b


IDENT_SAVE = C.LOVE / C.TEST_IDENT / "saves/red/slot1.lua"


def stage_a(run_dir, speed):
    print("== STAGE A: stone, then two HMs, in the Fuchsia Center")
    proc, b = boot(run_dir, C.LIVE_SAVE, speed)
    try:
        o = b.obs() or {}
        slot, nido = mon(o, "NIDORINA")
        if not slot:
            sys.exit("no NIDORINA in the party — wrong save?")
        print(f"  NIDORINA is slot {slot}, moves {moves_of(nido)}")

        r = send(b, "use_item", item="MOON_STONE", slot=slot)
        o = b.obs() or {}
        qslot, queen = mon(o, "NIDOQUEEN")
        case("MOON_STONE evolves NIDORINA and the scene closes",
             bool(r.get("ok")) and qslot == slot, r.get("detail"))
        if not qslot:
            return 1
        case("...and we are back in the overworld",
             (b.obs() or {}).get("mode") == "overworld")

        # she came in with four moves, so both teaches need forget= —
        # which is the path the chain kept failing before e45559d's fix,
        # and the fix has only ever been exercised by TMs.
        r = send(b, "use_item", item="HM_SURF", slot=qslot,
                 forget="TAIL_WHIP")
        _, queen = mon(b.obs() or {}, "NIDOQUEEN")
        case("HM_SURF taught over TAIL_WHIP",
             "SURF" in moves_of(queen), r.get("detail"))

        r = send(b, "use_item", item="HM_STRENGTH", slot=qslot,
                 forget="SCRATCH")
        _, queen = mon(b.obs() or {}, "NIDOQUEEN")
        case("HM_STRENGTH taught over SCRATCH",
             "STRENGTH" in moves_of(queen), r.get("detail"))
        print(f"  NIDOQUEEN now: {moves_of(queen)}")

        r = send(b, "save_game")
        case("save_game writes the world stage B starts from",
             bool(r.get("ok")), r.get("detail"))
    finally:
        C.stop_game(proc)
    return 0


def stage_b(run_dir, speed):
    print("== STAGE B: the boulder switch on VICTORY_ROAD_1F")
    if not IDENT_SAVE.exists():
        sys.exit("no stage A save — run stage A first")
    vr_save = run_dir / "slot_vr.lua"
    run_dir.mkdir(parents=True, exist_ok=True)
    teleport(IDENT_SAVE, vr_save, "VICTORY_ROAD_1F", 8, 16)
    proc, b = boot(run_dir, vr_save, speed)
    try:
        o = b.obs() or {}
        here = (o.get("map") or {}).get("id")
        case("teleported save wakes on VICTORY_ROAD_1F",
             here == "VICTORY_ROAD_1F", here)
        print(f"  boulders seen: {sorted(boulder_cells(b))}")
        case("the entrance boulder reads kind=boulder at 5,15",
             (5, 15) in boulder_cells(b))

        # WATCH 1: before activation the push must refuse, and the
        # refusal must say what is missing — the chain only ever learns
        # from what the words carry.
        r = send(b, "push", x=5, y=15, dir="down")
        det = str(r.get("detail") or "")
        case("push before STRENGTH refuses and names the cure",
             not r.get("ok") and "STRENGTH" in det, det)
        print(f"          it said: {det[:160]}")

        r = send(b, "field_move", move="STRENGTH")
        case("field_move STRENGTH activates", bool(r.get("ok")),
             r.get("detail"))

        # WATCH 2: the 18-push journey — does rock.cellX track live?
        done = 0
        for dir_, x, y in PLAN:
            ok, det = push_step(b, dir_, x, y)
            if not ok:
                case(f"push {done + 1}/18 ({dir_} at {x},{y})", False, det)
                break
            done += 1
        case("all 18 pushes moved the boulder", done == len(PLAN))

        # WATCH 3: what the ledger can see once the boulder rests on
        # the switch.
        o = b.obs() or {}
        case("the switch flag fired and is in obs.flags",
             SWITCH_FLAG in (o.get("flags") or []))

        # WATCH 4: a map change clears strengthActive. Leave, return,
        # and the boulder is home at 5,15 with STRENGTH asleep — the
        # refusal must say so, and a re-issued field_move must work.
        send(b, "use_warp", x=8, y=17)             # off the edge -> LAST_MAP
        o = b.obs() or {}
        left = (o.get("map") or {}).get("id")
        case("walked out to ROUTE_23", left == "ROUTE_23", left)
        if left == "ROUTE_23":
            send(b, "use_warp", x=4, y=31)         # the cave mouth
        o = b.obs() or {}
        case("...and back in",
             (o.get("map") or {}).get("id") == "VICTORY_ROAD_1F",
             (o.get("map") or {}).get("id"))
        r = send(b, "push", x=5, y=15, dir="down")
        det = str(r.get("detail") or "")
        case("after re-entry push refuses again (STRENGTH cleared)",
             not r.get("ok") and "STRENGTH" in det, det)
        r = send(b, "field_move", move="STRENGTH")
        ok2, _ = push_step(b, "down", 5, 15)
        case("re-issued field_move revives the push",
             bool(r.get("ok")) and ok2)
    finally:
        C.stop_game(proc)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["a", "b", "all"], default="all")
    ap.add_argument("--speed", default="200")
    args = ap.parse_args()

    run_dir = ROOT / "run/rehearsal"
    if args.stage in ("a", "all"):
        rc = stage_a(run_dir, args.speed)
        if rc:
            return rc
    if args.stage in ("b", "all"):
        stage_b(run_dir, args.speed)

    print(f"\n{'-' * 60}")
    print(f"wild interrupts fled: {fled}")
    if fails:
        print(f"THE REHEARSAL FOUND {len(fails)} GAP(S):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("the whole leg 33/34 tool-chain works: stone, both HM teaches, "
          "activation, 18 pushes, the switch flag, and the map-change "
          "reset with its refusal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
