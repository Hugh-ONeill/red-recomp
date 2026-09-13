#!/usr/bin/env python3
"""Did the thinking buy anything? Join each trace to the round it paid for.

A thinking round costs about three times a normal one in play and seven and
a half times in the author, so the only question that matters is whether
the round it bought went anywhere — and until 2026-09-12 the trace was
discarded the moment its length was counted, so there was nothing to read
(user: "this can help us pin down whether/when the thinking is actually
helpful").

The trace is written by brock_probe.log_thinking into run/thinking.jsonl
BEFORE the round runs, so it cannot know its own outcome. This joins it
afterwards, on (subgoal, round), to what the journal recorded:

  new clean ops   the round's own progress_ops delta. progress_ops is a
                  RUNNING TOTAL and reading it raw says a stuck round added
                  eighteen (2026-09-12) — the delta is the round's work.
  broke the wall  did the world move within two rounds of this one. That
                  is the thing thinking is bought for: _stale_rounds
                  resetting, not an op landing.

Run 16's verdict WITHOUT traces, from think_on records alone: 1.16 new
clean ops on a thinking round against 0.36 on a normal one, 8% of thinking
rounds adding nothing against 23%. It works where deliberation is the
missing thing, and it did nothing at all on defeat_blaine, which spent
eleven of them re-arguing a false premise.

  think_meter.py                    this run
  think_meter.py --journal X --traces Y
  think_meter.py --full             print whole traces, not excerpts
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(path: Path):
    out = []
    if not path or not path.exists():
        return out
    for line in path.open():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def rounds_of(journal):
    """(subgoal, round) -> what that round did, from the journal alone."""
    seq = collections.defaultdict(list)
    for r in journal:
        if r.get("kind") == "escalate_feedback":
            seq[r.get("subgoal")].append(r)
    out, thought = {}, set()
    for r in journal:
        if r.get("kind") == "think_on":
            thought.add((r.get("subgoal"), r.get("round")))
    for sg, rows in seq.items():
        prev = 0
        for r in rows:
            po = r.get("progress_ops") or 0
            out[(sg, r.get("round"))] = {
                "new_ops": po - prev,          # the DELTA, not the total
                "inert": len(r.get("inert") or []),
                "at": r.get("at"),
                "thought": (sg, r.get("round")) in thought,
            }
            prev = po
    return out


def broke_the_wall(journal, sg, rnd, within=2):
    """Did _stale_rounds fall after this round? think_on carries the count,
    so a LOWER stale at a later round on the same leg means the world moved
    in between. None when nothing later says."""
    later = [r for r in journal if r.get("kind") == "think_on"
             and r.get("subgoal") == sg
             and (r.get("round") or 0) > (rnd or 0)]
    here = next((r.get("stale") for r in journal
                 if r.get("kind") == "think_on"
                 and r.get("subgoal") == sg and r.get("round") == rnd), None)
    if here is None or not later:
        return None
    nxt = min(later, key=lambda r: r.get("round") or 0)
    if (nxt.get("round") or 0) - (rnd or 0) > within:
        return None
    return (nxt.get("stale") or 0) < here


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", type=Path,
                    default=REPO / "run/executor_log.jsonl")
    ap.add_argument("--traces", type=Path,
                    default=REPO / "run/thinking.jsonl")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()

    journal = _read(a.journal)
    traces = _read(a.traces)
    by_round = rounds_of(journal)
    if not by_round:
        print(f"no rounds in {a.journal}")
        return 1

    th = [v for v in by_round.values() if v["thought"]]
    no = [v for v in by_round.values() if not v["thought"]]
    print(f"rounds: {len(by_round)}  of which thought: {len(th)}")
    for name, rows in (("normal", no), ("thinking", th)):
        if not rows:
            continue
        d = [r["new_ops"] for r in rows]
        print(f"  {name:9s} n={len(d):5d}  new clean ops/round "
              f"{statistics.mean(d):.2f}   added nothing "
              f"{100 * sum(1 for x in d if x <= 0) / len(d):.0f}%")

    # which LEGS it helped, and which it only made slower
    per = collections.Counter()
    for (sg, _), v in by_round.items():
        if v["thought"]:
            per[sg] += 1
    if per:
        print("\nthinking rounds per leg (many on one leg = a false premise,"
              " not a hard problem):")
        for sg, n in per.most_common(10):
            print(f"  {n:3d}  {sg}")

    if not traces:
        print(f"\nno traces in {a.traces} — they are written from "
              f"2026-09-12 on; the numbers above come from think_on alone")
        return 0

    print(f"\n{len(traces)} trace(s):")
    for t in traces:
        sg, rnd = t.get("subgoal"), t.get("round")
        got = by_round.get((sg, rnd)) or {}
        broke = broke_the_wall(journal, sg, rnd)
        verdict = ("BROKE IT" if broke else "no change" if broke is False
                   else "unknown")
        print(f"\n  [{t.get('where')}] {sg or t.get('goal')} r{rnd} "
              f"stale={t.get('stale')} {t.get('tot_s') or 0:.0f}s "
              f"{t.get('chars')} chars -> new ops {got.get('new_ops')}, "
              f"{verdict}")
        txt = str(t.get("thinking") or "")
        print("    " + (txt if a.full else
                        (txt[:600] + ("..." if len(txt) > 600 else "")))
              .replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
