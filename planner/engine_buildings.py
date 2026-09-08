#!/usr/bin/env python3
"""What building each outdoor doorway is set in, per map, from the engine's
own block grids.

    planner/engine_buildings.py             # prints the Lua table for shim.lua
    planner/engine_buildings.py --txt       # writes planner/engine_buildings.txt
    planner/engine_buildings.py --show ROUTE_16 PALLET_TOWN

A player looking at the screen sees a house with a door in it, and sees that
two doorways sit in one long building. The harness reported every doorway as
a bare coordinate, so on Route 16 the model took the gate's south-west door
for the Fly house and walked at it twice (run 16, 2026-09-08; user: "should
we have it recognize 'building' from the sprites or something?"). This reads
what is drawn: a cell is WALKABLE if its bottom-left 8x8 tile is in the
tileset's walkable list (the engine's own rule); SCENERY if its tiles are
the map border's (trees, or the sea, or rock — whatever rings the map),
water, or a ledge; everything else that cannot be walked on is WALL. The
building around a door is the largest wall rectangle containing the door
cell; doors whose rectangles coincide share a building. Sizes are in the
page's own units (16px cells). Nothing here says where a door leads.
"""
import re
import sys
from pathlib import Path

G = Path.home() / "Developer" / "gen1recomp" / "data" / "generated"
WATER = {0x14}
# WHAT THE BORDER BLOCK DOES NOT TEACH. Kanto's maps are ringed with block 15
# (tiles 64/65/80/81), but the trees drawn INSIDE a map are another graphic
# (42/43/58/59), the hedge rows another (14/85), and the shoreline's edge tile
# (50) is neither wall nor water. Read off Pallet Town and Route 16, 2026-09-08.
HAND_SCENERY = {"OVERWORLD": {42, 43, 58, 59, 14, 85, 50}}
# WHERE ONE ROOF ENDS AND THE NEXT BEGINS. Kanto's buildings stand wall to
# wall (Celadon's Mansion and Center, Cerulean's north row), so a rectangle
# of wall cells runs across two of them. Each roof is drawn with its own
# corner tiles, which is how a player tells them apart: 5/21 on the left
# edge, 9/25 on the right (read off Red's house, 2026-09-08).
# ...and the big buildings (Centers, Marts, the Celadon row) draw theirs with
# 76 on the left and 77 on the right.
ROOF_LEFT = {"OVERWORLD": {5, 21, 76}}
ROOF_RIGHT = {"OVERWORLD": {9, 25, 77}}


def lua_blocks(txt, start):
    """Parse a Lua array of arrays / numbers starting at txt[start] == '{'."""
    depth = 0
    for e in range(start, len(txt)):
        if txt[e] == "{":
            depth += 1
        elif txt[e] == "}":
            depth -= 1
            if depth == 0:
                body = txt[start:e + 1]
                break
    else:
        return None
    return body


def tilesets():
    T = (G / "tilesets.lua").read_text()
    out = {}
    for m in re.finditer(r"\n  ([A-Z_0-9]+) = \{\n", T):
        name = m.group(1)
        nxt = re.search(r"\n  [A-Z_0-9]+ = \{\n", T[m.end():])
        blk = T[m.start(): m.end() + (nxt.start() if nxt else len(T))]
        bi = blk.find("blocks = {")
        blocks = []
        if bi >= 0:
            body = lua_blocks(blk, bi + len("blocks = "))
            for bm in re.finditer(r"\{([\d,\s]+)\}", body or ""):
                blocks.append([int(x) for x in bm.group(1).replace(" ", "").split(",") if x])
        wm = re.search(r"walkable = \{([\d,\s]*)\}", blk)
        walk = {int(x) for x in wm.group(1).replace(" ", "").split(",") if x} if wm else set()
        out[name] = {"blocks": blocks, "walkable": walk}
    return out


def ledges():
    F = (G / "field.lua").read_text()
    i = F.find("\n  ledges = {")
    body = lua_blocks(F, F.find("{", i + 3))
    out = {}
    for m in re.finditer(r"\{([^{}]*)\}", body or ""):
        t = m.group(1)
        ts = re.search(r'tileset = "([A-Z_]+)"', t)
        lt = re.search(r"ledgeTile = (\d+)", t)
        if lt:
            out.setdefault(ts.group(1) if ts else "OVERWORLD", set()).add(int(lt.group(1)))
    return out


def maps():
    M = (G / "maps.lua").read_text()
    out = []
    heads = list(re.finditer(r"\n  ([A-Z_0-9]+) = \{\n", M))
    for n, m in enumerate(heads):
        mid = m.group(1)
        end = heads[n + 1].start() if n + 1 < len(heads) else len(M)
        blk = M[m.start():end]
        ts = re.search(r'\n    tileset = "([A-Z_0-9]+)"', blk)
        w = re.search(r"\n    width = (\d+)", blk)
        h = re.search(r"\n    height = (\d+)", blk)
        bb = re.search(r"\n    borderBlock = (\d+)", blk)
        bi = blk.find("\n    blocks = {")
        grid = None
        if bi >= 0:
            body = lua_blocks(blk, blk.find("{", bi + 3))
            grid = [int(x) for x in re.sub(r"[{}\s]", "", body or "").split(",") if x]
        warps = []
        wi = blk.find("\n    warps = {")
        if wi >= 0:
            wb = lua_blocks(blk, blk.find("{", wi + 3))
            for wm in re.finditer(r"\{\s*destMap = \"([A-Z_0-9]+)\",\s*destWarp = (\d+),\s*x = (\d+),\s*y = (\d+),?\s*\}", wb or ""):
                warps.append((int(wm.group(3)), int(wm.group(4)), wm.group(1)))
        conns = bool(re.search(r"\n    connections = \{\n", blk))
        if ts and w and h and grid is not None:
            out.append({"id": mid, "tileset": ts.group(1), "w": int(w.group(1)), "h": int(h.group(1)),
                        "border": int(bb.group(1)) if bb else None, "grid": grid, "warps": warps,
                        "outdoor": conns})
    return out


def cell_tiles(mp, tsd, cx, cy):
    """The four 8x8 tiles of cell (cx,cy): [tl, tr, bl, br]; None outside."""
    bx, by = cx // 2, cy // 2
    if not (0 <= bx < mp["w"] and 0 <= by < mp["h"]):
        return None
    bid = mp["grid"][by * mp["w"] + bx]
    blocks = tsd["blocks"]
    if bid >= len(blocks):
        return None
    b = blocks[bid]
    ox, oy = (cx % 2) * 2, (cy % 2) * 2
    return [b[(oy) * 4 + ox], b[(oy) * 4 + ox + 1], b[(oy + 1) * 4 + ox], b[(oy + 1) * 4 + ox + 1]]


def classify(mp, tsd, scenery, ledge_tiles):
    W, H = mp["w"] * 2, mp["h"] * 2
    door = {(x, y) for x, y, _ in mp["warps"]}
    kind = {}
    edges = {}
    rl = ROOF_LEFT.get(mp["tileset"], set())
    rr = ROOF_RIGHT.get(mp["tileset"], set())
    for cy in range(H):
        for cx in range(W):
            t = cell_tiles(mp, tsd, cx, cy)
            if t is None:
                kind[(cx, cy)] = "out"
                continue
            edges[(cx, cy)] = ("L" if (t[0] in rl or t[2] in rl) else "") + ("R" if (t[1] in rr or t[3] in rr) else "")
            bl = t[2]
            if (cx, cy) in door:
                kind[(cx, cy)] = "door"
            elif bl in tsd["walkable"]:
                kind[(cx, cy)] = "walk"
            elif bl in WATER or bl in ledge_tiles or all(x in scenery for x in t):
                kind[(cx, cy)] = "scenery"
            else:
                kind[(cx, cy)] = "wall"
    kind["_edges"] = edges
    return kind, W, H


def rect_around(kind, W, H, ax, ay):
    """The building a wall (or door) cell belongs to, as (x0,y0,x1,y1).

    WIDTH IS READ OFF THE ROOF. Buildings stand wall to wall and their
    bottom rows run together, so the largest wall rectangle through a door
    was a thin slab across two or three of them (Saffron's Pidgey house and
    Mart as one 32x2 "long building"). A player reads a building by its roof:
    climb from the anchor to the top wall row, take that row's run between
    roof corners, then walk down while the whole width is still wall."""
    edges = kind.get("_edges") or {}

    def ok(x, y):
        return kind.get((x, y)) in ("wall", "door")

    def run(y, x):
        x0 = x
        while (x0 - 1 >= 0 and ok(x0 - 1, y)
               and "L" not in edges.get((x0, y), "") and "R" not in edges.get((x0 - 1, y), "")):
            x0 -= 1
        x1 = x
        while (x1 + 1 < W and ok(x1 + 1, y)
               and "R" not in edges.get((x1, y), "") and "L" not in edges.get((x1 + 1, y), "")):
            x1 += 1
        return x0, x1

    if not ok(ax, ay):
        return None
    t = ay
    while t - 1 >= 0 and ok(ax, t - 1):
        t -= 1
    x0, x1 = run(t, ax)
    b = t
    while b + 1 < H and all(ok(x, b + 1) for x in range(x0, x1 + 1)):
        b += 1
    if b < ay:
        # the anchor sits below where the roof's width ends (a narrower base):
        # keep the column range every row down to the anchor shares
        for y in range(t + 1, ay + 1):
            r = run(y, ax)
            x0, x1 = max(x0, r[0]), min(x1, r[1])
        b = ay
    return x0, t, x1, b


def buildings():
    TS = tilesets()
    LG = ledges()
    MS = maps()
    scen = {}
    for mp in MS:
        tsd = TS.get(mp["tileset"])
        if not tsd or mp["border"] is None or mp["border"] >= len(tsd["blocks"]):
            continue
        scen.setdefault(mp["tileset"], set()).update(tsd["blocks"][mp["border"]])
    for ts in scen:
        scen[ts] -= WATER
    for ts, extra in HAND_SCENERY.items():
        scen.setdefault(ts, set()).update(extra)
    out = {}
    for mp in MS:
        if not mp["outdoor"] or not mp["warps"]:
            continue
        tsd = TS.get(mp["tileset"])
        if not tsd:
            continue
        kind, W, H = classify(mp, tsd, scen.get(mp["tileset"], set()), LG.get(mp["tileset"], set()))
        rects = {}
        for x, y, dest in mp["warps"]:
            # A DOOR MAT CAN LIE OUTSIDE THE WALL. The gate houses' warp cells
            # sit beside the building (Route 16's at x=17 and x=24, the wall
            # between), so the rectangle through the door cell alone is a
            # two-row slab. Anchor on the door cell AND on each wall cell
            # beside it; the largest rectangle is the building.
            best = None
            for ax, ay in ((x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if kind.get((ax, ay)) not in ("wall", "door"):
                    continue
                r = rect_around(kind, W, H, ax, ay)
                if r and (best is None or (r[2] - r[0] + 1) * (r[3] - r[1] + 1) > (best[2] - best[0] + 1) * (best[3] - best[1] + 1)):
                    best = r
            if best is None:
                continue
            rects.setdefault(best, []).append((x, y, dest))
        # two doors of one building can anchor slightly different rectangles
        # (one through the mat, one through the wall): merge heavy overlaps
        items = sorted(rects.items(), key=lambda kv: -((kv[0][2] - kv[0][0] + 1) * (kv[0][3] - kv[0][1] + 1)))
        merged = []
        for r, doors in items:
            for mr in merged:
                ox = min(r[2], mr[0][2]) - max(r[0], mr[0][0]) + 1
                oy = min(r[3], mr[0][3]) - max(r[1], mr[0][1]) + 1
                small = min((r[2] - r[0] + 1) * (r[3] - r[1] + 1), (mr[0][2] - mr[0][0] + 1) * (mr[0][3] - mr[0][1] + 1))
                if ox > 0 and oy > 0 and ox * oy >= 0.5 * small:
                    mr[1].extend(doors)
                    break
            else:
                merged.append((r, list(doors)))
        blds = []
        for r, doors in sorted(merged):
            x0, y0, x1, y1 = r
            # WHAT KIND OF ROOF. Houses are drawn with the pitched roof (corner
            # tiles 5/21, 9/25); Centers, Marts, gyms and the gate houses with
            # the flat one (76/77). A player tells a house from a public
            # building by exactly this, before ever reading its sign.
            _top = [cell_tiles(mp, tsd, cx, y0) or [] for cx in range(x0, x1 + 1)]
            flat = any(76 in t or 77 in t for t in _top)
            _walls = sum(1 for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1) if kind.get((cx, cy)) == "wall")
            _doors = sum(1 for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1) if kind.get((cx, cy)) == "door")
            if _walls <= _doors:
                continue          # a cave mouth in rock, a pier's end: no building drawn around it
            blds.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "w": x1 - x0 + 1, "h": y1 - y0 + 1,
                         "flat": flat, "doors": sorted(doors)})
        if blds:
            out[mp["id"]] = blds
    return out


def size_word(w, h, flat=False):
    a = w * h
    if flat:
        if a <= 20:
            return "small flat-roofed building"
        if w >= 3 * h or h >= 3 * w:
            return "long flat-roofed building"
        return "large flat-roofed building"
    if a <= 20:
        return "small house"
    if a <= 42:
        return "house"
    return "large house"


def lua_table(B):
    lines = ["local BUILDINGS = {"]
    for mid in sorted(B):
        lines.append(f"  {mid} = {{")
        for i, b in enumerate(B[mid], 1):
            doors = ", ".join(f'"{x},{y}"' for x, y, _ in b["doors"])
            lines.append(f'    {{ x0 = {b["x0"]}, y0 = {b["y0"]}, x1 = {b["x1"]}, y1 = {b["y1"]}, '
                         f'look = "{size_word(b["w"], b["h"], b.get("flat"))}", doors = {{ {doors} }} }},')
        lines.append("  },")
    lines.append("}")
    return "\n".join(lines)


def main():
    B = buildings()
    if "--show" in sys.argv:
        for mid in sys.argv[sys.argv.index("--show") + 1:]:
            print(f"== {mid}")
            for b in B.get(mid, []):
                print(f"  {b['w']}x{b['h']} at ({b['x0']},{b['y0']})-({b['x1']},{b['y1']}) {size_word(b['w'], b['h'], b.get('flat'))}: "
                      + ", ".join(f"({x},{y})->{d}" for x, y, d in b["doors"]))
        return
    txt = lua_table(B)
    if "--txt" in sys.argv:
        Path(__file__).with_name("engine_buildings.txt").write_text(txt + "\n")
        print(f"wrote {sum(len(v) for v in B.values())} building(s) on {len(B)} map(s)")
        return
    print(txt)


if __name__ == "__main__":
    main()
