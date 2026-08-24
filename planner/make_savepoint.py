#!/usr/bin/env python3
"""Park a save exactly where you want a trial to begin.

THE SAVEPOINT IS THE CONTROL SURFACE. policy_author's gym used to walk the
party somewhere and heal it before scoring, which bakes "where the save
sits" into the gym and breaks the moment the run moves on. Instead: drive
the game once, by hand, to the state worth testing from, save it to a file,
and point `--from-save` at that file. Every candidate then starts from a
byte-identical position (user, 2026-08-24: "can we just control everything
from a savepoint?").

Runs in contract.py's isolation — own love identity, own bridge dir, a COPY
of the source save — so the campaign's game is never touched.

  make_savepoint.py --out run/arena_e4.lua --heal --ops ops.json
  make_savepoint.py --out run/arena_e4.lua --heal \
      --op '{"op":"use_warp","x":4,"y":11}' --op '{"op":"heal"}'
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "planner"))
sys.path.insert(0, str(REPO / "tests"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True,
                    help="where to write the savepoint")
    ap.add_argument("--from-save", type=Path, default=None,
                    help="source save (default: the live one)")
    ap.add_argument("--op", action="append", default=[],
                    help="a JSON op to run, repeatable, in order")
    ap.add_argument("--ops", type=Path, default=None,
                    help="a JSON file holding a list of ops")
    ap.add_argument("--heal", action="store_true",
                    help="shorthand for a final {\"op\":\"heal\"}")
    args = ap.parse_args()

    from contract import start_game, LIVE_SAVE      # noqa: E402
    src = args.from_save or LIVE_SAVE
    if not Path(src).exists():
        sys.exit(f"no such save: {src}")

    ops = [json.loads(o) for o in args.op]
    if args.ops:
        ops += json.loads(args.ops.read_text())
    if args.heal:
        ops.append({"op": "heal"})

    run_dir = REPO / "run/savepoint"
    proc = start_game(run_dir, Path(src), "200")
    try:
        os.environ["RED_BRIDGE_DIR"] = str(run_dir)
        from bridge import Bridge                   # noqa: E402
        from executor import bootstrap              # noqa: E402
        b = Bridge(run_dir)
        bootstrap(b, cont=True)
        o = b.obs() or {}
        print(f"[savepoint] start: {(o.get('map') or {}).get('id')}")
        for step in ops:
            step = dict(step)
            op = step.pop("op")
            r = b.send(op, **step)
            det = str(((r or {}).get("result") or {}).get("detail") or "")
            print(f"[savepoint] {op}({step}): {det[:110]}")
        o = b.obs() or {}
        print(f"[savepoint] end: {(o.get('map') or {}).get('id')} "
              f"{o.get('player', {}).get('x')},{o.get('player', {}).get('y')}")
        for p in (o.get("party") or []):
            print(f"[savepoint]   {p.get('species')} L{p.get('level')} "
                  f"{p.get('hp')}/{p.get('max_hp')}")
        b.send("save_game")
        # the game writes its own slot; copy that out to --out
        ident = Path(os.path.expanduser(
            "~/.local/share/love/red-contract/saves/red/slot1.lua"))
        if not ident.exists():
            sys.exit(f"the game did not write {ident}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ident, args.out)
        print(f"[savepoint] wrote {args.out}")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
