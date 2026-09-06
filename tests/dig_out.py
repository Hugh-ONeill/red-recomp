#!/usr/bin/env python3
"""DIG and the ESCAPE ROPE carry the party out to the last Pokemon Center,
against the real game.

Boots under contract.py's own love identity from a pinned save (the party
on the Pokemon Mansion's basement floor at a cell it stood on live, a
DUGTRIO that knows DIG, two ESCAPE_ROPEs, Cinnabar as the last Center), so
nothing here can reach the campaign. A Center was tried first as the stage
and the game refused: a Pokemon Center is its own POKECENTER tileset, not
INTERIOR, and DIG is not offered there — which is the gate doing its job.

  tests/dig_out.py                 the pinned fixture, two boots
  tests/dig_out.py --save PATH     start from a specific save

Boot one: DIG from the basement -> set down on Cinnabar Island outside the
Center door; DIG outdoors -> refused in words, party unmoved; the rope
outdoors -> refused, count unchanged; heal walks in. Boot two: the rope
from the basement -> outside, one rope fewer. Neither op takes a step, so
the wild floor never rolls a fight. The op's words are checked against the
observation, never trusted on their own.
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import contract as C                                   # noqa: E402

FIXTURE = ROOT / "tests/fixtures/mansion_b1f_dig.lua"


def knows(o, mv):
    for m in o.get("party") or []:
        for x in m.get("moves") or []:
            if (x.get("id") if isinstance(x, dict) else x) == mv:
                return m.get("species")
    return None


def boot(save, speed, run_dir):
    proc = C.start_game(run_dir, save, speed)
    os.environ["RED_BRIDGE_DIR"] = str(run_dir)
    from bridge import Bridge                           # noqa: E402
    from executor import bootstrap                      # noqa: E402
    b = Bridge(run_dir)
    bootstrap(b, cont=True)
    return proc, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--speed", default="200")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    save = args.save or FIXTURE
    if not save.exists():
        sys.exit(f"no save: {save}")
    run_dir = ROOT / "run/digout"
    fails = []

    def check(name, ok, detail=""):
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}"
              + (f"\n          {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    def pos(o):
        pl = (o or {}).get("player") or {}
        return ((o.get("map") or {}).get("id"), pl.get("x"), pl.get("y"))

    # ---------------------------------------------------------- boot one: DIG
    proc, b = boot(save, args.speed, run_dir)
    try:
        o = b.obs() or {}
        here = (o.get("map") or {}).get("id") or ""
        digger = knows(o, "DIG")
        ropes = int((o.get("bag") or {}).get("ESCAPE_ROPE") or 0)
        town = ((o.get("respawn") or {}).get("outdoor")) or ""
        print(f"  standing on {here} at {pos(o)[1:]}; {digger or 'nobody'} "
              f"knows DIG; {ropes} rope(s); last Center's town {town}")
        if not digger or not town:
            print("\n  SKIPPED — this save has no DIG-knowing party member "
                  "or no Center to return to; re-run with the fixture.")
            return 0
        # THE SCENARIO ITSELF: asking for a Center where there is none
        r = (b.send("heal") or {}).get("result") or {}
        det = str(r.get("detail") or "")
        check("heal with no Center on this map refuses and names the ways back",
              not r.get("ok") and "no Center door on this map" in det
              and "DUGTRIO" in det and "knows DIG" in det
              and "ESCAPE_ROPE is in your bag" in det
              and f"on {town}" in det and "OUTSIDE the door" in det, det)
        check("...without taking a step", pos(b.obs() or {}) == (here, 20, 4))
        r = (b.send("field_move", move="DIG") or {}).get("result") or {}
        o = b.obs() or {}
        now = (o.get("map") or {}).get("id") or ""
        det = str(r.get("detail") or "")
        check("DIG from the basement carries the party out to the Center's town",
              r.get("ok") and now == town and now != here, f"{det} | now on {now}")
        check("...and says where it set you down, and that nothing was spent",
              f"set you down on {now}" in det and "outside the door" in det, det)
        check("...beside a door that leads into a Center",
              any("POKECENTER" in str(w.get("dest") or "")
                  for w in (o.get("map") or {}).get("warps") or []),
              str((o.get("map") or {}).get("warps"))[:200])
        p0 = pos(o)
        r = (b.send("field_move", move="DIG") or {}).get("result") or {}
        o = b.obs() or {}
        det = str(r.get("detail") or "")
        check("DIG outdoors is refused before any menu opens, naming TELEPORT",
              not r.get("ok") and "not offered here" in det and "TELEPORT" in det, det)
        check("...and the party did not move", pos(o) == p0, f"{p0} -> {pos(o)}")
        r = (b.send("use_item", item="ESCAPE_ROPE") or {}).get("result") or {}
        o = b.obs() or {}
        det = str(r.get("detail") or "")
        check("the rope outdoors is refused in the game's words and unspent",
              not r.get("ok") and "isn't the time" in det
              and int((o.get("bag") or {}).get("ESCAPE_ROPE") or 0) == ropes, det)
        r = (b.send("heal") or {}).get("result") or {}
        o = b.obs() or {}
        check("heal walks into the Center from the landing spot",
              r.get("ok") and "POKECENTER" in ((o.get("map") or {}).get("id") or ""),
              f"{r.get('detail')} | {(o.get('map') or {}).get('id')}")
    finally:
        if not args.keep:
            C.stop_game(proc)

    # ------------------------------------------------------ boot two: the rope
    proc, b = boot(save, args.speed, run_dir)
    try:
        o = b.obs() or {}
        here = (o.get("map") or {}).get("id") or ""
        ropes = int((o.get("bag") or {}).get("ESCAPE_ROPE") or 0)
        town = ((o.get("respawn") or {}).get("outdoor")) or ""
        r = (b.send("use_item", item="ESCAPE_ROPE") or {}).get("result") or {}
        o = b.obs() or {}
        now = (o.get("map") or {}).get("id") or ""
        left = int((o.get("bag") or {}).get("ESCAPE_ROPE") or 0)
        det = str(r.get("detail") or "")
        check("an ESCAPE_ROPE from the basement carries the party out",
              r.get("ok") and now == town and now != here, f"{det} | now on {now}")
        check("...and exactly one rope was spent, as the op says",
              left == ropes - 1 and f"({left} left)" in det, f"{ropes}->{left} | {det}")
    finally:
        if not args.keep:
            C.stop_game(proc)
    print(("\nFAIL %d" % len(fails)) if fails
          else "\nok: DIG and the rope carry the party out to the last Center")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
