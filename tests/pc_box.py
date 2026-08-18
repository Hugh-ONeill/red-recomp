#!/usr/bin/env python3
"""The screens where a press spends something: boxes and counters.

The boxes can be written to, RELEASE really releases, and neither
a box nor a shop counter can be driven by a blind key press.

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

        # A PC IS IN EVERY POKEMON CENTER and the ops walk to it
        # themselves, so the run has to be standing in one. The save is
        # wherever the campaign left it, so step through a door that leads
        # to one if we are not already inside.
        # `heal` routes to a Center and walks in — a door's dest reads
        # UNKNOWN until it has been walked, so matching warps on their
        # destination picks whatever door happens to be first (it landed
        # in VIRIDIAN_NICKNAME_HOUSE). Use the op that exists for this.
        here = ((b.obs() or {}).get("map") or {}).get("id") or ""
        for _ in range(3):
            if "POKECENTER" in here:
                break
            r = (b.send("heal") or {}).get("result") or {}
            here = ((b.obs() or {}).get("map") or {}).get("id") or ""
            if "POKECENTER" not in here:
                # back outside and try again from the street
                for w in (((b.obs() or {}).get("map") or {}).get("warps")
                          or []):
                    b.send("use_warp", x=w.get("x"), y=w.get("y"))
                    break
                here = ((b.obs() or {}).get("map") or {}).get("id") or ""
        print(f"  standing in {here}")

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
        # --- AND A BARE PRESS MUST BOUNCE OFF. The whole reason the
        # boxes were worth making writable is that blind A-presses were
        # already moving things: menu(index=1) plus a boilerplate
        # answer="yes" bought fifteen POKE_BALLs at a counter without a
        # buy op ever being proposed. With storage writable the same shape
        # could deposit or release, and a release does not come back.
        r = (b.send("interact", name="PC") or {}).get("result") or {}
        det = str(r.get("detail") or "")
        o = b.obs() or {}
        # the rows must be NUMBERED: menu addresses them by index, and an
        # unnumbered list made the model guess (it asked for 2, the box
        # menu it wanted was 1)
        ok = ("the PC is on" in det and "1=" in det
              and len(o.get("party") or []) == n0 - 1)
        print(f"  {'ok  ' if ok else 'FAIL'}  a bare interact opens the PC "
              f"and stops at its menu instead of mashing through it")
        if not ok:
            print(f"          {det[:170]}")
            print(f"          mode {o.get('mode')} party {party_of(o)}")
            fails.append("interact guard")

        # THE REGRESSION THIS FILE EXISTS TO CATCH NOW. The first version
        # of the guard called ui_back_out, so the screen was shut before
        # the observation — which made {"screen":"BoxMenu"} impossible to
        # satisfy, the exact predicate added to make "access the PC"
        # sayable. A subgoal cannot be conditioned on a screen the harness
        # closes on its way out.
        ok = (o.get("ui") or {}).get("screenId") is not None \
            or o.get("mode") == "ui"
        print(f"  {'ok  ' if ok else 'FAIL'}  ...and the screen is still "
              f"OPEN when the observation is taken "
              f"(mode={o.get('mode')}, screen="
              f"{(o.get('ui') or {}).get('screenId')})")
        if not ok:
            fails.append("screen closed before obs")

        # and the box menu itself must be reachable from there, because
        # that is what the subgoal is conditioned on
        r = (b.send("menu", index=1) or {}).get("result") or {}
        o = b.obs() or {}
        sid = (o.get("ui") or {}).get("screenId")
        ok = sid == "BoxMenu"
        print(f"  {'ok  ' if ok else 'FAIL'}  menu on the PC's own list "
              f"reaches BoxMenu (screen={sid})")
        if not ok:
            print(f"          {r.get('detail')}")
            fails.append("BoxMenu unreachable")

        # ...and once THERE, a blind press is refused, without shutting it
        r = (b.send("mash_a", times=3) or {}).get("result") or {}
        o = b.obs() or {}
        ok = (not r.get("ok")) and "PC STORAGE is open" in str(r.get("detail")
                                                              or "") \
            and (o.get("ui") or {}).get("screenId") == "BoxMenu"
        print(f"  {'ok  ' if ok else 'FAIL'}  mashing inside BoxMenu is "
              f"refused and the screen survives the refusal")
        if not ok:
            print(f"          {str(r.get('detail'))[:150]}")
            print(f"          screen now {(o.get('ui') or {}).get('screenId')}")
            fails.append("mash guard")

        # AND THERE MUST BE A WAY OUT. Without one this guard is a trap:
        # menu(index=2) opens the item PC, and from inside it every
        # menu/tap/mash is refused, so the run cannot get back to row 1 to
        # pick the box menu it wanted. It was choosing correctly and had
        # no way to act on it. B closes a screen and cannot spend
        # anything, so B is always allowed.
        r = (b.send("tap", btn="b") or {}).get("result") or {}
        o = b.obs() or {}
        ok = r.get("ok") and (o.get("ui") or {}).get("screenId") != "BoxMenu"
        print(f"  {'ok  ' if ok else 'FAIL'}  B steps back out of a guarded "
              f"screen (now {(o.get('ui') or {}).get('screenId')})")
        if not ok:
            print(f"          {r.get('detail')}")
            fails.append("no escape from the guard")

        # ...and the ops that MEAN to drive it still can, which is the
        # half a guard like this usually breaks. The release above emptied
        # the box, so put something back first — otherwise this would pass
        # or fail for a reason that has nothing to do with the guard.
        b.send("pc_deposit", slot=n0 - 1)
        r = (b.send("pc_withdraw", index=1, box=1) or {}).get("result") or {}
        o = b.obs() or {}
        ok = r.get("ok") and len(o.get("party") or []) == n0 - 1
        print(f"  {'ok  ' if ok else 'FAIL'}  ...while pc_withdraw still "
              f"drives the same screen")
        if not ok:
            print(f"          {r.get('detail')}")
            fails.append("guard blocks real ops")

        # ================= THE COUNTER =================
        # This is where the guard was actually earned: fifteen POKE_BALLs
        # bought without a buy op, 3175 money down to 175. Get outside to
        # a map with a mart and check both halves — the trade ops still
        # work, a bare press does not.
        warps = ((b.obs() or {}).get("map") or {}).get("warps") or []
        out = next((w for w in warps if w.get("x") is not None), None)
        if out:
            b.send("use_warp", x=out["x"], y=out["y"])
        o = b.obs() or {}
        if (o.get("map") or {}).get("id") == "VIRIDIAN_POKECENTER":
            print("  SKIPPED (counter) — could not get out of the Center")
        else:
            money0 = o.get("money")
            r = (b.send("sell", item="POKE_BALL", count=1)
                 or {}).get("result") or {}
            o = b.obs() or {}
            ok = r.get("ok") and (o.get("money") or 0) > (money0 or 0)
            print(f"  {'ok  ' if ok else 'FAIL'}  sell still drives the "
                  f"counter (money {money0} -> {o.get('money')})")
            if not ok:
                print(f"          {r.get('detail')}")
                fails.append("sell")

            # the clerk, pressed blind, is where the 15 balls came from
            r = (b.send("interact", name="VIRIDIANMART_CLERK")
                 or {}).get("result") or {}
            det = str(r.get("detail") or "")
            o2 = b.obs() or {}
            spent = (o2.get("money") or 0) < (o.get("money") or 0)
            ok = ("shop COUNTER is open" in det) and not spent
            print(f"  {'ok  ' if ok else 'FAIL'}  a bare interact on the "
                  f"clerk is handed back, and nothing is bought")
            if not ok:
                print(f"          {det[:160]}")
                print(f"          money {o.get('money')} -> {o2.get('money')}")
                fails.append("clerk guard")

    finally:
        # contract.stop_game, NOT proc.terminate(): run.sh execs xvfb-run,
        # which spawns love as a child and does not forward SIGTERM, so
        # terminate() kills the wrapper and leaves the game running on a
        # dead display. Three of those piled up and blocked the next
        # campaign launch with "a run is still live — stop it first".
        # The helper kills the process GROUP, which is why it exists.
        if not args.keep:
            C.stop_game(proc)

    print(f"\n{'-' * 60}")
    if fails:
        print(f"THE BOXES DO NOT WORK: {len(fails)} case(s)")
        return 1
    print("boxes and counters: the ops that name a decision work, a "
          "blind press does not, and a misnamed release takes nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
