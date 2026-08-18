#!/usr/bin/env python3
"""The boxes can be written to, and RELEASE really releases.

Until 2026-08-17 obs.pc_mons listed what was in PC storage and no op could
touch it. Pokemon went in exactly one way — caught with a full party, which
this engine auto-deposits rather than refusing (docs/known-differences.md)
— and never came out. That made "the party holds a WATER type"
UNSATISFIABLE rather than merely hard the moment the right creature was
boxed, the same shape as the mode that did not exist and stopped a chain.
The harness was even telling the run to do it: daycare_withdraw refuses
with "there is nowhere to put X until one is deposited in the PC", naming
an action with no op behind it.

RELEASE IS HERE ON PURPOSE (user, 2026-08-17: "cant tie its hands even if
it wants to make a bad decision"). It is irreversible: no box holds the
Pokemon afterwards and that individual can never be caught again. The
harness does not get a vote on whether releasing is wise. What it does
insist on is that the model name the species it means — a mismatch is a
WRONG FACT about which row is which, not a bad decision, and the last case
below is the one that matters most in this file.

THIS RUNS THE REAL GAME, because the whole point is the menu driving:
which row, which submenu, which confirmation, and the release prompt that
defaults to NO. A synthetic test would only re-assert what I already
believed. It boots under contract.py's own love identity against a COPY of
the save, so nothing it does can reach the campaign.

  tests/pc_box.py                 use the live save (copied)
  tests/pc_box.py --save PATH     start from a specific save
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import contract as C                                   # noqa: E402


def party_of(o):
    return [(m.get("species"), m.get("level")) for m in (o.get("party") or [])]


def boxed(o):
    return [(m.get("species"), m.get("box"), m.get("index"))
            for m in (o.get("pc_mons") or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--speed", default="200")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    save = args.save
    if save is None:
        save = C.LIVE_SAVE if C.LIVE_SAVE.exists() else None
        if save is None:
            cands = sorted((ROOT / "run").glob("slot1*.lua"),
                           key=lambda p: p.stat().st_mtime)
            save = cands[-1] if cands else None
    if not save or not save.exists():
        sys.exit("no save to test against — this test needs a party")

    run_dir = ROOT / "run/pcbox"
    proc = C.start_game(run_dir, save, args.speed)
    fails = []
    try:
        os.environ["RED_BRIDGE_DIR"] = str(run_dir)
        from bridge import Bridge                       # noqa: E402
        from executor import bootstrap                  # noqa: E402
        b = Bridge(run_dir)
        bootstrap(b, cont=True)
        o = b.obs() or {}
        if o.get("mode") != "overworld":
            sys.exit(f"not in the overworld: {o.get('mode')}")
        print(f"  party  {party_of(o)}")
        print(f"  boxed  {boxed(o)}")
        n0 = len(o.get("party") or [])
        if n0 < 2:
            sys.exit("this test needs at least 2 party members to be safe "
                     "— the PC refuses your last Pokemon")

        # A PC IS IN EVERY POKEMON CENTER and the op walks to it itself, so
        # the run has to be standing in one. Rather than route there, ask
        # the op and let it say so: "there is no PC on this map" is a
        # legitimate pass for a test run from an outdoor save.
        r = (b.send("pc_deposit", slot=n0) or {}).get("result") or {}
        det = str(r.get("detail") or "")
        if not r.get("ok") and "no PC on this map" in det:
            print(f"\n  SKIPPED — the save is not in a Pokemon Center "
                  f"({det})")
            print("  Re-run from a save inside one to exercise the menus.")
            return 0

        # --- DEPOSIT
        o = b.obs() or {}
        ok = len(o.get("party") or []) == n0 - 1 and len(boxed(o)) == 1
        print(f"  {'ok  ' if ok else 'FAIL'}  deposit moves a Pokemon out of "
              f"the party and into a box")
        if not ok:
            print(f"          {det}")
            print(f"          party {party_of(o)}  boxed {boxed(o)}")
            fails.append("deposit")
        stored = (o.get("pc_mons") or [{}])[0]
        species = stored.get("species")
        idx, box = stored.get("index"), stored.get("box")

        # --- A WRONG SPECIES MUST NOT RELEASE ANYTHING. The one property
        # in this file worth more than the features: an index that has
        # shifted must never take the wrong Pokemon with it.
        wrong = "MAGIKARP" if species != "MAGIKARP" else "RATTATA"
        r = (b.send("pc_release", index=idx, box=box,
                    species=wrong) or {}).get("result") or {}
        o = b.obs() or {}
        ok = (not r.get("ok")) and len(boxed(o)) == 1
        print(f"  {'ok  ' if ok else 'FAIL'}  releasing under the WRONG "
              f"species name refuses, and nothing is lost")
        if not ok:
            print(f"          {r.get('detail')}")
            print(f"          boxed {boxed(o)}")
            fails.append("wrong-species guard")

        # --- WITHDRAW it back
        r = (b.send("pc_withdraw", index=idx, box=box) or {}).get("result") or {}
        o = b.obs() or {}
        ok = len(o.get("party") or []) == n0 and not boxed(o)
        print(f"  {'ok  ' if ok else 'FAIL'}  withdraw brings it back into "
              f"the party")
        if not ok:
            print(f"          {r.get('detail')}")
            print(f"          party {party_of(o)}  boxed {boxed(o)}")
            fails.append("withdraw")

        # --- and RELEASE, correctly named, really is permanent
        b.send("pc_deposit", slot=n0)
        o = b.obs() or {}
        st = (o.get("pc_mons") or [{}])[0]
        r = (b.send("pc_release", index=st.get("index"), box=st.get("box"),
                    species=st.get("species")) or {}).get("result") or {}
        o = b.obs() or {}
        ok = r.get("ok") and not boxed(o) and len(o.get("party") or []) == n0 - 1
        print(f"  {'ok  ' if ok else 'FAIL'}  release under the right name "
              f"removes it from the box for good")
        if not ok:
            print(f"          {r.get('detail')}")
            print(f"          party {party_of(o)}  boxed {boxed(o)}")
            fails.append("release")
        else:
            print(f"          {r.get('detail')}")
    finally:
        if not args.keep:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    print(f"\n{'-' * 60}")
    if fails:
        print(f"THE BOXES DO NOT WORK: {len(fails)} case(s)")
        return 1
    print("deposit, withdraw and release all work, and a misnamed release "
          "takes nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
