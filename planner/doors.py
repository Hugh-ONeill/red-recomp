#!/usr/bin/env python3
"""How often the run takes the same doors.

    planner/doors.py                          # the live journal, whole run
    planner/doors.py --goal "S.S. Anne"       # only legs whose goal says this
    planner/doors.py --last 3                 # the last three legs
    planner/doors.py A.jsonl B.jsonl --goal Anne

Reads the `explored` rows the executor writes on every door transition
(frm region, via tile, to region). A door is counted by the map it stands
on and the part it opens onto, so twin tiles are one door and the six
cabin doors of one corridor are six. Reports how many transitions there
were, how many distinct doors, how many were taken once, the share of
transitions that immediately undid the one before (there-and-back), and
the most re-taken doors. No model calls; nothing here reaches the model.

Written for run 16's S.S. Anne stretch (2026-09-07; user: "can we tell how
often its visiting the same doors"): 125 transitions through 40 doors, 68
of 124 consecutive pairs there-and-back, one cabin corridor taken 26 times
— while the step waited on a flag set on another floor.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os


def rows_of(path):
    with open(path, "rb") as fh:
        for raw in fh:
            if raw.startswith(b"{"):
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue


def stretch(path, goal_sub=None, last=None):
    """The explored rows of the chosen legs, in order."""
    rows = list(rows_of(path))
    starts = [i for i, r in enumerate(rows) if r.get("kind") == "plan_start"]
    keep = [True] * len(rows)
    if goal_sub or last:
        keep = [False] * len(rows)
        goals = []          # (start index, goal) per distinct consecutive goal
        for i in starts:
            g = rows[i].get("goal") or ""
            if not goals or goals[-1][1] != g:
                goals.append((i, g))
        chosen = set()
        if goal_sub:
            chosen |= {k for k, (_, g) in enumerate(goals) if goal_sub.lower() in g.lower()}
        if last:
            chosen |= set(range(max(0, len(goals) - last), len(goals)))
        for k in chosen:
            a = goals[k][0]
            b = goals[k + 1][0] if k + 1 < len(goals) else len(rows)
            for j in range(a, b):
                keep[j] = True
    return [r for r, k in zip(rows, keep) if k and r.get("kind") == "explored"]


def _map(region):
    return str(region or "").split("|")[0]


def report(ex, label):
    if not ex:
        print(f"{label}: no door transitions")
        return
    doors = collections.Counter((_map(r.get("frm")), r.get("to")) for r in ex)
    seq = [(_map(r.get("frm")), _map(r.get("to"))) for r in ex]
    back = sum(1 for a, b in zip(seq, seq[1:]) if a[0] == b[1] and a[1] == b[0])
    once = sum(1 for n in doors.values() if n == 1)
    print(f"{label}: {len(ex)} door transitions through {len(doors)} distinct doors; "
          f"{once} taken once; {back} of {max(1, len(seq) - 1)} consecutive pairs were "
          f"there-and-back ({100 * back / max(1, len(seq) - 1):.0f}%)")
    print("  most re-taken (times  from map -> part it opens onto):")
    for (fm, to), n in doors.most_common(8):
        if n < 2:
            break
        print(f"    {n:3}  {fm} -> {to}")
    maps = collections.Counter(m for pair in seq for m in pair)
    print("  maps in the shuttle: " + ", ".join(f"{m} x{n}" for m, n in maps.most_common(6)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--goal", help="only legs whose goal contains this")
    ap.add_argument("--last", type=int, help="only the last N legs")
    a = ap.parse_args()
    logs = a.logs or ["run/executor_log.jsonl"]
    for p in logs:
        if not os.path.exists(p):
            print(f"{p}: missing")
            continue
        ex = stretch(p, a.goal, a.last)
        report(ex, os.path.basename(p) + (f" [{a.goal}]" if a.goal else "") + (f" [last {a.last}]" if a.last else ""))


if __name__ == "__main__":
    main()
