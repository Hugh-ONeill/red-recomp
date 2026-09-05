#!/usr/bin/env python3
"""A plan can ask to come out somewhere new on a map it has been on.

2026-09-05: the ladder inserted "Exit the Seafoam Islands", which was the
right thing to insert, and the author could not write a plan for it at all
— fifteen rounds across three drafts, every one refused. The pincer:

  {"map": "ROUTE_20"}                 refused: the run has ALREADY stood on
                                      Route 20, so it holds before the plan
                                      takes a step and witnesses nothing
  {"map": "ROUTE_20",
   "not_area": "ROUTE_20|0,0"}        refused: nobody has stood in 0,0, so
                                      the exclusion excludes nothing

Both refusals are correct in their own terms. Route 20 is split by water:
the run knows the east half, and the objective is to come out on the west,
through Seafoam's far door. The author saw exactly that — it named its step
`exit_to_route_20_west` — and had no way to say it. Authoring failed, the
ladder pushed the leg later, and a hand repair of the outline made an hour
earlier came apart as a consequence.

The language could already say it: not_area takes a LIST, so excluding
every part you have stood in is the correct expression. But only if the
author enumerates them all from memory without missing one, which is
bookkeeping, and the side that keeps the ledger should do it.

So `new_part` names the map and the parts are filled in from the visit
ledger. It points at nothing: no coordinate, no direction, no destination,
only "somewhere on this map that is not somewhere I have been", which is
the run's own history. The same pincer in its Rock Tunnel shape is the
"refusing" example in the README; this is the shape it came back in.
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                    # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

VISITS = {"ROUTE_20|44,2": 35, "ROUTE_20|52,2": 27,
          "SEAFOAM_ISLANDS_1F|3,2": 28, "FUCHSIA_CITY|2,2": 9}

def plan_ending(dw):
    return {"goal": "Exit the Seafoam Islands",
            "subgoals": [
                {"id": "descend", "goal": "go down",
                 "done_when": {"map": "SEAFOAM_ISLANDS_B1F"}},
                {"id": "exit_to_route_20", "goal": "come out",
                 "done_when": dw}]}

def problems(dw):
    return A.validate(plan_ending(dw))

STOOD = "has ALREADY stood in"
NOTHING = "excludes nothing"

with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("run").mkdir()
    Path("run/explored.json").write_text(json.dumps({"visits": VISITS}))

    # the two refusals, exactly as they came back live
    ck("ending on a map the run has stood on is still refused",
       any(STOOD in p for p in problems({"map": "ROUTE_20"})))
    ck("...and excluding a part nobody has stood in is still refused",
       any(NOTHING in p for p in
           problems({"map": "ROUTE_20", "not_area": "ROUTE_20|0,0"})))

    # the way out
    pl = plan_ending({"new_part": "ROUTE_20"})
    probs = A.validate(pl)
    dw = pl["subgoals"][-1]["done_when"]
    ck("asking for a new part is not refused as already stood in",
       not any(STOOD in p for p in probs))
    ck("...nor as an exclusion that excludes nothing",
       not any(NOTHING in p for p in probs))
    ck("it freezes into the map it names", dw.get("map") == "ROUTE_20")
    ck("...and carves off every part of it the run has stood in",
       dw.get("not_area") == ["ROUTE_20|44,2", "ROUTE_20|52,2"])
    ck("...and only that map's parts",
       all(str(r).startswith("ROUTE_20|") for r in dw["not_area"]))
    ck("the word itself is spent, so nothing downstream meets it twice",
       "new_part" not in dw)

    # a map the run has never stood on: every part of it is a new part, and
    # an empty exclusion would be noise
    pl2 = plan_ending({"new_part": "CINNABAR_ISLAND"})
    A.validate(pl2)
    dw2 = pl2["subgoals"][-1]["done_when"]
    ck("a map never stood on freezes to the map alone",
       dw2 == {"map": "CINNABAR_ISLAND"})

    # inside a branch, because any_of is where alternatives live
    pl3 = plan_ending({"any_of": [{"new_part": "ROUTE_20"},
                                  {"map": "CINNABAR_ISLAND"}]})
    A.validate(pl3)
    alt = pl3["subgoals"][-1]["done_when"]["any_of"][0]
    ck("a branch of any_of is frozen too",
       alt.get("map") == "ROUTE_20" and alt.get("not_area") == [
           "ROUTE_20|44,2", "ROUTE_20|52,2"])

os.chdir(ROOT)
ck("the model is told the predicate exists",
   "new_part" in A.PRED_DOC if hasattr(A, "PRED_DOC") else True)
_doc = "".join(str(v) for v in vars(A).values() if isinstance(v, dict)
               and "not_area" in v for v in [v.get("new_part") or ""])
ck("...and told what it is for", "NEVER STOOD ON" in _doc)
ck("...and that it is written for them",
   "you do not have to name them" in _doc)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
