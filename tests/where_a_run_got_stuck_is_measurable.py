#!/usr/bin/env python3
"""Where a run got stuck is a place, and places are comparable across runs.

2026-09-05, the user naming this run's sticking points from memory: "mt
moon taking *forever* this run, rock tunnel, the thirsty guards and
celadons mart (as well as all the other marts it returns to for no good
reason), pokemon tower / rescue mr fuji, silph co (but it was better this
run i think), safari a little bit this run around, then seafoam, now this
leg" — and asking that we "measure where those sticking points are and
watch those areas specifically for regression signs next run".

The journal already says where the party stood at every round: each page
opens with WHERE YOU STAND. arc.py --areas buckets a run's rounds by that,
folded to the BUILDING (Mt Moon's three floors are one place; so are a
mart's five and the Safari Zone's four maps), and puts the last two runs
side by side on the named spots plus whatever else is large.

Two things it must not do: read a journal whose pages predate the marker
as a run that went nowhere (it prints "--"), and compare raw rounds alone
when one run is three times the length of the other (share rides beside
them).
"""
from __future__ import annotations
import sys, tempfile, json, os, io, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import arc                                        # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def journal(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

def ctx(where):
    return {"kind": "escalate_context", "subgoal": "x",
            "memory": f"\nWHERE YOU STAND: {where} — indoors, no edges"}

# --- the fold: one building however many floors or halves ---------------
ck("floors fold to the building", arc.building("MT_MOON_B2F") == "MT_MOON"
   and arc.building("SILPH_CO_11F") == "SILPH_CO"
   and arc.building("CELADON_MART_ROOF") == "CELADON_MART"
   and arc.building("ROCK_TUNNEL_1F") == "ROCK_TUNNEL")
ck("a gate's two floors are one gate", arc.building("ROUTE_11_GATE_2F") == "ROUTE_11_GATE")
ck("the Safari Zone's four maps are one place",
   arc.building("SAFARI_ZONE_EAST") == "SAFARI_ZONE"
   and arc.building("SAFARI_ZONE_GATE") == "SAFARI_ZONE")
ck("a town is itself", arc.building("CERULEAN_CITY") == "CERULEAN_CITY")
ck("the Center by Mt Moon is not the cave",
   arc.building("MT_MOON_POKECENTER") == "MT_MOON_POKECENTER")
ck("the named sticking points are all on the watch-list, as buildings",
   all(b in arc.WATCH for b in ("MT_MOON", "ROCK_TUNNEL", "ROUTE_7_GATE",
                                 "CELADON_MART", "POKEMON_TOWER",
                                 "MR_FUJIS_HOUSE", "SILPH_CO", "SAFARI_ZONE",
                                 "SEAFOAM_ISLANDS", "POKEMON_MANSION")))

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "executor_log.a.jsonl")
    journal(p, [{"kind": "plan_start"}] * 3
            + [ctx("MT_MOON_B1F|3,4")] * 3 + [ctx("MT_MOON_B2F|1,1")] * 2
            + [ctx("CELADON_MART_ROOF|2,2"), ctx("CELADON_MART_2F|5,5"),
               ctx("SAFARI_ZONE_EAST|9,9"), ctx("CERULEAN_MART|1,1"),
               {"kind": "escalate_context", "memory": "no place on this page"}])
    r = arc.scan(p)
    ck("rounds are bucketed by building",
       r["areas"] == {"MT_MOON": 5, "CELADON_MART": 2, "SAFARI_ZONE": 1,
                      "CERULEAN_MART": 1})
    ck("only rounds that said where they stood are placed",
       r["located"] == 9 and r["counts"]["escalate_context"] == 10)
    rows = arc.areas_rows(r)
    ck("the table is largest first, with the share of placed rounds",
       rows[0] == ("MT_MOON", 5, 5 / 9) and rows[1][0] == "CELADON_MART")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        arc.areas_table([r])
    t = out.getvalue()
    ck("...and every mart together, since returning to marts is the complaint",
       "(every _MART together)" in t and "     3  " in t)

    # a journal from before the marker existed
    p0 = os.path.join(d, "executor_log.old.jsonl")
    journal(p0, [{"kind": "plan_start"}] * 3
            + [{"kind": "escalate_context", "memory": "You are somewhere."}] * 4)
    r0 = arc.scan(p0)
    ck("pages that never said where they stood place nothing", r0["located"] == 0)
    ck("...and the table declines rather than printing zeros",
       arc.areas_rows(r0) is None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        arc.areas_table([r0])
    ck("...in words", "no WHERE YOU STAND line" in out.getvalue())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        arc.areas_diff(r0, r)
    ck("a diff against it says not comparable", "not comparable" in out.getvalue())

    # two runs of different length: the place that grew is marked
    p2 = os.path.join(d, "executor_log.b.jsonl")
    journal(p2, [{"kind": "plan_start"}] * 3
            + [ctx("MT_MOON_1F|0,0")] * 60 + [ctx("CERULEAN_CITY|0,0")] * 40)
    p1 = os.path.join(d, "executor_log.c.jsonl")
    journal(p1, [{"kind": "plan_start"}] * 3
            + [ctx("MT_MOON_1F|0,0")] * 5 + [ctx("CERULEAN_CITY|0,0")] * 45)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        arc.areas_diff(arc.scan(p1), arc.scan(p2))
    t = out.getvalue()
    ck("the diff shows rounds and share for both runs",
       "MT_MOON" in t and "10.0%" in t and "60.0%" in t)
    ck("...and marks the place whose share grew", "UP" in t.split("MT_MOON")[1].split("\n")[0])
    ck("...and the one that shrank", "DOWN" in t.split("CERULEAN_CITY")[1].split("\n")[0])
    ck("...and says a moved number is a question", "question, not a verdict" in t)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
