#!/usr/bin/env python3
"""The footprint's cost, per map — footprint leftovers (g) and (h).

decay.py answered the headline (successes, distillation, escalations per
subgoal: the footprint era beat the pre-footprint baseline on all three,
2026-08-28). This answers the finer questions the design asked for:
model calls per map, ops per call, stalls (rounds with no progress op),
how much new ground each call learned (sightings per call), and whether
the round budget rebalanced the BIG floors now that a sweep is one round
however many steps it walks.

Read out of two journals, nothing written during play. Attribution: each
model call is an `escalate_feedback` record (one per round), whose `at`
is the region the party stood in when the round was judged; its `trace`
is the list of op outcomes the round ran. A stall is a round whose
`progress_ops` is 0. "Learned" is what the round's own words say: the
sweep's "N cell(s) newly on screen" and "came into view: a; b; c" (the
footprint era only — before it, every map was known whole), and the
`explored` records (an edge walked and recorded) for both eras.

  planner/footprint_cost.py                     default: pre vs post logs
  planner/footprint_cost.py --pre LOG --post LOG
  planner/footprint_cost.py --top 30
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"
PRE = RUN / "executor_log.054345.pre-discovery.jsonl"
POST = RUN / "executor_log.jsonl"

_SWEPT = re.compile(r"swept (\d+) step\(s\), (\d+) cell\(s\) newly on screen")


def _trace(t):
    if isinstance(t, list):
        return [str(x) for x in t]
    if isinstance(t, str):
        try:
            v = ast.literal_eval(t)
            if isinstance(v, list):
                return [str(x) for x in v]
        except (ValueError, SyntaxError):
            pass
        return [t]
    return []


def _sightings(s: str) -> int:
    if "came into view:" not in s:
        return 0
    body = s.split("came into view:", 1)[1]
    body = body.split(" — stopped", 1)[0]
    return len([p for p in body.split(";") if p.strip()])


def measure(path: Path) -> dict:
    per = defaultdict(lambda: {"calls": 0, "ops": 0, "stalls": 0, "sweeps": 0,
                               "swept_steps": 0, "new_cells": 0,
                               "sightings": 0, "explored": 0,
                               "attempts": set()})
    procs = 0
    last_dt = -1.0
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            dt = r.get("dt")
            if isinstance(dt, (int, float)):
                if dt < last_dt:
                    procs += 1
                last_dt = dt
            k = r.get("kind")
            if k == "escalate_feedback":
                at = str(r.get("at") or "")
                if not at or "None" in at:
                    continue
                m = at.split("|")[0]
                d = per[m]
                d["calls"] += 1
                d["attempts"].add((procs, str(r.get("subgoal"))))
                tr = _trace(r.get("trace"))
                d["ops"] += len(tr)
                if int(r.get("progress_ops") or 0) == 0:
                    d["stalls"] += 1
                for s in tr:
                    mm = _SWEPT.search(s)
                    if mm:
                        d["sweeps"] += 1
                        d["swept_steps"] += int(mm.group(1))
                        d["new_cells"] += int(mm.group(2))
                    d["sightings"] += _sightings(s)
            elif k == "explored":
                frm = str(r.get("frm") or r.get("at") or "")
                if frm and "None" not in frm:
                    per[frm.split("|")[0]]["explored"] += 1
    return per


def _tot(per):
    t = {"calls": 0, "ops": 0, "stalls": 0, "sweeps": 0, "swept_steps": 0,
         "new_cells": 0, "sightings": 0, "explored": 0}
    for d in per.values():
        for k in t:
            t[k] += d[k]
    return t


def _fmt_era(name, per, top):
    t = _tot(per)
    c = max(1, t["calls"])
    out = [f"{name}: {t['calls']} model calls over {len(per)} maps — "
           f"{t['ops'] / c:.2f} ops/call, {100 * t['stalls'] / c:.1f}% stalls "
           f"(rounds with no progress op), {t['explored'] / c:.2f} edges "
           f"recorded/call, {t['sweeps']} sweeps ({100 * t['sweeps'] / c:.1f}% "
           f"of calls) walking {t['swept_steps']} steps, "
           f"{t['new_cells']} cells newly on screen "
           f"({t['new_cells'] / c:.1f}/call), {t['sightings']} sightings "
           f"({t['sightings'] / c:.2f}/call)"]
    out.append(f"  {'map':28s} {'calls':>5s} {'attempts':>8s} {'calls/att':>9s} "
               f"{'ops/call':>8s} {'stall%':>6s} {'edges/call':>10s} "
               f"{'sweep%':>6s} {'cells/call':>10s} {'sight/call':>10s}")
    rows = sorted(per.items(), key=lambda kv: -kv[1]["calls"])[:top]
    for m, d in rows:
        cc = max(1, d["calls"])
        att = max(1, len(d["attempts"]))
        out.append(f"  {m[:28]:28s} {d['calls']:5d} {len(d['attempts']):8d} "
                   f"{d['calls'] / att:9.1f} {d['ops'] / cc:8.2f} "
                   f"{100 * d['stalls'] / cc:6.1f} {d['explored'] / cc:10.2f} "
                   f"{100 * d['sweeps'] / cc:6.1f} {d['new_cells'] / cc:10.1f} "
                   f"{d['sightings'] / cc:10.2f}")
    return "\n".join(out)


def _fmt_shared(pre, post, top):
    shared = [m for m in pre if m in post]
    shared.sort(key=lambda m: -(pre[m]["calls"] + post[m]["calls"]))
    out = ["SHARED MAPS (both runs stood there) — the honest comparison; "
           "'att' = distinct (process, subgoal) pairs that escalated there, "
           "calls/att = the round budget a map actually consumed per attempt"]
    out.append(f"  {'map':28s} {'calls pre':>9s} {'post':>5s} | "
               f"{'calls/att pre':>13s} {'post':>5s} | {'stall% pre':>10s} "
               f"{'post':>5s} | {'ops/call pre':>12s} {'post':>5s}")
    for m in shared[:top]:
        a, b = pre[m], post[m]
        ca, cb = max(1, a["calls"]), max(1, b["calls"])
        out.append(f"  {m[:28]:28s} {a['calls']:9d} {b['calls']:5d} | "
                   f"{a['calls'] / max(1, len(a['attempts'])):13.1f} "
                   f"{b['calls'] / max(1, len(b['attempts'])):5.1f} | "
                   f"{100 * a['stalls'] / ca:10.1f} {100 * b['stalls'] / cb:5.1f} | "
                   f"{a['ops'] / ca:12.2f} {b['ops'] / cb:5.2f}")
    # the big floors: the maps that ate the most rounds per attempt before
    big = sorted(shared, key=lambda m: -(pre[m]["calls"] / max(1, len(pre[m]["attempts"]))))[:12]
    out.append("")
    out.append("BIG FLOORS (h): the 12 shared maps with the most rounds per "
               "attempt BEFORE the footprint, and what they cost after — a "
               "sweep is one round however many steps, so if the budget "
               "rebalanced, calls/att should fall where sweep% is high")
    out.append(f"  {'map':28s} {'calls/att pre':>13s} {'post':>5s} | "
               f"{'stall% pre':>10s} {'post':>5s} | {'sweep% post':>11s} "
               f"{'steps/sweep':>11s} {'cells/call':>10s}")
    for m in big:
        a, b = pre[m], post[m]
        cb = max(1, b["calls"])
        out.append(f"  {m[:28]:28s} "
                   f"{a['calls'] / max(1, len(a['attempts'])):13.1f} "
                   f"{b['calls'] / max(1, len(b['attempts'])):5.1f} | "
                   f"{100 * a['stalls'] / max(1, a['calls']):10.1f} "
                   f"{100 * b['stalls'] / cb:5.1f} | "
                   f"{100 * b['sweeps'] / cb:11.1f} "
                   f"{b['swept_steps'] / max(1, b['sweeps']):11.1f} "
                   f"{b['new_cells'] / cb:10.1f}")
    # the aggregate over the big floors, which is the (h) verdict
    pa = sum(pre[m]["calls"] for m in big); pb = sum(post[m]["calls"] for m in big)
    aa = sum(len(pre[m]["attempts"]) for m in big); ab = sum(len(post[m]["attempts"]) for m in big)
    sa = sum(pre[m]["stalls"] for m in big); sb = sum(post[m]["stalls"] for m in big)
    out.append(f"  {'ALL 12 BIG FLOORS':28s} {pa / max(1, aa):13.1f} "
               f"{pb / max(1, ab):5.1f} | {100 * sa / max(1, pa):10.1f} "
               f"{100 * sb / max(1, pb):5.1f}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pre", type=Path, default=PRE)
    ap.add_argument("--post", type=Path, default=POST)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    pre, post = measure(a.pre), measure(a.post)
    print(_fmt_era("PRE-FOOTPRINT  " + a.pre.name, pre, a.top))
    print()
    print(_fmt_era("FOOTPRINT ERA  " + a.post.name, post, a.top))
    print()
    print(_fmt_shared(pre, post, a.top))


if __name__ == "__main__":
    main()
