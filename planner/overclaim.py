#!/usr/bin/env python3
"""How often does a harness ABSOLUTE precede a stall, and how often does
the run itself contradict one?

The harness states things as settled — "EVERYTHING YOU CAN REACH HERE IS
DONE", "FULLY WORKED", "proven uncrossable", "no walked way", "PROVEN:
what this goal needs is NOT here". Each is a claim about the world wider
than a single observation, and the standing worry (TODO 2026-08-19, "audit
every absolute") is that a wrong one becomes a wall the model quotes back
at itself until the leg dies. Nothing measured how often that happened.

This reads run/executor_log.jsonl and reports three things, each with its
own limits stated:

  1. ABSOLUTES EMITTED — the raw volume, per phrase, in the text the model
     was shown (escalate_context + escalate_feedback).

  2. QUOTED BACK, THEN STALLED — an escalation is the window from one
     escalate_start to the next. It STALLED if an escalate_end was logged
     inside it (the loop only logs end on the give-up path; a loop that met
     done_when returns without one). Of escalations where the model echoed
     an absolute in its own plan text, what share stalled — against the
     base rate for all escalations. A correlation is not proof the absolute
     caused the stall, but a quoted-back absolute in a stalled escalation
     is the shape the audit was looking for, and this counts it.

  3. THE HARNESS RETRACTING ITSELF — dead_op_cleared: an op it marked dead
     and then cleared because it worked. The one unambiguous self-
     contradiction the journal records.

  4. 'FINISHED HERE' AND THEN STALLED — escalations shown a "you are
     finished here" absolute (FULLY WORKED / EVERYTHING YOU CAN REACH /
     proven uncrossable) that then stalled. NOTE the earlier draft counted
     "shown the absolute, progressed anyway" as a contradiction; that was
     wrong — leaving by a listed exit is the verdict working. Only the
     stalls are reported, and only as correlation.

No model calls; nothing is written during play.
"""
from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"

# What the harness asserts, in the text it shows the model.
ABSOLUTES = [
    "EVERYTHING YOU CAN REACH HERE IS DONE",
    "FULLY WORKED",
    "nothing here is untried",
    "proven uncrossable",
    "no walked way",
    "no exit here is unopened",
    "PROVEN: what this goal needs is NOT",
    "PROVEN UNREACHABLE",
    "is a wall",
]
# The subset that says "you are finished in this spot" — the ones a later
# step of progress in the SAME spot flatly contradicts.
FINISHED_HERE = [
    "EVERYTHING YOU CAN REACH HERE IS DONE",
    "FULLY WORKED",
    "nothing here is untried",
    "proven uncrossable",
    "PROVEN UNREACHABLE",
    "no exit here is unopened",
]
# What the model quoting one back looks like in its own plan prose.
QUOTES = ["unreachable", "cannot reach", "fully worked", "dead end",
          "uncrossable", "no walked way", "nothing left", "already explored",
          "proven"]


def _load(path):
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*", default=None)
    ap.add_argument("--era", choices=["all", "map-edges", "ledger"],
                    default="all",
                    help="restrict to one prompt era by its marker line "
                         "(map-edges: 'THIS MAP HAS'; ledger: 'WHERE YOU "
                         "STAND:')")
    ap.add_argument("--new", action="store_true",
                    help="alias for --era ledger")
    args = ap.parse_args()
    paths = [Path(p) for p in args.logs] or [RUN / "executor_log.jsonl"]
    era = "ledger" if args.new else args.era
    MARK = {"map-edges": "THIS MAP HAS", "ledger": "WHERE YOU STAND:"}

    def in_era(mem):
        return era == "all" or MARK[era] in (mem or "")

    emitted = Counter()
    dead_cleared = 0
    dead_called = 0
    # escalations, as start->next-start windows
    n_esc = 0
    n_stalled = 0
    n_quote = 0
    n_quote_stalled = 0
    n_ctx_absolute = 0          # escalations whose context said "done here"
    n_ctx_absolute_progressed = 0
    # per-window state
    cur = None                  # {"stalled","quoted","ctx_absolute","in_era"}

    def close(w):
        nonlocal n_esc, n_stalled, n_quote, n_quote_stalled
        nonlocal n_ctx_absolute, n_ctx_absolute_progressed
        if w is None or not w["in_era"]:
            return
        n_esc += 1
        if w["stalled"]:
            n_stalled += 1
        if w["quoted"]:
            n_quote += 1
            if w["stalled"]:
                n_quote_stalled += 1
        if w["ctx_absolute"]:
            n_ctx_absolute += 1
            if not w["stalled"]:
                n_ctx_absolute_progressed += 1

    for path in paths:
        for r in _load(path):
            k = r.get("kind")
            if k == "dead_op_cleared":
                dead_cleared += 1
            elif k == "dead_end":
                dead_called += 1
            if k in ("escalate_context", "escalate_feedback"):
                blob = json.dumps(r)
                for a in ABSOLUTES:
                    if a in blob:
                        emitted[a] += 1
            if k == "escalate_start":
                close(cur)
                cur = {"stalled": False, "quoted": False,
                       "ctx_absolute": False, "in_era": era == "all"}
            elif cur is not None:
                if k == "escalate_end":
                    cur["stalled"] = True
                elif k == "escalate_context":
                    mem = r.get("memory") or ""
                    if in_era(mem):
                        cur["in_era"] = True
                    if any(a in mem for a in FINISHED_HERE):
                        cur["ctx_absolute"] = True
                elif k == "escalate_proposal":
                    pl = str(r.get("plan") or "").lower()
                    if any(q in pl for q in QUOTES):
                        cur["quoted"] = True
    close(cur)

    print(f"OVER-CLAIM METER — {n_esc} escalation(s)"
          + (f", era={era}" if era != "all" else "") + "\n")

    print("1. ABSOLUTES THE HARNESS EMITTED (in the text shown), by phrase:")
    for a, c in emitted.most_common():
        print(f"   {c:6d}  {a}")
    print()

    base = (n_stalled / n_esc * 100) if n_esc else 0.0
    qs = (n_quote_stalled / n_quote * 100) if n_quote else 0.0
    print("2. QUOTED BACK, THEN STALLED")
    print(f"   escalations that stalled (logged a give-up): "
          f"{n_stalled}/{n_esc} ({base:.1f}%)")
    print(f"   escalations where the model quoted an absolute in its plan: "
          f"{n_quote}")
    print(f"   ...of those, stalled: {n_quote_stalled}/{n_quote} ({qs:.1f}%)")
    lift = qs - base
    print(f"   quoting an absolute goes with a {lift:+.1f} pp change in the "
          f"stall rate.")
    print()

    fh_stall = n_ctx_absolute - n_ctx_absolute_progressed
    fh_rate = (fh_stall / n_ctx_absolute * 100) if n_ctx_absolute else 0.0
    print("3. THE HARNESS RETRACTING ITSELF")
    print(f"   dead ops it marked, then cleared because they worked: "
          f"{dead_cleared}")
    print()
    print("4. 'FINISHED HERE' AND THEN STALLED")
    print(f"   escalations shown a 'you are finished here' absolute: "
          f"{n_ctx_absolute}")
    print(f"   ...of those, stalled: {fh_stall} ({fh_rate:.1f}%)")
    print("   (An escalation that was shown the absolute and PROGRESSED is "
          "not counted against it — leaving by a listed exit is the verdict\n"
          "   working, not a contradiction. Only the stalls are the concern, "
          "and only as correlation.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
