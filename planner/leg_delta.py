#!/usr/bin/env python3
"""What a leg actually GAINED, as evidence for judging whether it is done.

check-done only ever saw the CURRENT state, so it could not tell an
objective that was achieved from one that was never touched — and a leg
can fail every subgoal while accomplishing its aim (the fossil leg walked
out of Mt Moon HOLDING the fossil and still failed three rewrites). The
DELTA is the honest record: flags that fired, items and badges gained,
places entered, levels earned, between the moment the leg started and the
moment it gave up.

Mechanical throughout — it reports what changed and never says what that
means. Whether "Deliver the parcel from Bill to the Oak Lab" is satisfied
by EVENT_OAK_GOT_PARCEL is exactly the judgment this project leaves to the
model.

Usage:
  leg_delta.py snap  run/leg_start.json          # before the leg runs
  leg_delta.py diff  run/leg_start.json          # after it fails
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _state() -> dict:
    for src in ("run/last_state.json", "run/obs.json"):
        try:
            o = json.load(open(src))
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        m = o.get("map")
        try:
            vis = json.load(open("run/explored.json")).get("visits") or {}
        except Exception:
            vis = {}
        return {
            "flags": sorted(o.get("flags") or []),
            "bag": dict(o.get("bag") or {}),
            "badges": sorted(o.get("badges") or []),
            "party": [(p.get("species"), p.get("level"))
                      for p in (o.get("party") or [])],
            "map": (m.get("id") if isinstance(m, dict) else m),
            "areas": sorted(vis),
        }
    return {}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mode, path = sys.argv[1], Path(sys.argv[2])
    if mode == "snap":
        path.write_text(json.dumps(_state()))
        return 0
    try:
        before = json.loads(path.read_text())
    except Exception:
        return 0                      # no snapshot: say nothing rather than guess
    now = _state()
    if not now or not before:
        return 0
    bits = []
    fl = [f for f in now.get("flags", []) if f not in set(before.get("flags", []))]
    if fl:
        bits.append("events that fired: " + ", ".join(fl[:12]))
    bg = [b for b in now.get("badges", []) if b not in set(before.get("badges", []))]
    if bg:
        bits.append("badges earned: " + ", ".join(bg))
    ob, nb = before.get("bag", {}), now.get("bag", {})
    got = [f"{k} x{nb[k] - ob.get(k, 0)}" for k in nb
           if nb[k] > ob.get(k, 0)]
    lost = [k for k in ob if k not in nb]
    if got:
        bits.append("items gained: " + ", ".join(sorted(got)[:12]))
    if lost:
        bits.append("items no longer held: " + ", ".join(sorted(lost)[:8]))
    new_areas = [a for a in now.get("areas", [])
                 if a not in set(before.get("areas", []))]
    if new_areas:
        bits.append(f"{len(new_areas)} place(s) entered for the first time: "
                    + ", ".join(new_areas[:8]))
    op = dict((s, l) for s, l in before.get("party", []))
    grew = [f"{s} {op[s]}->{l}" for s, l in now.get("party", [])
            if s in op and l > op[s]]
    joined = [s for s, _ in now.get("party", []) if s not in op]
    if grew:
        bits.append("levels gained: " + ", ".join(grew))
    if joined:
        bits.append("joined the party: " + ", ".join(joined))
    # SPENDING IS NOT A YIELD. "items no longer held" is the bag going
    # DOWN — a potion used, a candy tossed — and it kept a dry leg alive:
    # the Secret Key leg's fourth run read as a yield on "items no longer
    # held: FULL_RESTORE, MAX_POTION" and the dry gate never fired
    # (2026-08-27). It is still reported, as an aside; it just is not
    # progress, so a run with nothing else to show starts with NOTHING.
    aside = ""
    if lost:
        aside = "items no longer held: " + ", ".join(sorted(lost)[:8])
        bits = [b for b in bits if not b.startswith("items no longer held")]
    if not bits:
        print("NOTHING new while this leg ran: no event fired, no item "
              "or badge was gained, and no new place was entered"
              + (f" — only the bag went down ({aside})" if aside else "")
              + ".")
        return 0
    print("WHAT CHANGED WHILE THIS LEG RAN — " + "; ".join(bits)
          + (f" ({aside})" if aside else "") + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
