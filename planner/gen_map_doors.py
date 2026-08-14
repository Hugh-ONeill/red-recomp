#!/usr/bin/env python3
"""Regenerate planner/map_doors.json from the gen1recomp map data.

Companion to map_edges.json. That file holds the printed map's OUTDOOR
connections ("Route 10 is west of Route 9"); this one holds the doors those
outdoor maps have — which named interior each one opens into.

Same tier as map_edges: the Town Map pins ROCK TUNNEL and DIGLETT'S CAVE to
the routes they sit on, and a player walking a road sees its doorways. What
is deliberately NOT here is anything past the doorway: an interior appears
only if an OUTDOOR map warps into it, so entrances are named and dungeon
interiors, floor graphs and building layouts are not. Working out that Rock
Tunnel's far side reaches Lavender is still the model's to do.

Written because the run planned "Enter Diglett's Cave from Route 10 / exit
east into Route 11" — Diglett's Cave joins Route 2 and Route 11, and the
tunnel on Route 10 is Rock Tunnel. Two real places, swapped.

Usage: gen_map_doors.py [path-to-gen1recomp] > planner/map_doors.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def load(src: str) -> dict:
    """map id -> {"connections": bool, "warps": [dest, ...]}."""
    maps: dict = {}
    # entries look like:  NAME = {\n    blocks = { ... },\n ...  },
    for m in re.finditer(r'\n  ([A-Z][A-Z_0-9]*) = \{', src):
        name = m.group(1)
        start = m.end()
        nxt = re.search(r'\n  [A-Z][A-Z_0-9]* = \{', src[start:])
        seg = src[start:start + nxt.start()] if nxt else src[start:]
        maps[name] = {
            "outdoor": bool(re.search(
                r'connections = \{\s*(north|south|east|west)', seg)),
            "warps": re.findall(r'destMap = "([A-Z_0-9]+)"', seg),
        }
    return maps


def doors(maps: dict, labels: dict) -> dict:
    """Outdoor map -> the named places it has a door into.

    Filtered by the Town Map's own labels: a door is kept only when the
    map draws what is behind it as a place of its OWN name. ROCK TUNNEL is
    labelled ROCK TUNNEL while Viridian's mart is labelled VIRIDIAN CITY
    like the street outside it, so tunnels, caves and towers survive and a
    hundred shop doorways do not. That keeps this file to what a player
    reads off the Town Map, and no further.
    """
    out: dict = {}
    for name, info in maps.items():
        if not info["outdoor"]:
            continue
        here = (labels.get(name) or {}).get("name")
        # A door may open into an ANNEX the map labels with the road's own
        # name — a gate, or the hut that is Diglett's Cave's mouth. Step
        # through those to what they actually reach. One hop, and only
        # through a same-name annex: that is still the doorway a player
        # sees from the road, not the inside of anything.
        seen, queue = set(), list(info["warps"])
        while queue:
            dest = queue.pop(0)
            if dest in seen or dest == "LAST_MAP":
                continue
            seen.add(dest)
            if maps.get(dest, {}).get("outdoor"):
                continue
            there = (labels.get(dest) or {}).get("name")
            if there and there == here:
                queue += [w for w in maps.get(dest, {}).get("warps") or []
                          if w not in seen]
                continue
            if not there:
                continue
            # DRAWN AS ITS OWN PLACE, or merely named after where you are
            # standing? ROCK TUNNEL has its own pin at (14,3) beside ROUTE
            # 10's at (14,4); ROCKET HQ shares CELADON CITY's pin exactly,
            # because the map is not drawing a hideout, it is telling you
            # you are in Celadon. Sharing a pin means the map never showed
            # it — so the Rocket hideout and Silph Co. stay unknown, which
            # is right: where the Silph Scope lives is the model's to find.
            hp, tp = labels.get(name) or {}, labels.get(dest) or {}
            if (hp.get("x"), hp.get("y")) == (tp.get("x"), tp.get("y")):
                continue
            out.setdefault(name, {}).setdefault(there, [])
            if dest not in out[name][there]:
                out[name][there].append(dest)
    return {k: {lbl: sorted(ids) for lbl, ids in sorted(v.items())}
            for k, v in sorted(out.items())}


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1
                else Path.home() / "Developer" / "gen1recomp")
    src = (root / "data" / "generated" / "maps.lua").read_text(
        encoding="utf-8", errors="replace")
    labels = json.loads((root / "tools" / "rom_manifest.json").read_text()
                        )["field"]["townMap"]["locations"]
    print(json.dumps(doors(load(src), labels), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
