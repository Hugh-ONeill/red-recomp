"""Victory Road 1F is solvable, and only one boulder can do it.

The model names WHERE a boulder should end up and the harness works out the
shoving (shim.lua solve_push). This is the same algorithm in Python, run
against the game's own map and collision data, so the puzzle's solvability
is pinned: if a map edit or a bad walkable lookup breaks it, this fails
rather than the run discovering it at 2am.

It also documents the shape of the problem the model is NOT being asked to
solve: 19 shoves that double back, each needing the player on the far side.
"""

import json, subprocess, sys
from collections import deque

GAME = "/home/wiz/Developer/gen1recomp"
# pull walkable cells + npc cells straight from the engine
lua = r'''
package.path="./?.lua;./?/init.lua;"..package.path
local maps = dofile("data/generated/maps.lua")
local ts = dofile("data/generated/tilesets.lua")
local m = maps.VICTORY_ROAD_1F
local set = ts[m.tileset]
local W, H = m.width*2, m.height*2
local WALK = {}
for _, tid in ipairs(set.walkable or {}) do WALK[tid] = true end
local walk = {}
for cy=0,H-1 do
  local row = {}
  for cx=0,W-1 do
    local tx,ty = cx*2, cy*2+1
    local bx,by = math.floor(tx/4), math.floor(ty/4)
    local bi = m.blocks[by*m.width+bx+1]
    local blk = bi and set.blocks[bi+1]
    local t = blk and blk[(ty%4)*4+(tx%4)+1]
    row[#row+1] = (t and WALK[t]) and 1 or 0
  end
  walk[#walk+1] = table.concat(row)
end
local tiles = {}
for cy=0,H-1 do
  local row = {}
  for cx=0,W-1 do
    local tx,ty = cx*2, cy*2+1
    local bx,by = math.floor(tx/4), math.floor(ty/4)
    local bi = m.blocks[by*m.width+bx+1]
    local blk = bi and set.blocks[bi+1]
    row[#row+1] = tostring(blk and blk[(ty%4)*4+(tx%4)+1] or -1)
  end
  tiles[#tiles+1] = table.concat(row, ",")
end
print(table.concat(walk, "\n"))
print("--TILES--")
print(table.concat(tiles, "\n"))
'''
out = subprocess.run(["lua5.4","-e",lua], cwd=GAME, capture_output=True, text=True)
_parts = out.stdout.split("--TILES--")
grid = [l for l in _parts[0].splitlines() if l]
TILES = [[int(v) for v in row.split(",")]
         for row in (_parts[1].splitlines() if len(_parts) > 1 else []) if row]
# THE ENGINE ALSO ENFORCES TILE PAIRS (elevation), and in a CAVERN that is
# what makes Victory Road a maze. Approximating collision as "walkable +
# empty" is what made the shim's first solver plan an 18-shove route whose
# FIRST shove the game refused.
PAIRS = {(32, 5), (65, 5), (42, 5), (5, 33)}


def pair_blocked(x0, y0, x1, y1):
    try:
        a, b = TILES[y0][x0], TILES[y1][x1]
    except IndexError:
        return False
    return (a, b) in PAIRS or (b, a) in PAIRS
if not grid:
    print("could not read the map:", out.stderr[:200]); sys.exit(1)
H, W = len(grid), len(grid[0])
def free(x,y,rocks):
    return 0<=x<W and 0<=y<H and grid[y][x]=='1' and (x,y) not in rocks


def step_ok(x0, y0, x1, y1, rocks):
    return free(x1, y1, rocks) and not pair_blocked(x0, y0, x1, y1)

ROCKS = {(5,16),(14,2),(2,10)}
START_P = (8,15)
SWITCH = (17,13)

def solve(bx,by,px,py,target,others):
    seen={((bx,by),(px,py))}
    q=deque([((bx,by),(px,py),[])])
    while q:
        (bx,by),(px,py),path = q.popleft()
        # player reachability with the boulder as a wall
        R={(px,py)}; dq=deque([(px,py)])
        while dq:
            cx,cy=dq.popleft()
            for dx,dy in ((0,-1),(0,1),(-1,0),(1,0)):
                nx,ny=cx+dx,cy+dy
                if ((nx,ny) not in R and (nx,ny)!=(bx,by)
                        and step_ok(cx,cy,nx,ny,others)):
                    R.add((nx,ny)); dq.append((nx,ny))
        for name,(dx,dy) in (("up",(0,-1)),("down",(0,1)),("left",(-1,0)),("right",(1,0))):
            sx,sy=bx-dx,by-dy
            nx,ny=bx+dx,by+dy
            if (sx,sy) in R and step_ok(bx,by,nx,ny,others):
                st=((nx,ny),(bx,by))
                if st not in seen:
                    if (nx,ny)==target: return path+[name]
                    seen.add(st); q.append(((nx,ny),(bx,by),path+[name]))
    return None

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


ck("the map reads as a real room, not a wall",
   sum(r.count("1") for r in grid) > 100)

sols = {}
for rock in sorted(ROCKS):
    sols[rock] = solve(rock[0], rock[1], START_P[0], START_P[1],
                       SWITCH, ROCKS - {rock})

ck("the puzzle is solvable at all", any(sols.values()))
ck("exactly one boulder can reach the switch",
   sum(1 for v in sols.values() if v) == 1)
ck("...and it is the one by the entrance", sols[(5, 16)] is not None)
ck("the route doubles back rather than running straight",
   len(set(sols[(5, 16)])) > 2)
ck("it is a long route — not something to spell out one shove at a time",
   len(sols[(5, 16)]) > 10)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
