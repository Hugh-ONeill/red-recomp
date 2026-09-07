#!/usr/bin/env python3
"""Best splits: the quickest each leg has ever been played, and the sum.

    planner/splits.py                       # every run/executor_log*.jsonl
    planner/splits.py A.jsonl B.jsonl       # just these
    planner/splits.py --keep "Reach Pewter City"      # mark the best as kept
    planner/splits.py --keep "Reach Pewter City" --dir run/saves/leg_06...   # a named one

A run is a chain of legs, each played from the checkpoint the leg before it
left. After a harness fix is confirmed on a leg (replayed from its
checkpoint, not stuck the same way, faster), the confirmed play becomes that
leg's split, and its end checkpoint the base the next leg is played from.
Keep only the best split of every leg and the run they compose is the
quickest the harness can currently do — under the constraints as they stand
today, and re-composable as they evolve (user, 2026-09-07: "keep only the
best splits after the fixes have been hopefully confirmed and have as a
result essentially the quickest the run can theoretically be").

This reads the journals: every plan_start opens an attempt, consecutive
attempts at one goal are an episode of that leg, an episode is complete
when its last attempt ended in plan_complete (or the objective was met
early). Time is the clock inside attempts (dt) and, where the rows carry it
(2026-09-07 on), the wall clock across the episode including authoring.
The kept splits live in plans/splits.json: goal -> {checkpoint dir, journal,
seconds, rev}. Nothing here reaches the model.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

KIND = re.compile(rb'"kind": "([a-z_]+)"')
GOAL = re.compile(rb'"goal": "((?:[^"\\]|\\.)*)"')
DT = re.compile(rb'"dt": ([0-9.]+)')
TT = re.compile(rb'"t": ([0-9.]+)')
REV = re.compile(rb'"rev": "([^"]*)"')
CKDIR = re.compile(rb'"dir": "([^"]*)"')
END_OK = {"plan_complete", "plan_objective_met_early"}
END_BAD = {"plan_failed_at"}
SPLITS = Path("plans/splits.json")


def hms(secs) -> str:
    if secs is None:
        return "--"
    secs = int(secs)
    if secs >= 3600:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
    return f"{secs // 60}m{secs % 60:02d}s"


def norm(goal: str) -> str:
    return re.sub(r"\s+", " ", (goal or "").strip().lower())


def episodes(path: str) -> list:
    """Consecutive attempts at one goal, with what they cost and how they ended."""
    out = []
    cur = None          # the open episode
    att = None          # the open attempt
    with open(path, "rb") as fh:
        for raw in fh:
            m = KIND.search(raw)
            if not m:
                continue
            k = m.group(1).decode()
            _dt = DT.search(raw); dt = float(_dt.group(1)) if _dt else None
            _tt = TT.search(raw); tt = float(_tt.group(1)) if _tt else None
            if k == "plan_start":
                g = GOAL.search(raw)
                goal = (g.group(1).decode("utf-8", "replace")
                        .encode().decode("unicode_escape", "replace") if g else "")
                _rv = REV.search(raw)
                rev = _rv.group(1).decode() if _rv else ""
                if cur is None or norm(goal) != norm(cur["goal"]):
                    if cur is not None:
                        out.append(cur)
                    cur = {"goal": goal, "path": path, "attempts": 0,
                           "rounds": 0, "exec": 0.0, "t_first": tt,
                           "t_last": tt, "revs": [], "end": "open",
                           "checkpoint": None}
                att = {"max_dt": dt or 0.0}
                cur["attempts"] += 1
                if rev and rev not in cur["revs"]:
                    cur["revs"].append(rev)
                continue
            if cur is None:
                continue
            if tt is not None:
                if cur["t_first"] is None:
                    cur["t_first"] = tt
                cur["t_last"] = tt
            if dt is not None and att is not None and dt > att["max_dt"]:
                att["max_dt"] = dt
            if k == "escalate_context":
                cur["rounds"] += 1
            elif k == "checkpoint":
                d = CKDIR.search(raw)
                if d:
                    cur["checkpoint"] = d.group(1).decode()
            elif k in END_OK or k in END_BAD:
                if att is not None:
                    cur["exec"] += att["max_dt"]
                    att = None
                cur["end"] = "complete" if k in END_OK else "failed"
    if cur is not None:
        if att is not None:
            cur["exec"] += att["max_dt"]
        out.append(cur)
    for e in out:
        e["wall"] = ((e["t_last"] - e["t_first"])
                     if (e["t_first"] is not None and e["t_last"] is not None) else None)
    return out


def load_kept() -> dict:
    try:
        return json.loads(SPLITS.read_text())
    except (OSError, ValueError):
        return {}


def label(path: str) -> str:
    return os.path.basename(path).replace("executor_log", "").replace(".jsonl", "").strip(".") or "live"


def cost(e) -> float:
    """What a split is ranked by: the wall clock where the rows carry it,
    else the clock inside attempts."""
    return e["wall"] if e["wall"] is not None else e["exec"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--keep", help="mark this goal's best complete episode as the kept split")
    ap.add_argument("--dir", help="with --keep: the checkpoint dir to keep instead of the best's")
    ap.add_argument("--all", action="store_true", help="list every episode, not only the best")
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob("run/executor_log*.jsonl"), key=os.path.getmtime)
    eps = []
    for p in logs:
        if Path(p).exists():
            eps.extend(episodes(p))
    by_goal: dict = {}
    for e in eps:
        by_goal.setdefault(norm(e["goal"]), []).append(e)
    kept = load_kept()

    if a.keep:
        key = norm(a.keep)
        cands = [e for e in by_goal.get(key, []) if e["end"] == "complete"]
        if not cands and not a.dir:
            sys.exit(f"no complete episode of {a.keep!r} in these journals")
        best = min(cands, key=cost) if cands else None
        d = a.dir or (best or {}).get("checkpoint")
        kept[key] = {"goal": a.keep, "checkpoint": d, "journal": (best or {}).get("path"),
                     "seconds": cost(best) if best else None,
                     "rounds": (best or {}).get("rounds"), "revs": (best or {}).get("revs")}
        SPLITS.write_text(json.dumps(kept, indent=1))
        print(f"kept {a.keep!r}: {hms(kept[key]['seconds'])}, checkpoint {d}")
        return

    # the outline's order, so the table reads as the run
    try:
        order = [l.strip() for l in Path("plans/outline.txt").read_text().splitlines() if l.strip()]
    except OSError:
        order = []
    goals = [g for g in order if norm(g) in by_goal]
    goals += [e["goal"] for k, es in by_goal.items() for e in es[:1] if k not in {norm(g) for g in goals}]
    print(f"{'leg':<44} {'best':>8} {'rnds':>5} {'runs':>4} {'kept':>8}  from")
    total_best, total_kept, n_best = 0.0, 0.0, 0
    for g in goals:
        es = by_goal[norm(g)]
        done = [e for e in es if e["end"] == "complete"]
        best = min(done, key=cost) if done else None
        k = kept.get(norm(g))
        if best:
            total_best += cost(best); n_best += 1
        if k and k.get("seconds") is not None:
            total_kept += k["seconds"]
        star = "*" if best and best["wall"] is None else ""
        print(f"{g[:44]:<44} {(hms(cost(best)) + star) if best else '--':>8} "
              f"{(best or {}).get('rounds', '--') if best else '--':>5} "
              f"{len(es):>4} {hms(k['seconds']) if k else '--':>8}  "
              f"{label(best['path']) + (' rev ' + ','.join(best['revs']) if best and best['revs'] else '') if best else 'never completed'}")
        if a.all:
            for e in sorted(es, key=cost):
                print(f"    {e['end']:<9} {hms(cost(e)):>8} {e['rounds']:>5} rounds "
                      f"{e['attempts']} attempt(s)  {label(e['path'])}"
                      + (f"  rev {','.join(e['revs'])}" if e["revs"] else "")
                      + (f"  -> {e['checkpoint']}" if e["checkpoint"] else ""))
    print(f"\nSUM OF BEST over {n_best} leg(s) with a completed play: {hms(total_best)}"
          + (f"   (kept: {hms(total_kept)} over {len(kept)} kept split(s))" if kept else "")
          + "\n* = clock inside attempts only (rows without the wall clock); a leg's episode "
            "spans its consecutive attempts, and 'complete' means its last attempt ended in "
            "plan_complete. The compose step is: replay_from.sh <the kept checkpoint of leg N> "
            "and play leg N+1.")


if __name__ == "__main__":
    main()
