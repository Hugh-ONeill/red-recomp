"""Ask the model, in prose, how it thinks the run is going.

This is a LISTENING tool, not a control surface. Nothing it returns is fed
back into a plan, a predicate or a ledger — the whole point is to hear what
the model is reaching for in its own words, so we can find out whether the
thing it wants is something the harness has simply never made expressible.
The knows_move predicate came from noticing exactly that gap by hand (a bag
full of TMs, twelve losses, and no way to write "teach it something"); this
asks the question directly instead of waiting to notice.

It gets the SAME evidence the plan author gets — no more. Giving it extra
here would tell us about a model we do not run.

  python planner/introspect.py --model MODEL [--question "..."] [--out F]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import author
import brock_probe

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"

SYS = (
    "You are playing Pokemon Red through a harness that executes plans you "
    "write. You are talking to the people who BUILD that harness. They are "
    "not asking you for a plan and they will not run anything you say here. "
    "They want your honest read on how it is going. Speak plainly and "
    "concretely, in prose, and cite the evidence you were given. Say what "
    "you would do differently if you could, INCLUDING things the plan "
    "vocabulary gives you no way to ask for — those are the most useful "
    "answers, because they can be built."
)

DEFAULT_Q = (
    "Looking at where the run stands and what the journal shows:\n"
    "1. What is going WELL — what have you been getting right?\n"
    "2. What is going BADLY, and what do you think the actual cause is?\n"
    "3. Is there something you have wanted to do and could not express as a "
    "subgoal? Describe it in plain words, even if no predicate fits it.\n"
    "4. Is there anything you are being told that is confusing, misleading "
    "or contradictory?"
)


def build(question: str, goal: str) -> str:
    # the chain builds its start line by RUNNING state_text.py; do the same
    # so introspection reads exactly the sentence the author reads
    start = subprocess.run([sys.executable, str(ROOT / "planner/state_text.py")],
                           capture_output=True, text=True).stdout.strip()
    start = start or "a brand new game"
    parts = [f"THE GOAL YOU ARE PLAYING TOWARD: {goal}",
             f"WHERE YOU ARE RIGHT NOW: {start}"]
    outline = ROOT / "plans/outline.txt"
    if outline.exists():
        parts.append("THE PLAYTHROUGH OUTLINE YOU WROTE:\n"
                     + outline.read_text().strip())
    jt = author.journal_text(RUN / "executor_log.jsonl")
    if jt:
        parts.append("WHAT HAPPENED RECENTLY:\n" + jt)
    ot = author.observed_text(RUN / "explored.json")
    if ot:
        parts.append("WHAT YOU HAVE OBSERVED:\n" + ot)
    parts.append("THE PREDICATES YOU CAN CURRENTLY WRITE:\n"
                 + "\n".join(f"- {k}: {v}"
                             for k, v in author.PREDICATES.items()))
    body = author._fit("\n\n".join(parts))
    return body + "\n\n" + question


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--goal", default="")
    ap.add_argument("--question", default=DEFAULT_Q)
    ap.add_argument("--out")
    a = ap.parse_args()

    # same default the chain uses, same env var
    goal = a.goal or os.environ.get("RED_GOAL") or "Become the Champion"

    prompt = build(a.question, goal)
    print(f"[introspect] prompt {len(prompt)} chars", flush=True)
    reply = brock_probe.chat(
        [{"role": "system", "content": SYS},
         {"role": "user", "content": prompt}], a.model)
    print(reply)
    if a.out:
        Path(a.out).write_text(reply)


if __name__ == "__main__":
    main()
