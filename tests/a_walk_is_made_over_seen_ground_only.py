#!/usr/bin/env python3
"""The movement ops route over ground that has been on screen, only.

The ledger, sweep and go held the footprint line; walk_to/use_warp/cross
still searched the full map with live collision, so an op could thread a
maze the run had never looked at (the obs called a door
unreachable-over-seen-ground and use_warp opened it anyway). Guards that
the routing gate exists, honors the freeze, is consulted by every step
branch of both BFSes, that a never-seen target is refused in plain words,
and that blind=true / RED_BLIND_ROUTING=1 remain as tooling escapes the
model's vocabulary does not carry.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

ck("the routing gate exists and applies the freeze",
   "local function route_gate(G)" in sh
   and "seen_wall_since_view(map, WT, rpx, rpy, nx, ny, nk," in sh
   and 'if not mask[nk] then return "unseen" end' in sh)
ck("bfs_dir and bfs_to_edge build it, honoring blind and the env escape",
   sh.count("local gate = (not (blind or BLIND_ROUTING)) and route_gate(G) or nil") == 2
   and 'local BLIND_ROUTING = (os.getenv("RED_BLIND_ROUTING") == "1")' in sh)
ck("the walker's BFS gates walk, spinner and ledge steps",
   "probe, dir)\n           and not gated(nx, ny) then" in sh
   and "not wblock[key(sx, sy)]\n               and not gated(sx, sy) then" in sh
   and sh.count("and not gated(lx, ly) then") == 2)
ck("the seam finder's BFS gates walk, spinner and ledge steps",
   "probe, dname)\n           and not gated(nx, ny) then" in sh
   and "if not seen[key(sx, sy)] and not gated(sx, sy) then" in sh)
ck("a never-seen walk target is refused in plain words",
   "has NEVER BEEN ON SCREEN — you only know " in sh
   and "local blind = (c.blind and true) or BLIND_ROUTING" in sh)
ck("the never-seen refusal does not say 'no path' (region retries are moot)",
   "no path" not in sh.split("has NEVER BEEN ON SCREEN")[1][:400])
ck("the no-path words say the search was over seen ground, not a proven wall",
   sh.count("THIS SEARCH RAN OVER GROUND THAT HAS BEEN ON SCREEN") == 2
   and 'gate and "have SEEN and " or ""' in sh)
ck("sweep's own router honors the freeze too",
   "bfs_dir_pass(G, target.x, target.y, avoid,\n"
   "                               route_gate(G))" in sh)
ck("surf mounts, grind and interact reach over the seen flood "
   "(warp_reach stays only for the obs memo and blind branches)",
   sh.count("= warp_reach(G) or {}") == 1
   and sh.count("blind and (warp_reach(G) or {})") == 2)
ck("grind's spawn-ground flood and its nearest-grass address are seen facts",
   "and not (gate and gate(nx, ny, key(nx, ny))) then" in sh
   and 'if map:isGrassCell(xx, yy) and _gm[xx .. "," .. yy] then' in sh
   and "no \" .. ground .. \" anywhere on the ground you have " in sh)
ck("the model's op vocabulary states the seen-ground contract",
   "over ground that has BEEN\nON SCREEN" in ex)
ck("the executor's somebody-standing-there hint stays quiet on never-seen",
   'and "NEVER BEEN ON SCREEN" not in det' in ex)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
