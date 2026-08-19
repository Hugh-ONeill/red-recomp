#!/usr/bin/env python3
"""Every door edge in the walked graph, against the game's own warp table.

A door's destination is recorded from where the party was STANDING once the
dust settled, so anything that moved it between the warp firing and the read
lands on the door: ROUTE_7|18,2 --18,9--> SAFFRON_CITY, four times, for a
door the ROM says opens into ROUTE_7_GATE. That one made the way west read
as the way back, and ROUTE_16's 7,5 --> ROUTE_17 hid the FLY house door
behind a lie for a whole leg. executor.note_transition now refuses to record
a transition whose op landed somewhere else (343cd87); this finds the ones
already written down.

READ ONLY BY DEFAULT. --fix drops the contradicting edges, which leaves them
reading "untried" — honest, and they re-record the moment they are walked.
Never rewrites an edge to the table's answer: where a door goes is the
model's to discover by walking, and the table is ours to check against, not
to tell.

  LAST_MAP is a sentinel ("back the way you came"), not a map, so a house
  door recorded as the town outside it AGREES with the table. Elevators are
  skipped: the panel rewrites their warps at ride time.

Usage: audit_doors.py [--fix] [--game DIR] [--graph run/explored.json]
"""
import argparse
import json
import re
from pathlib import Path


def warp_tables(game: Path) -> dict:
    src = (game / "data/generated/maps.lua").read_text()
    out = {}
    for m in re.finditer(r"\n  ([A-Z0-9_]+) = \{", src):
        seg = src[m.end():m.end() + 20000]
        j = seg.find("warps = {")
        if j < 0:
            continue
        k = seg.find("\n    },", j)
        d = {}
        for w in re.finditer(r'destMap = "([A-Z0-9_]+)",\s*destWarp = \d+,'
                             r'\s*x = (\d+),\s*y = (\d+)',
                             seg[j:k if k > 0 else j + 3000]):
            d[(int(w.group(2)), int(w.group(3)))] = w.group(1)
        if d:
            out[m.group(1)] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--game", default=str(Path.home() / "Developer/gen1recomp"))
    ap.add_argument("--graph", default="run/explored.json")
    a = ap.parse_args()

    tbl = warp_tables(Path(a.game))
    g = json.loads(Path(a.graph).read_text())
    ex = g["explored"]
    bad = []
    for reg, edges in list(ex.items()):
        mp = reg.split("|")[0]
        if "ELEVATOR" in mp:
            continue
        for k, v in list((edges or {}).items()):
            if not re.fullmatch(r"\d+,\d+", str(k)):
                continue
            x, y = (int(n) for n in k.split(","))
            want = (tbl.get(mp) or {}).get((x, y))
            got = str((v or {}).get("to", "")).split("|")[0]
            if not (want and got) or want == "LAST_MAP" or want == got:
                continue
            if "ELEVATOR" in got:
                continue
            bad.append((reg, k, got, want, (v or {}).get("n")))
            if a.fix:
                del ex[reg][k]
    for reg, k, got, want, n in bad:
        print(f"{reg:24} {k:>6}  recorded->{got:<24} truth {want} (n={n})")
    print(f"{len(bad)} contradicting door edge(s)"
          + (" — dropped" if a.fix else ""))
    if a.fix and bad:
        Path(a.graph).write_text(json.dumps(g))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
