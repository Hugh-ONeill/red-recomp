#!/usr/bin/env python3
"""Does THINKING help the leg author? Same goal, same world, N trials each way.

Authoring is the better place to ask than an escalation round: it happens a
handful of times per leg rather than twenty, and its output is
MACHINE-CHECKABLE — validate() returns the exact problems, so "did it work"
needs no judgement from me. The hard cases are already on disk (the Seafoam
crossing and the Silph rescue each burned five rounds, twice, on refusals
that were in front of the model the whole time).

Scored per trial: whether a valid plan came out, how many rounds it took,
the seconds and tokens spent, and which refusal classes recurred.

  tools/think_ab.py --goal "Travel through the Seafoam Islands ..." --trials 3
  tools/think_ab.py --goal-file goals.txt --trials 5 --think-only

RUN IT WHILE THE CHAIN IS PAUSED. It calls the same model on the same GPU;
alongside a live run it steals the card and slows every round.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import author as A                                            # noqa: E402
import brock_probe as B                                       # noqa: E402


def start_text() -> str:
    """The same sentence the chain hands the author: planner/state_text.py
    reading the live save. Computed once — every trial must face the same
    world or the arms are not comparable."""
    import subprocess
    try:
        return subprocess.run([sys.executable, str(ROOT / "planner/state_text.py")],
                              capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


START_TEXT = ""


def one_trial(goal: str, model: str, think: bool, rounds: int) -> dict:
    """One authoring run. Mirrors author.author()'s loop so the rounds and
    the refusals are the real ones, with think passed through."""
    fb, probs_seen, t0 = "", [], time.time()
    spent = {"gtok": 0, "ptok": 0}
    for rnd in range(1, rounds + 1):
        user = A.build_prompt(goal, START_TEXT)
        if fb:
            user += ("\n\nFIX THESE PROBLEMS from your last attempt. Change "
                     "nothing else about your plan:\n" + fb)
        reply = B.chat([{"role": "system", "content": A.SYS},
                        {"role": "user", "content": user}], model, think=think)
        for k in ("gtok", "ptok"):
            spent[k] += int((getattr(B, "LAST", None) or {}).get(k) or 0)
        import re as _re
        m = _re.search(r"\{.*\}", reply, _re.S)
        if not m:
            fb, _p = "your reply was not a JSON object", ["not-json"]
            probs_seen += _p
            continue
        try:
            plan = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            fb, _p = f"invalid JSON: {e}", ["bad-json"]
            probs_seen += _p
            continue
        A.normalize_items(plan)
        probs = (A.validate(plan) or A.witness_already_true_problems(plan)
                 or A.held_step_problems(plan))
        if not probs:
            return {"ok": True, "rounds": rnd, "secs": round(time.time() - t0, 1),
                    "probs": probs_seen, **spent}
        probs_seen += [p.split("—")[0].strip()[:70] for p in probs]
        fb = "\n".join(f"- {p}" for p in probs)
    return {"ok": False, "rounds": rounds, "secs": round(time.time() - t0, 1),
            "probs": probs_seen, **spent}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", action="append", default=[])
    ap.add_argument("--goal-file", type=Path)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--model", default="gemma4:31b-it-q4_K_M")
    ap.add_argument("--think-only", action="store_true")
    ap.add_argument("--plain-only", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "run/think_ab.jsonl")
    a = ap.parse_args()

    goals = list(a.goal)
    if a.goal_file:
        goals += [l.strip() for l in a.goal_file.read_text().splitlines() if l.strip()]
    if not goals:
        return int(bool(sys.stderr.write("give --goal or --goal-file\n")))

    global START_TEXT
    START_TEXT = start_text()
    print(f"start state: {START_TEXT[:80]}...")
    arms = ([] if a.plain_only else [True]) + ([] if a.think_only else [False])
    for goal in goals:
        print(f"\n=== {goal[:90]}")
        for think in arms:
            rows = [one_trial(goal, a.model, think, a.rounds)
                    for _ in range(a.trials)]
            with a.out.open("a") as fh:
                for r in rows:
                    fh.write(json.dumps({"goal": goal, "think": think, **r}) + "\n")
            won = [r for r in rows if r["ok"]]
            name = "THINK" if think else "plain"
            print(f"  {name}: {len(won)}/{len(rows)} valid"
                  + (f", rounds {statistics.mean(r['rounds'] for r in won):.1f}"
                     if won else "")
                  + f", {statistics.mean(r['secs'] for r in rows):.0f}s/trial"
                  + f", {statistics.mean(r['gtok'] for r in rows):.0f} gen tok")
            seen = {}
            for r in rows:
                for p in r["probs"]:
                    seen[p] = seen.get(p, 0) + 1
            for p, n in sorted(seen.items(), key=lambda kv: -kv[1])[:3]:
                print(f"      {n}x {p}")
    print(f"\nrows appended to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
