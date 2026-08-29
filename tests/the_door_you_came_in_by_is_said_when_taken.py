#!/usr/bin/env python3
"""A doorway's tiles are one door, and taking it back is said in the round.

Viridian Forest south gate, 2026-08-29 (user watching): the ledger row read
"door (4,7)+(5,7) — ONE doorway, two tiles wide -> ROUTE_2 — the door you
came in by"; the model said "I see two doors; one leads back to Route 2,
the other is untried", sent use_warp(5,7) and walked back out, and the
round said only "ok (map->ROUTE_2)". Two honesty fixes: the label names
the other tile as the SAME door, not another; and a successful use_warp
through the door you came in by says so in the round's own words, with
where it put you — judged against the arrival record as it stood BEFORE
the op (note_transition rewrites it the moment the warp lands).
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
d = L.Candidate(key="4,7", kind="door", twins=["5,7"])
ck("a two-tile doorway is labelled as ONE door with the other tile named as the same door",
   d.label() == "door (4,7) [ONE door, 2 tiles wide: (5,7) is the SAME door, not another]")
ck("the arrival record is snapshotted before the op runs",
   "_arr_snap = (getattr(self, \"_arrived\", None)," in ex)
ck("a use_warp back through it is said, with where it put you",
   "that was the door you came in by (a " in ex and "where you came from" in ex
   and "ledger._came_in_by(_ns, pre_obs, self._where(pre_obs)," in ex)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
