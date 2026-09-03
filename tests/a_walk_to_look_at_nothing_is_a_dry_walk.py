#!/usr/bin/env python3
"""A walk to look at nothing is a dry walk.

explore ranks an area by the unseen ground counted for it, and walks the
party there, and two walks that sweep nothing new send the area to the
bottom of its list. Rock Tunnel's entrance chamber carried a count of ONE
spot (kept positive while the map as a whole has unseen ground — the
pocket rule) while its own live frontier was empty: the tunnel's unseen
ground lies in chambers no walk from that chamber reaches. Nothing to
sweep meant the sweep never ran, the dry-walk count never moved, and
explore walked the party into that chamber six times in one attempt, each
round ending as it arrived, the model warping back out each time
(2026-09-03, leg 24 "Reach Lavender Town").

Now an arrival with nothing to look at counts as a dry walk and says so,
in the same words the swept-nothing case uses; the second such walk sends
the area to the bottom, as the rule always intended.

Source-level: the branch sits deep inside explore's arrival expansion.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

i_sweep = src.index('_run({"op": "sweep"},\n                              "sweeping the ground there never on screen")')
i_dry = src.index("nothing here is left to look at from where you")
i_exits = src.index("if _map_goal and exits2:            # same rule as at home")
ck("an arrival with no live frontier but a counted spot is a dry walk",
   i_sweep < i_dry < i_exits)
seg = src[i_sweep:i_exits]
ck("...counted in the same ledger the swept-nothing case uses",
   seg.count("self._dry_walks[region] = int(self._dry_walks.get(region, 0) or 0) + 1") == 2)
ck("...and said in the round, naming the count and the region",
   "spot(s) counted for {region} are in" in seg
   and "ranks LAST for explore from now on" in seg)
ck("...only when the area was chosen for its unseen ground", "        if unseen:\n" in seg)
ck("...and persisted", seg.count("self._save_memory()") >= 2)
ck("two dry walks still rank the area last",
   "if _dry >= 2:\n                _pri = 3" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
