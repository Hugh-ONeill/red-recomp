#!/usr/bin/env python3
"""Did the harness get better or worse between one run and the next?

The question the rig could not answer (user, 2026-09-05: "its hard to say
whether things that helped at one point in the run hurt at other points
during the run, so its not noticed until the next run"). Every fix in this
repo is validated twice, and both are blind to it:

  - an offline test written the same day, which pins THAT incident;
  - watching the live run at the exact spot it was stuck.

The second is selection bias by construction — you only ever see a change
where you made it. So a fix that helps at leg 12 and hurts at leg 42 is
invisible until a later run reaches leg 42, by which time a hundred other
things have changed too. This is the meter for that.

NO MODEL CALLS, NO GAME. It streams archived journals and counts outcomes
the executor already writes down, then puts the runs side by side.

  planner/arc.py                      every run/executor_log*.jsonl, oldest first
  planner/arc.py A.jsonl B.jsonl      just these, in the order given
  planner/arc.py --phases             each run split into quarters by leg
  planner/arc.py --diff               what moved between the last two
  planner/arc.py --kinds              which row kinds each journal contains

TWO TRAPS, BOTH LOAD-BEARING, BOTH REPORTED RATHER THAN HIDDEN:

1. A COUNTER THAT DID NOT EXIST YET READS AS ZERO. `route_hop_surfed` was
   born in August; a July journal scores 0 rides, which is not "it never
   rode", it is "nothing was writing that down". That is the very failure
   this tool exists to catch, reproduced inside the tool, so any metric
   whose numerator kind is ENTIRELY ABSENT from a journal prints "--" and
   not a number. Absence of the counter is never evidence about the run.

2. A RATE IS ALSO A STATEMENT ABOUT WHERE THE RUN WAS. Seafoam and Route
   20 are split by water, and a run that spends its routing budget there
   concentrates every water bug into a handful of hops; the same harness
   scores clean on a run that spent its budget in towns. So every table
   carries its denominators, and --phases shows where in the run the
   movement is. A number that moved is a QUESTION, never a verdict.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

KIND = re.compile(rb'"kind":\s*"([a-z_]+)"')
STEP = re.compile(rb'"step":\s*"([a-z_]+)"')
TOMAP = re.compile(rb'"to":\s*"([A-Z_0-9]+)\|')

# name -> (numerator kinds, denominator kind, "per what")
METRICS = [
    ("rounds/esc",  ["escalate_proposal"],     "escalate_start",    "esc"),
    ("esc/solved",  ["escalate_start"],        "escalate_success",  "solved"),
    ("refused%",    ["dead_end_refused", "escalate_repeat_refused",
                     "inference_refused"],     "escalate_proposal", "round"),
    ("blocked/go",  ["walk_edge_blocked"],     "go_step",           "go"),
    ("lost/go",     ["route_abandoned", "route_walk_lost"],
                                               "go_step",           "go"),
    ("unreach/esc", ["target_unreachable"],    "escalate_start",    "esc"),
    ("rides/go",    ["route_hop_surfed", "route_ride"],
                                               "go_step",           "go"),
    ("dryexpl%",    ["explore_none"],          "explore_step",      "explore"),
    ("fights/rnd",  ["battle_start"],          "escalate_proposal", "round"),
]


def scan(path: str, keep_lines: bool = False) -> dict:
    """One pass, regex only: an 89 MB journal is not worth json.loads.

    The per-row buffer is only built for --phases, because this box
    sheds background work under memory pressure and a meter that
    costs the run its RAM is not a meter."""
    counts: dict = {}
    maps: dict = {}
    legs: list = []          # line index of each plan_start, for --phases
    per_line: list = []      # (kind, line_no) for the kinds we bucket
    n = 0
    with open(path, "rb") as fh:
        for n, raw in enumerate(fh):
            m = KIND.search(raw)
            if not m:
                continue
            k = m.group(1).decode()
            # an explore step that found nothing is its own outcome
            if k == "explore_step":
                s = STEP.search(raw)
                if s and s.group(1) == b"none":
                    counts["explore_none"] = counts.get("explore_none", 0) + 1
            counts[k] = counts.get(k, 0) + 1
            if k == "plan_start":
                legs.append(n)
            elif k == "explored":
                t = TOMAP.search(raw)
                if t:
                    mp = t.group(1).decode()
                    maps[mp] = maps.get(mp, 0) + 1
            if keep_lines:
                per_line.append((k, n))
    return {"path": path, "counts": counts, "maps": maps, "legs": legs,
            "lines": n + 1, "per_line": per_line}


def rate(counts: dict, nums: list, den: str):
    """None when the counter never existed; else (value, numerator, denom)."""
    if not any(k in counts for k in nums):
        return None                      # trap 1: absence is not evidence
    d = counts.get(den, 0)
    if not d:
        return None
    v = sum(counts.get(k, 0) for k in nums)
    return (v / d, v, d)


def fmt(r, pct: bool) -> str:
    if r is None:
        return "   --"
    v = r[0]
    return f"{v * 100:4.1f}%" if pct else f"{v:5.2f}"


def label(path: str) -> str:
    ts = os.path.getmtime(path)
    import datetime
    return (datetime.datetime.fromtimestamp(ts).strftime("%m-%d") + " "
            + os.path.basename(path).replace("executor_log", "")
              .replace(".pre-discovery", "").replace(".jsonl", "")
              .strip(".") or "live")


def table(runs: list, phases: bool):
    head = f"{'run':<14}{'legs':>5}{'esc':>6}{'rnds':>7}"
    for name, _, _, _ in METRICS:
        head += f"{name:>12}"
    print(head)
    for r in runs:
        c = r["counts"]
        row = (f"{label(r['path']):<14}{c.get('plan_start', 0):>5}"
               f"{c.get('escalate_start', 0):>6}"
               f"{c.get('escalate_proposal', 0):>7}")
        for name, nums, den, _ in METRICS:
            row += f"{fmt(rate(c, nums, den), name.endswith('%')):>12}"
        print(row)
        top = sorted(r["maps"].items(), key=lambda kv: -kv[1])[:4]
        if top:
            print(f"{'':<14}where it walked: "
                  + ", ".join(f"{m} {n}" for m, n in top))
        if phases:
            for qi, q in enumerate(quarters(r), 1):
                sub = f"  q{qi}"
                line = f"{sub:<14}{'':>5}{q.get('escalate_start', 0):>6}" \
                       f"{q.get('escalate_proposal', 0):>7}"
                for name, nums, den, _ in METRICS:
                    line += f"{fmt(rate(q, nums, den), name.endswith('%')):>12}"
                print(line)


def quarters(r: dict) -> list:
    """Counts per quarter of the run, measured in LEGS attempted — the axis
    the question is actually about ("it helped early and hurt late")."""
    legs = r["legs"]
    if len(legs) < 4:
        return []
    cuts = [legs[int(len(legs) * f / 4)] for f in (1, 2, 3)] + [1 << 62]
    out = [{} for _ in range(4)]
    for k, ln in r["per_line"]:
        q = next(i for i, c in enumerate(cuts) if ln < c)
        out[q][k] = out[q].get(k, 0) + 1
    return out


def diff(a: dict, b: dict):
    print(f"\n{label(a['path'])}  ->  {label(b['path'])}")
    for name, nums, den, per in METRICS:
        ra, rb = rate(a["counts"], nums, den), rate(b["counts"], nums, den)
        if ra is None or rb is None:
            print(f"  {name:<12} -- not comparable: the counter is absent "
                  f"from one of them")
            continue
        # a denominator too small to argue from is said so, not rounded off
        thin = min(ra[2], rb[2]) < 30
        d = rb[0] - ra[0]
        pct = name.endswith("%")
        arrow = "  " if abs(d) < (0.02 if pct else 0.15) else (
            "UP" if d > 0 else "DOWN")
        print(f"  {name:<12}{fmt(ra, pct)} -> {fmt(rb, pct)}  {arrow:<4}"
              f"  ({ra[1]}/{ra[2]} -> {rb[1]}/{rb[2]})"
              + ("   [thin: too few to argue from]" if thin else ""))
    print("\nA number that moved is a question. Check `where it walked` "
          "above: a run that spent its budget in a water-split cave scores "
          "worse on routing with an identical harness.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--phases", action="store_true",
                    help="split each run into quarters by leg")
    ap.add_argument("--diff", action="store_true",
                    help="what moved between the last two runs")
    ap.add_argument("--kinds", action="store_true",
                    help="which row kinds each journal contains")
    ap.add_argument("--min-legs", type=int, default=3,
                    help="skip journals with fewer legs than this")
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob("run/executor_log*.jsonl"),
                            key=os.path.getmtime)
    runs = []
    for p in logs:
        if not Path(p).exists():
            continue
        r = scan(p, keep_lines=a.phases)
        if r["counts"].get("plan_start", 0) < a.min_legs:
            continue
        runs.append(r)
    if not runs:
        sys.exit("no journals with enough legs to compare")
    if a.kinds:
        for r in runs:
            print(f"\n{label(r['path'])}: "
                  + ", ".join(sorted(r["counts"])))
        return
    table(runs, a.phases)
    if a.diff and len(runs) >= 2:
        diff(runs[-2], runs[-1])


if __name__ == "__main__":
    main()
