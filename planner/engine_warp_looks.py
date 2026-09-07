#!/usr/bin/env python3
"""What is DRAWN on each warp tile, per tileset, with the direction the
drawing shows: stairs up, stairs down, ladder up, ladder down.

    planner/engine_warp_looks.py            # prints the Lua table for shim.lua
    planner/engine_warp_looks.py --txt      # writes planner/engine_warp_looks.txt

Reads gen1recomp's generated maps and tilesets: for every warp of every
map, the tile the engine reads for that cell (Map:cellTile = the cell's
bottom-left 8x8 tile) and the floor of the map it leads to, from the two
maps' names (1F, 2F, B1F). A tile that leads UP everywhere it appears is
drawn as an ascending staircase; one that leads DOWN everywhere, a
descending one. The destination is used only to LABEL the graphic once,
here; the label itself says what the tile looks like, which any player
sees, and never where it goes (2026-09-07, user: "the actual tiles often
show what they are ... stairs going up, stairs going down, ladder versions
of those two"). Cave tilesets draw ladders, the rest draw stairs. A tile
whose warps lead both ways is a plain "stairs" (looks like a staircase,
direction not settled by the drawing), and doorways, exit mats and cave
mouths are left to the engine's own door test, as before.
"""
import re
import sys
import collections
from pathlib import Path

G = Path.home() / "Developer" / "gen1recomp" / "data" / "generated"
LADDER_SETS = {"CAVERN"}
# the drawing settles these; the survey cannot (no floor in the names)
HAND = {("UNDERGROUND", 19): "stairs_up",     # tunnel exits climb to the gate houses (GATE 26 is the way down)
        ("DOJO", 74): "stairs",               # Lance's room, kept from the old list
        ("MUSEUM", 26): "stairs_down",        # one pair of warps, below the two-warp rule; the same
        ("MUSEUM", 28): "stairs_up"}          # tiles and directions as GATE, LOBBY and MANSION


def floor(mid):
    m = re.search(r"(?<![A-Z0-9])(B?\d{1,2})F(?![A-Z0-9])", mid or "")
    if not m:
        return None
    t = m.group(1)
    return -int(t[1:]) if t.startswith("B") else int(t)


def survey():
    S = (G / "maps.lua").read_text()
    T = (G / "tilesets.lua").read_text()
    tilesets = {}
    for m in re.finditer(r"\n  ([A-Z_0-9]+) = \{\n    animation", T):
        blk = T[m.start(): m.start() + 200000]
        e = re.search(r"\n  [A-Z_0-9]+ = \{\n    animation", blk[10:])
        blk = blk[:e.start() + 10] if e else blk
        b = re.search(r"\n    blocks = \{(.*?)\n    \},", blk, re.S)
        nums = list(map(int, re.findall(r"\d+", b.group(1))))
        tilesets[m.group(1)] = [nums[i * 16:(i + 1) * 16] for i in range(len(nums) // 16)]
    by = collections.defaultdict(collections.Counter)
    for m in re.finditer(r"\n  ([A-Z_0-9]+) = \{\n    blocks = \{(.*?)\},", S, re.S):
        mid = m.group(1)
        blocks = list(map(int, re.findall(r"\d+", m.group(2))))
        blk = S[m.start(): m.start() + 60000]
        e = re.search(r"\n  [A-Z_0-9]+ = \{\n    blocks", blk[10:])
        blk = blk[:e.start() + 10] if e else blk
        w = re.search(r"width = (\d+)", blk)
        ts = re.search(r'tileset = "([A-Z_0-9]+)"', blk)
        if not (w and ts) or ts.group(1) not in tilesets:
            continue
        W, tset = int(w.group(1)), tilesets[ts.group(1)]
        wb = re.search(r"warps = \{(.*?)\n    \}", blk, re.S)
        for x in re.findall(r"\{[^{}]*\}", wb.group(1), re.S) if wb else []:
            d = dict(re.findall(r"(\w+) = ([^,\n]+)", x))
            try:
                sx, sy = int(d["x"]), int(d["y"])
            except (KeyError, ValueError):
                continue
            bi = (sy // 2) * W + (sx // 2)
            if bi >= len(blocks) or blocks[bi] >= len(tset):
                continue
            b = tset[blocks[bi]]
            cell_tile = b[((sy % 2) * 2 + 1) * 4 + (sx % 2) * 2]      # bottom-left, as Map:cellTile
            f0, f1 = floor(mid), floor(d.get("destMap", "").strip('"'))
            rel = ("up" if f1 > f0 else "down" if f1 < f0 else "same") if (f0 is not None and f1 is not None) else "?"
            by[(ts.group(1), cell_tile)][rel] += 1
    return by


def table():
    by = survey()
    out = {}
    # TWO OR MORE WARPS, ALL ONE WAY. One warp is not a drawing settled:
    # FACILITY tile 1 is plain floor under four landings and exits, one of
    # which happens to lead up. Both ways on one tile is not a staircase:
    # FACILITY 32 is the teleport pad of Saffron Gym and Silph Co (the
    # engine names pads before this table is consulted), CAVERN 20 is the
    # Seafoam cells the current carries you across. Those are left to the
    # engine's own tests and the door fallback, as before.
    for (ts, tile), c in by.items():
        up, down = c["up"], c["down"]
        if up + down < 2 or (up and down) or c["same"] > up + down:
            continue
        kind = "ladder" if ts in LADDER_SETS else "stairs"
        out[(ts, tile)] = f"{kind}_{'up' if up else 'down'}"
    out.update(HAND)
    return out, by


def main():
    out, by = table()
    if "--txt" in sys.argv:
        p = Path(__file__).with_name("engine_warp_looks.txt")
        p.write_text("".join(f"{ts}\t{tile}\t{look}\n" for (ts, tile), look in sorted(out.items())))
        print(f"wrote {p} ({len(out)} rows)")
        return
    print("      local WARP_LOOKS = {")
    for ts in sorted({ts for ts, _ in out}):
        cells = ", ".join(f'[{tile}] = "{out[(ts, tile)]}"' for (t2, tile) in sorted(out) if t2 == ts)
        print(f"        {ts:12} = {{ {cells} }},")
    print("      }")
    print("-- evidence (tileset, tile: how its warps lead):", file=sys.stderr)
    for k in sorted(out):
        print(f"--   {k[0]} {k[1]}: {dict(by.get(k, {}))} -> {out[k]}", file=sys.stderr)


if __name__ == "__main__":
    main()
