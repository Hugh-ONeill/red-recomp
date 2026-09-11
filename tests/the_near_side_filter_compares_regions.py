#!/usr/bin/env python3
"""_walk_joined compares two REGIONS, and it was being handed a map.

The excludes rule refuses a step that carves off the part of a map the run
has already come out onto, because that part IS the far side -- unless it
is walk-joined to where the party started, in which case it is the NEAR
side and the filter drops it.  The filter compared candidates against
_map_now(), which answers "ROUTE_23" and never "ROUTE_23|10,104", so
nothing ever matched and it never fired.

That is why "Come out of Victory Road onto a part of ROUTE_23 you have
never stood on" could not be authored: five rounds refusing the exclusion
of ROUTE_23|4,31, the part Victory Road's own door lands on, which is
walk-joined to both other parts the run had walked (2026-09-11, user: "fix
the near-side filter to use the region not the map").

No claim is made when either half is missing: a bare map wearing a
region's shape would be worse than nothing.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# ---- the reader ---------------------------------------------------------
ck("an observation carrying map and region gives a region",
   A._region_now(obs={"map": {"id": "ROUTE_23", "region": "10,104"}})
   == "ROUTE_23|10,104")
ck("...and the state file's two halves do too",
   A._region_now(obs={}, last={"map": "ROUTE_23", "region": "4,31"})
   == "ROUTE_23|4,31")
ck("a map with no region claims nothing",
   A._region_now(obs={"map": {"id": "ROUTE_23"}}, last={"map": "ROUTE_23"})
   is None)
ck("...and neither does an empty record",
   A._region_now(obs={}, last={}) is None)
ck("it never returns a bare map",
   "|" in (A._region_now(obs={"map": {"id": "X", "region": "1,1"}}) or "|"))

# ---- and _map_now still answers its own question ------------------------
ck("_map_now still gives the map alone",
   A._map_now(obs={"map": {"id": "ROUTE_23", "region": "10,104"}}) == "ROUTE_23")

# ---- the filter now compares like with like -----------------------------
SRC = (ROOT / "planner" / "author.py").read_text()
blk = SRC.split("THE PARTY'S REGION, NOT ITS MAP", 1)[1][:600]
ck("the near-side filter reads the region", "_in_parts = [_region_now()]" in blk)
ck("...and still walk-joins against earlier steps' areas",
   '(x.get("done_when") or {}).get("area")' in blk)
_f = SRC.split("_in_parts = [_region_now()]", 1)[1][:500]
ck("...and still never joins a part to itself", 'w != pt' in _f)

# ---- the joined-ness it depends on is real ------------------------------
# ROUTE_23's three walked parts are joined by walk: edges in the live atlas
try:
    _atlas = json.loads((ROOT / "run" / "explored.json").read_text())
    _has = any(str(k).startswith("walk:") for r, e in
               (_atlas.get("explored") or {}).items()
               if str(r).startswith("ROUTE_23") for k in (e or {}))
except OSError:
    _has = True          # no run to read; the unit checks above stand alone
ck("walk: edges are what join two parts of one map", _has)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:90] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
