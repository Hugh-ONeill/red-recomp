#!/usr/bin/env python3
"""A printed road the run has stood beside and never aimed a crossing at is
said as untried, not as a road that failed.

The author's page listed every printed road out of a well-trodden map whose
far side was never reached as "never once got through", under a preamble
saying a route using it HAS NOT WORKED YET and a plan built on one needs
something to change first. Lavender's west road read "stood there 12x and
never once got through" with no crossing ever aimed at it, and the author
planned an eleven-step trek around the one road to Celadon (run 17,
2026-09-14). The record can tell the two apart: a tried road has a crossing
attempt on its book, a no-cross record, a sealed seam, or something pressed
on that map while aiming at the far side; an untried one has nothing.
Nothing here says which road to take or what lies down it.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the printed map draws the roads this test leans on",
   A.MAP_EDGES.get("LAVENDER_TOWN", {}).get("west") == "ROUTE_8"
   and A.MAP_EDGES.get("ROUTE_12", {}).get("west") == "ROUTE_11", (A.MAP_EDGES.get("LAVENDER_TOWN"), A.MAP_EDGES.get("ROUTE_12")))

def render(**extra):
    d = {"visits": {"LAVENDER_TOWN|6,0": 12, "ROUTE_12|10,21": 6, "ROUTE_12|8,0": 13},
         "explored": {"LAVENDER_TOWN|6,0": {"south": {"to": "ROUTE_12|8,0", "n": 5}},
                      "ROUTE_12|8,0": {"north": {"to": "LAVENDER_TOWN|6,0", "n": 5}},
                      "ROUTE_12|10,21": {}},
         "outcomes": {"map:ROUTE_11|ROUTE_12|10,21":
                      {"west": {"n": 2, "last": "FAILED — the west seam of ROUTE_12 cannot be walked to from here"}}},
         "no_cross": {"ROUTE_12|10,21": ["west"]}}
    d.update(extra)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, f); f.close()
    return A.observed_text(Path(f.name))

t = render()
def line(text, m, nb):
    return next((l for l in text.splitlines() if f"{m} --" in l and f"--> {nb}" in l and "stood in" in l), "")
def block(text, head):
    i = text.find(head)
    if i < 0:
        return ""
    j = text.find("\n\n", i + len(head))
    return text[i:j if j > 0 else None]

lav = line(t, "LAVENDER_TOWN", "ROUTE_8")
r12 = line(t, "ROUTE_12", "ROUTE_11")
ck("a road never aimed at is listed as never tried", "NEVER TRIED" in lav and "no crossing of yours was ever aimed that way" in lav, lav)
ck("...still with the bare fact that its far side was never reached", "never once reached ROUTE_8" in lav, lav)
ck("...under its own heading", "LAVENDER_TOWN --west--> ROUTE_8" in block(t, "ROADS YOU HAVE STOOD BESIDE AND NEVER TRIED"))
ck("...and not under the one that says a route using it has not worked",
   "LAVENDER_TOWN --west" not in block(t, "ROADS YOU HAVE STOOD BESIDE AND NEVER CROSSED"))
ck("the untried heading claims nothing either way",
   "nothing about it has worked, and nothing has failed" in t and "HAS NOT WORKED YET" not in block(t, "ROADS YOU HAVE STOOD BESIDE AND NEVER TRIED"))
ck("a road with two failed crossings on its book is a road that failed, with the count",
   "aimed at it 2x" in r12 and "never once reached ROUTE_11" in r12, r12)
ck("...under the heading that says so", "ROUTE_12 --west--> ROUTE_11" in block(t, "ROADS YOU HAVE STOOD BESIDE AND NEVER CROSSED"))
ck("the grouped block tells the two apart, row by row",
   "from LAVENDER_TOWN heading west: stood there 12x and never once tried it" in t
   and "from ROUTE_12 heading west: stood there 19x, aimed at it 2x, never once got through" in t, t[t.find("EVERY PRINTED WAY"):][:900])

# what counts as tried
t2 = render(outcomes={"map:ROUTE_8|LAVENDER_TOWN|6,0": {"LAVENDERTOWN_GUARD": {"n": 1, "last": 'it said: "the road is closed"'}}}, no_cross={})
ck("something pressed on the map while aiming at the far side counts as a try",
   "aimed at it 1x" in line(t2, "LAVENDER_TOWN", "ROUTE_8") and "NEVER TRIED" not in line(t2, "LAVENDER_TOWN", "ROUTE_8"), line(t2, "LAVENDER_TOWN", "ROUTE_8"))
t3 = render(outcomes={"map:ROUTE_8|LAVENDER_TOWN|6,0": {"TEXT_LAVENDER_SIGN": {"n": 3, "last": 'it said: "LAVENDER TOWN"'}}}, no_cross={})
ck("...but a signpost read while aiming there does not", "NEVER TRIED" in line(t3, "LAVENDER_TOWN", "ROUTE_8"))
t4 = render(outcomes={}, no_cross={}, bad_seam=[["LAVENDER_TOWN|6,0", "west", "ROUTE_8|0,0"]])
ck("a sealed seam counts as tried", "aimed at it 1x" in line(t4, "LAVENDER_TOWN", "ROUTE_8"))
t5 = render(outcomes={}, no_cross={})
ck("with nothing on any book, every such road is untried and the grouped block still renders",
   "NEVER TRIED" in line(t5, "ROUTE_12", "ROUTE_11") and "EVERY PRINTED WAY INTO A PLACE" in t5 and "NEVER CROSSED" not in t5)

ck("nothing here points down a road",
   not any(w in t.lower() for w in ("you should", "go west", "take the west", "head west", "the way to celadon")))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:500])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
