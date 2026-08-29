#!/usr/bin/env python3
"""A seen-gated seam search proves nothing about the map.

Two claims, both load-bearing: (1) cross refuses a side of the map no
cell of which has been on screen, BEFORE reading the map table (the "no
north edge" fail-fast used to answer for ground never looked at); (2)
when the seam search was stopped by the footprint rather than by walls,
the verdict is scoped — it avoids "cannot be walked to" and "no walkable
path reaches it", the exact phrases _seam_proof and the journal regex
read as permanent geometry — while the executor's recall/uncork/surf
retries still fire on the scoped words. The failure report's name-lists
(fences, bushes, doors) are filtered to what has been on screen.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

ck("cross refuses a never-seen side, before the map-table fail-fast",
   "no cell of the %s side of %s has ever been ON " in sh
   and sh.index("has ever been ON ") < sh.index("has no %s edge — %s"))
ck("the never-seen-side refusal carries none of the proof phrases",
   (lambda t: "cannot be walked to" not in t and "seam of" not in t
    and "no walkable path" not in t)(
        sh.split("no cell of the %s side of %s")[1][:500]))
ck("the seam search reports whether unseen ground bordered it",
   "unseen_touched = bfs_to_edge(G, dir, c.skip, c.surf, blind)" in sh
   and ", bestx, besty, seen, nseen, gate_unseen" in sh)
ck("a footprint-stopped search gets the scoped verdict",
   "cannot be reached over the \"\n        .. \"ground you have SEEN" in sh
   and "(unseen_touched or 0) > 0" in sh)
ck("a fully-seen dead search keeps the strong verdict (proof still lands)",
   "cannot be walked to from \"\n        .. \"here — no walkable path reaches it." in sh)
ck("_seam_proof and the journal regex still read only the strong phrases",
   'or "cannot be walked to" in det)' in ex
   and 'seam of (\\w+) .*cannot be walked to' in ex)
ck("recall, uncork and the surf retry fire on the scoped verdict too",
   ex.count("cannot be reached over the ground") == 4)
ck("the failure report names only what has been on screen",
   'if mask0 and not mask0[x .. "," .. y] then return end' in sh
   and "local mask0 = blind and nil or (SEEN[startMap] or {})" in sh)
ck("the you-are-not-shut-in doors come from the seen flood",
   "local reach = blind and (warp_reach(G) or {})\n"
   "                    or (seen_reach(G) or {})" in sh)

sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
_c = L.Candidate(key="north", kind="seam", status="untried",
                 note="cross(dir=north): FAILED — the north seam of VIRIDIAN_CITY (to ROUTE_2) cannot be reached over the ground you have SEEN — the search stopped where your footprint ends, NOT a proven wall")
ck("a footprint-stopped seam is not a refusal (explore may open it)", not L._refused(_c))
ck("...and its row says a walk over seen ground has not reached it yet, not that it turned you back",
   "no walk over ground you have " in (ROOT / "planner" / "ledger.py").read_text()
   and 'and "cannot be reached over the ground" in str(c.note or "")' in (ROOT / "planner" / "ledger.py").read_text())
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
