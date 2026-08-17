#!/usr/bin/env python3
"""The escalation decay curve — the number that says whether any of this
compounds.

SPD_DESIGN names it "the headline metric" and nothing computed it. The
question it answers: when the run meets the same leg again, does it need
LESS of the model than it did last time? If yes, the distillation loop is
working and the harness is turning live piloting into stored route. If no,
escalation is the runtime pilot and every wall gets re-solved for ever —
which is what the audit measured (94% of executor wall time is inference,
48% of escalations succeed, 24% of successes get distilled).

Everything here is read out of run/executor_log.jsonl. Nothing extra is
written during play.

WHAT THE JOURNAL CANNOT TELL US, said up front rather than papered over:
  * There is no run id in the records. A new executor PROCESS is detected
    by `dt` going backwards, which is exact — dt is seconds since that
    process started — but it means "attempt" here is "executor process",
    not campaign attempt number. In practice fresh_run.sh launches one
    executor per attempt, so they coincide.
  * The log is append-only across many chains and many code versions, so
    attempt 1 and attempt 6 of a leg can be days and a hundred commits
    apart. --since bounds that.
  * A leg is identified by its plan's GOAL TEXT, because that is what the
    journal records and what survives a re-author into leg_N.vM.json.

  planner/decay.py                    the live log
  planner/decay.py --since 12:00      only processes starting after today's HH:MM
  planner/decay.py --subgoals         which subgoals are the escalation sinks
  planner/decay.py LOG [LOG ...]      specific logs, oldest first
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"


def read(paths):
    """Split the journal into executor processes. A process boundary is `dt`
    going backwards; nothing else in the record marks one."""
    procs, cur = [], None
    for p in paths:
        try:
            lines = Path(p).read_text().splitlines()
        except OSError:
            continue
        last_dt = -1.0
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            dt = d.get("dt")
            if not isinstance(dt, (int, float)):
                continue
            if cur is None or dt < last_dt:
                cur = {"file": Path(p).name, "recs": [], "span": 0.0}
                procs.append(cur)
            last_dt = dt
            cur["span"] = max(cur["span"], dt)
            cur["recs"].append(d)
    return procs


def summarise(proc):
    """Per-plan tallies for one executor process."""
    out = defaultdict(lambda: {"esc": 0, "won": 0, "distilled": 0,
                               "done": 0, "failed": 0, "infer": 0.0,
                               "calls": 0, "subgoals": Counter()})
    goal, waiting = None, None
    for d in proc["recs"]:
        k = d.get("kind")
        if k == "plan_start":
            goal = d.get("goal")
        if goal is None:
            continue
        s = out[goal]
        if k == "escalate_start":
            s["esc"] += 1
            s["subgoals"][d.get("subgoal")] += 1
        elif k == "escalate_success":
            s["won"] += 1
            # A SUBGOAL FINISHED BY ESCALATION IS STILL FINISHED.
            # `subgoal_done` is logged only on the macro-replay path, so
            # using it alone as the denominator scored every leg that
            # escalated its way through as "completed nothing" — which is
            # exactly backwards, and made the whole per-subgoal column read
            # as dashes.
            s["done"] += 1
        elif k == "distilled":
            s["distilled"] += 1
        elif k == "subgoal_done":
            s["done"] += 1
        elif k == "subgoal_failed":
            s["failed"] += 1
        # a model call is the gap from the last context/feedback to the
        # proposal it produced
        if k in ("escalate_context", "escalate_note"):
            waiting = d.get("dt")
        elif k == "escalate_proposal" and waiting is not None:
            gap = (d.get("dt") or 0) - waiting
            if 0 < gap < 600:
                s["infer"] += gap
                s["calls"] += 1
            waiting = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*", default=None)
    ap.add_argument("--since", default=None,
                    help="only processes whose file mtime is after HH:MM "
                         "today (crude, but the journal carries no clock)")
    ap.add_argument("--subgoals", action="store_true",
                    help="also list the subgoals soaking up the escalations")
    args = ap.parse_args()
    paths = args.logs or [RUN / "executor_log.jsonl"]
    procs = read(paths)
    if not procs:
        sys.exit("no journal records found")

    # ---- the curve: for each leg, escalations on each successive attempt
    per_goal = defaultdict(list)
    for i, proc in enumerate(procs):
        for goal, s in summarise(proc).items():
            if s["esc"] or s["done"]:
                per_goal[goal].append((i, s))

    print(f"{len(procs)} executor process(es), "
          f"{sum(len(v) for v in per_goal.values())} leg-attempt(s)\n")
    print("ESCALATION DECAY — escalations each time a leg was attempted,")
    print("and beneath it the same divided by subgoals actually completed.")
    print("a leg that compounds needs fewer per subgoal each time; a leg "
          "that does not\nis being piloted live, not compiled. '-' means "
          "the attempt finished nothing.\n")
    rows = sorted(per_goal.items(), key=lambda kv: -sum(s["esc"]
                                                        for _, s in kv[1]))
    for goal, attempts in rows[:16]:
        seq = " -> ".join(str(s["esc"]) for _, s in attempts)
        tot = sum(s["esc"] for _, s in attempts)
        won = sum(s["won"] for _, s in attempts)
        dis = sum(s["distilled"] for _, s in attempts)
        # RAW COUNT CONFLATES TWO OPPOSITE THINGS. A leg that escalates 13
        # times and finishes is not the same as one that escalates 13 times
        # and gets nowhere — and on this very dataset the S.S. Anne leg
        # reads "UP" on its last attempt, which is the attempt that walked
        # the underground path and boarded the ship. Normalise by subgoals
        # actually completed; that is the number that says whether the model
        # is being spent on progress or on the same wall.
        def rate(s):
            return s["esc"] / s["done"] if s["done"] else None
        rates = [rate(s) for _, s in attempts]
        seen = [r for r in rates if r is not None]
        trend = "—"
        if len(seen) >= 2:
            trend = ("DOWN" if seen[-1] < seen[0] * 0.8 else
                     "UP" if seen[-1] > seen[0] * 1.25 else "flat")
        per = ("  per-subgoal " + " ".join(
            f"{r:.0f}" if r is not None else "-" for r in rates))
        print(f"  {str(goal)[:44]:44s} {seq:>24s}  "
              f"[{tot} esc, {won} won, {dis} dist, {trend}]")
        print(f"  {'':44s} {per}")

    # ---- the two numbers item 30 turns on
    esc = sum(s["esc"] for v in per_goal.values() for _, s in v)
    won = sum(s["won"] for v in per_goal.values() for _, s in v)
    dis = sum(s["distilled"] for v in per_goal.values() for _, s in v)
    infer = sum(s["infer"] for v in per_goal.values() for _, s in v)
    calls = sum(s["calls"] for v in per_goal.values() for _, s in v)
    span = sum(p["span"] for p in procs)
    print(f"\nPILOT OR COMPILER")
    print(f"  escalations              {esc}")
    print(f"  succeeded                {won}"
          + (f"  ({100 * won // esc}%)" if esc else ""))
    print(f"  distilled back           {dis}"
          + (f"  ({100 * dis // won}% of successes)" if won else "")
          + "   <- the compiler half")
    print(f"  model calls              {calls}")
    print(f"  time waiting on model    {infer / 3600:.2f} h of "
          f"{span / 3600:.2f} h"
          + (f"  ({100 * infer / span:.0f}%)" if span else ""))
    if calls:
        print(f"  median-ish per call      {infer / calls:.1f} s")

    # ---- THE HEADLINE. Not raw escalations, which fall simply because a
    # leg gets resumed past once its condition already holds, but the COST
    # PER UNIT OF PROGRESS. If the harness compounds, this falls.
    done = sum(s["done"] for v in per_goal.values() for _, s in v)
    ordered = sorted(((i, s) for v in per_goal.values() for i, s in v),
                     key=lambda p: p[0])
    half = len(ordered) // 2
    def cost(chunk):
        e = sum(s["esc"] for _, s in chunk)
        d = sum(s["done"] for _, s in chunk)
        return (e / d) if d else None
    early, late = cost(ordered[:half]), cost(ordered[half:])
    print(f"\nDOES IT COMPOUND")
    print(f"  subgoals completed       {done}")
    if done:
        print(f"  escalations per subgoal  {esc / done:.2f}  overall")
    if early and late:
        verdict = ("FALLING" if late < early * 0.8 else
                   "RISING" if late > early * 1.25 else "FLAT")
        print(f"  first half / second half {early:.2f} -> {late:.2f}   "
              f"{verdict}")
        print(f"\n  Read it as cost per unit of progress. Raw escalation "
              f"counts fall on their\n  own as a leg starts being resumed "
              f"past — those attempts complete nothing,\n  which is why "
              f"the per-subgoal row shows '-' for them.")

    if args.subgoals:
        print("\nWHERE THE ESCALATIONS GO")
        sink = Counter()
        for v in per_goal.values():
            for _, s in v:
                sink.update(s["subgoals"])
        for name, n in sink.most_common(15):
            print(f"  {n:5d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
