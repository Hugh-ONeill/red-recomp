#!/usr/bin/env python3
"""Two counters, one round, opposite verdicts — and the loud one was wrong.

Run 17, four minutes in (2026-09-13). The run was sweeping Viridian City
for the Poke Mart and finding it: 266 cells newly on screen one round, 131
the next, 81 the next. The ROUND BUDGET said so in the trace of every one
of them — "this round found something new — 266 cell(s) newly on screen —
and does not count against the step's rounds". The STALE counter, reading
the same rounds, called them all dry, because it asks only whether the
party ended up STANDING somewhere this subgoal had not stood, or whether
something it carries changed: badges, flags, bag, party, money. Sweeping
one city changes none of those. Three dry rounds tripped the thinking gate
and the run spent 235 seconds and 5,092 tokens deliberating about a search
that was working (user: "it was making progress (unseen ground now seen)
so idk why the thinking mode would activate").

So ground coming onto the screen now counts as the world moving. It is
safe to count because it is SELF-LIMITING in a way an idea is not: a sweep
stops of its own accord once nothing new comes into view. And it is
counted per MAP against a high-water mark, so walking back into a room
already seen reveals nothing and resets nothing — which is the whole point
of the stale budget and must survive this.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))


class Counter:
    """The accounting as run_plan does it, with nothing else of the run."""
    def __init__(self):
        self.stale = 0
        self.dry = 0
        self.hi = {}
        self.fp = None
        self.stood = set()

    def round(self, map_id, seen_n, region=None, fp=None, exempt=False):
        fresh = region is not None and region not in self.stood
        if region is not None:
            self.stood.add(region)
        looked = map_id in self.hi and seen_n > self.hi[map_id]
        if map_id:
            self.hi[map_id] = max(seen_n, self.hi.get(map_id, 0))
        moved = bool(fresh or looked or (fp is not None and fp != self.fp))
        if moved:
            self.stale = 0
            self.dry = 0
        elif not exempt:
            self.stale += 1
        self.fp = fp if fp is not None else self.fp
        return moved


# ---- the Viridian sweep, as it actually ran -----------------------------
c = Counter()
c.round("VIRIDIAN_CITY", 40, region="VIRIDIAN_CITY|17,0", fp="a")
for n in (224, 355, 436):                     # +184, +131, +81
    c.round("VIRIDIAN_CITY", n, region="VIRIDIAN_CITY|17,0", fp="a")
ck("a sweep that keeps revealing ground never goes stale", c.stale == 0)

# ---- but a sweep that stops revealing does ------------------------------
for _ in range(4):
    c.round("VIRIDIAN_CITY", 436, region="VIRIDIAN_CITY|17,0", fp="a")
ck("...and the moment it stops finding anything, it does", c.stale == 4)
ck("...which is what the budget is FOR", c.stale >= 3)

# ---- walking back into a seen room reveals nothing ----------------------
c2 = Counter()
c2.round("OAKS_LAB", 100, region="OAKS_LAB|4,1", fp="a")
c2.round("PALLET_TOWN", 200, region="PALLET_TOWN|10,0", fp="a")
c2.round("OAKS_LAB", 100, region="OAKS_LAB|4,1", fp="a")
ck("a room already seen resets nothing on re-entry", c2.stale == 1)
c2.round("OAKS_LAB", 80, region="OAKS_LAB|4,1", fp="a")
ck("...and neither does seeing LESS of it", c2.stale == 2)

# ---- the first sight of a map is not double-counted --------------------
c3 = Counter()
c3.round("ROUTE_1", 0, region="ROUTE_1|10,35", fp="a")
ck("arriving somewhere new is new ground, which already counted",
   c3.stale == 0)

# ---- the other two reasons still work ----------------------------------
c4 = Counter()
c4.round("X", 10, region="X|1,1", fp="a")
for _ in range(3):
    c4.round("X", 10, region="X|1,1", fp="a")
ck("nothing seen, nothing carried, nowhere new: dry", c4.stale == 3)
c4.round("X", 10, region="X|1,1", fp="b")      # a badge, an item, a level
ck("...and something the run CARRIES still resets it", c4.stale == 0)
c4.round("X", 10, region="X|2,2", fp="b")
ck("...and so does standing somewhere new", c4.stale == 0)

# ---- an exempt round is still neither for nor against -------------------
c5 = Counter()
for _ in range(3):
    c5.round("X", 5, region="X|1,1", fp="a", exempt=True)
ck("an exempt round counts neither way, as before", c5.stale == 0)

# ---- and the run says which of the three it was -------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the counter reads the map's own seen count",
   '.get("seen") or {})\n                              .get("n")' in SRC
   or '.get("seen") or {}' in SRC)
ck("...against a high-water mark, kept per map",
   "_seen_hi[_mid_now] = max(_seen_n, _seen_hi.get(_mid_now, 0))" in SRC)
ck("...and only counts a rise, never a first sight",
   "_looked = _mid_now in _seen_hi and _seen_n > _seen_hi[_mid_now]" in SRC)
ck("the world moving now includes having looked",
   "_moved_world = bool(_fresh_ground or _looked" in SRC)
ck("the plan's verdict says so in its own words",
   '"more of this map on screen" if _looked else' in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
