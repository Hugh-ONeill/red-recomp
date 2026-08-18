#!/usr/bin/env bash
# What the model is being TOLD, what it PROPOSED, and what happened —
# read back out of the journal the executor already writes.
#
#   ./show_esc.sh            last 5 escalation rounds
#   ./show_esc.sh 20         last 20
#   ./show_esc.sh -f         follow: print each new round as it lands
#   ./show_esc.sh -q         proposals and results only, no context text
#   ./show_esc.sh -p         THOUGHTS: the model's own plan per round, one
#                            line each, with a one-line result — what it is
#                            "thinking" (the plan echo, EXPLORE_DESIGN §6c)
#   ./show_esc.sh -p -f      ...and follow it live
#
# A READER, not a change to the executor. The chain spawns a fresh
# executor per attempt, so editing it mid-run lands on the next leg and
# the run changes behaviour halfway through; nothing here can do that.
cd "$(dirname "$0")"
python - "$@" <<'EOF'
import json
import os
import sys
import time

args = sys.argv[1:]
follow = "-f" in args
quiet = "-q" in args
thoughts = "-p" in args
nums = [a for a in args if a.lstrip("-").isdigit()]
last_n = int(nums[0]) if nums else 5
LOG = "run/executor_log.jsonl"

BOLD, DIM, OFF = "\033[1m", "\033[2m", "\033[0m"
CYAN, YELL, GREY = "\033[36m", "\033[33m", "\033[90m"


def wrap(text, indent):
    """Reflow to the terminal, honouring the writer's own line breaks."""
    width = max(40, (os.get_terminal_size().columns
                     if sys.stdout.isatty() else 100) - len(indent))
    out = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            if len(line) + len(word) + 1 > width:
                out.append(indent + line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(indent + line)
    return "\n".join(out)


def show(d):
    k = d.get("kind")
    sg, rnd, dt = d.get("subgoal"), d.get("round"), d.get("dt")
    if thoughts:
        # THE THOUGHT STREAM. One line of the model's own plan per round,
        # then what came of it in one line. Nothing else.
        if k == "escalate_start":
            print(f"\n{BOLD}{sg}{OFF}  {DIM}{(d.get('goal') or '')[:90]}{OFF}")
        elif k == "escalate_proposal":
            plan = d.get("plan") or "(no plan given)"
            ops = ", ".join(
                o.get("op", "?") + ("(" + ",".join(
                    f"{kk}={vv}" for kk, vv in o.items()
                    if kk not in ("op", "when")) + ")"
                    if len(o) > 1 else "")
                for o in (d.get("macro") or []) if isinstance(o, dict))
            print(f"{YELL}R{rnd}{OFF} {plan}")
            print(f"    {DIM}-> {ops}{OFF}")
        elif k == "escalate_feedback":
            tr = [t for t in (d.get("trace") or []) if not t.startswith("(")]
            first = (tr or d.get("trace") or ["?"])[0]
            print(f"    {GREY}{first[:150]}{OFF}  {DIM}[at {d.get('at')}]{OFF}")
        elif k == "escalate_end":
            print(f"    {BOLD}{'SOLVED' if d.get('success') else 'gave up'}{OFF}")
        return
    if k == "escalate_context" and not quiet:
        print(f"\n{GREY}{'-' * 70}{OFF}")
        print(f"{BOLD}{sg}{OFF}  {DIM}target {d.get('target')}  "
              f"t+{dt}{OFF}")
        print(f"{CYAN}WHAT IT IS TOLD:{OFF}")
        print(wrap(d.get("memory") or "", "   "))
    elif k == "escalate_note" and not quiet:
        print(f"{CYAN}WHY IT IS STUCK:{OFF}")
        print(wrap(d.get("stuck") or "", "   "))
    elif k == "escalate_proposal":
        print(f"\n{YELL}ROUND {rnd} — IT PROPOSES:{OFF}  {DIM}({sg}){OFF}"
              if quiet else f"{YELL}ROUND {rnd} — IT PROPOSES:{OFF}")
        if d.get("plan"):
            print(wrap(f"plan: {d['plan']}", "   "))
        for op in d.get("macro") or []:
            print(f"   {json.dumps(op)}")
    elif k == "escalate_feedback":
        print(f"{YELL}WHAT HAPPENED:{OFF} {DIM}(round {rnd}, "
              f"{d.get('spent')} spent, at {d.get('at')}){OFF}")
        for t in d.get("trace") or []:
            print(wrap(t, "   "))
        if d.get("inert"):
            print(f"   {DIM}inert: {', '.join(d['inert'])}{OFF}")
    elif k == "escalate_end":
        print(f"{BOLD}=== {sg}: "
              f"{'SOLVED' if d.get('success') else 'gave up'} ==={OFF}")


KINDS = {"escalate_context", "escalate_note", "escalate_proposal",
         "escalate_feedback", "escalate_end", "escalate_start"}


def parse(line):
    try:
        d = json.loads(line)
    except ValueError:
        return None
    return d if d.get("kind") in KINDS else None


if not os.path.exists(LOG):
    sys.exit("no run/executor_log.jsonl yet — nothing has escalated")

with open(LOG) as f:
    rows = [d for d in (parse(l) for l in f) if d]
    # count back last_n ROUNDS, not last_n records
    starts = [i for i, d in enumerate(rows)
              if d.get("kind") == "escalate_proposal"]
    if starts and len(starts) > last_n:
        rows = rows[starts[-last_n]:]
    for d in rows:
        show(d)
    if not follow:
        raise SystemExit
    print(f"\n{DIM}...following{OFF}")
    f.seek(0, os.SEEK_END)
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.4)
            continue
        d = parse(line)
        if d:
            show(d)
EOF
