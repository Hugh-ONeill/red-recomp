#!/usr/bin/env python3
"""What the wild ground offered is the plan author's too (2026-09-04).

The executor has tallied every wild encounter by species and map since 08-24
and said it on the page while grinding, never to the plan author. "The party
holds a PSYCHIC or GROUND type" was therefore planned as a walk into a cave
named for a Ground type — a level-16 Diglett — while the run had fought fifty
Drowzee on Route 11 and a hundred Abra on Route 24 (user: "drowzee was also
right there"). The run's own fights now ride the author's evidence, by map,
with the level band met there. What a species is stays the model's.

Synthetic: a walked record in a temp file, no model."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

REC = {"explored": {"ROUTE_11|9,0": {"east": {"to": "DIGLETTS_CAVE|1,1"}}},
       "visits": {"ROUTE_11|9,0": 12, "DIGLETTS_CAVE|1,1": 3},
       "offered": {"ROUTE_11": {"SPEAROW": 89, "EKANS": 78, "DROWZEE": 50},
                   "DIGLETTS_CAVE": {"DIGLETT": 20},
                   "ROUTE_24": {"ODDISH": 202, "KAKUNA": 172, "PIDGEY": 165, "WEEDLE": 158, "ABRA": 117, "BELLSPROUT": 40, "CATERPIE": 9}},
       "wild_lv": {"ROUTE_11": {"lo": 9, "hi": 17, "n": 217}, "DIGLETTS_CAVE": {"lo": 15, "hi": 21, "n": 20}}}
w = A.wild_met_text(REC)
ck("the block names each map's species with counts", "ROUTE_11 (217 wild fight(s), levels 9-17): SPEAROW x89, EKANS x78, DROWZEE x50" in w, w)
ck("...the busiest map first", w.index("ROUTE_24") < w.index("ROUTE_11") < w.index("DIGLETTS_CAVE"), w)
ck("...six species at most per map", "CATERPIE" not in w and "BELLSPROUT" in w, w)
ck("...a map with no level band still lists", "ROUTE_24 (863 wild fight(s)): ODDISH x202" in w, w)
ck("...and claims nothing about ground never fought on", "not listed and nothing is claimed" in w, w)
ck("it says what a species is nowhere", "PSYCHIC" not in w and "GROUND" not in w and "type" not in w.lower().replace("types", ""), w)
ck("no tallies, no block", A.wild_met_text({"offered": {}}) == "" and A.wild_met_text({}) == "")
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "explored.json"; p.write_text(json.dumps(REC))
    txt = A.observed_text(p)
    ck("the author's walked evidence carries it", "WILD POKEMON THIS RUN HAS FOUGHT, by map" in txt and "DROWZEE x50" in txt, txt[-500:])
bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
