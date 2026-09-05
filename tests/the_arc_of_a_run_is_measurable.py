#!/usr/bin/env python3
"""A run's arc is measurable, and an absent counter is not a zero.

Written for planner/arc.py (2026-09-05, user: "its hard to say whether
things that helped at one point in the run hurt at other points during the
run, so its not noticed until the next run ... lets build the meter so we
dont go crazy").

The meter compares outcome rates across archived journals. Two ways it
could lie, both of which this pins:

1. A METRIC WHOSE COUNTER DID NOT EXIST YET scores zero, and zero reads as
   "the run never did that" when the truth is "nothing was writing it
   down". route_hop_surfed was born in August; every July journal would
   otherwise show a perfect no-rides-needed record. The meter must return
   nothing at all for a kind absent from a journal, and print "--".

2. A DENOMINATOR OF NONE is not a rate. A journal with no go_step has no
   opinion about routing, and dividing by it either explodes or invents a
   number to argue from.

Plus the arithmetic itself, and the quarter split, which is the axis the
question is actually about: helped early, hurt late.
"""
from __future__ import annotations
import sys, tempfile, json, os
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

# --- rate(): the two ways it must decline to answer -----------------
ck("a counter absent from the journal is not a zero",
   arc.rate({"go_step": 40}, ["route_hop_surfed"], "go_step") is None)
ck("...and one that IS present answers, even at zero occurrences",
   arc.rate({"go_step": 40, "route_hop_surfed": 0}, ["route_hop_surfed"],
            "go_step") == (0.0, 0, 40))
ck("a denominator of none is not a rate",
   arc.rate({"walk_edge_blocked": 3}, ["walk_edge_blocked"], "go_step") is None)
ck("the arithmetic is the arithmetic",
   arc.rate({"walk_edge_blocked": 3, "go_step": 12},
            ["walk_edge_blocked"], "go_step") == (0.25, 3, 12))
ck("numerator kinds are summed",
   arc.rate({"route_abandoned": 2, "route_walk_lost": 4, "go_step": 12},
            ["route_abandoned", "route_walk_lost"], "go_step")[1] == 6)
ck("a missing counter prints as two dashes, never as 0.0",
   arc.fmt(None, False).strip() == "--" and arc.fmt(None, True).strip() == "--")

with tempfile.TemporaryDirectory() as d:
    # eight legs: the first four route cleanly, the last four do not —
    # exactly the shape the question is about
    rows = []
    for leg in range(8):
        rows.append({"kind": "plan_start"})
        rows.append({"kind": "escalate_start"})
        rows.append({"kind": "escalate_proposal"})
        rows.append({"kind": "go_step"})
        rows.append({"kind": "explored", "to": "SEAFOAM_ISLANDS_B3F|1,0"})
        if leg >= 4:
            rows.append({"kind": "walk_edge_blocked"})
        rows.append({"kind": "escalate_success"})
    p = os.path.join(d, "executor_log.test.jsonl")
    journal(p, rows)
    r = arc.scan(p, keep_lines=True)

    c = r["counts"]
    ck("it counts the legs", c.get("plan_start") == 8)
    ck("it counts what it was given", c.get("go_step") == 8
       and c.get("walk_edge_blocked") == 4)
    ck("it records where the walking happened",
       r["maps"].get("SEAFOAM_ISLANDS_B3F") == 8)
    ck("the whole-run rate averages the two halves",
       arc.rate(c, ["walk_edge_blocked"], "go_step")[0] == 0.5)

    qs = arc.quarters(r)
    ck("the run splits into four quarters by leg", len(qs) == 4)
    got = [arc.rate(q, ["walk_edge_blocked"], "go_step") for q in qs]
    ck("the clean early quarters say nothing about a counter never fired",
       got[0] is None and got[1] is None)
    ck("...and the late quarters carry the whole of it",
       got[2] is not None and got[3] is not None
       and got[2][0] == 1.0 and got[3][0] == 1.0)

    # a journal too short to have quarters says so rather than inventing them
    p2 = os.path.join(d, "executor_log.tiny.jsonl")
    journal(p2, [{"kind": "plan_start"}, {"kind": "go_step"}])
    ck("a journal with too few legs gets no quarters",
       arc.quarters(arc.scan(p2, keep_lines=True)) == [])

    # explore steps that found nothing are their own outcome
    p3 = os.path.join(d, "executor_log.expl.jsonl")
    journal(p3, [{"kind": "plan_start"},
                 {"kind": "explore_step", "step": "sweep"},
                 {"kind": "explore_step", "step": "none"},
                 {"kind": "explore_step", "step": "none"},
                 {"kind": "explore_step", "step": "walk"}])
    c3 = arc.scan(p3)["counts"]
    ck("an explore that found nothing is counted apart",
       c3.get("explore_step") == 4 and c3.get("explore_none") == 2)
    ck("...and reads as half the explores",
       arc.rate(c3, ["explore_none"], "explore_step")[0] == 0.5)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
