#!/usr/bin/env python3
"""How often does a round re-propose something already tried, and how much
of that is the harness's own doing?

The companion question to decisions.py. That one asks whether the model
took an option it was SHOWN (it does: 99.5%). This one asks whether the
loop is a SEARCH — whether each round tries something new — and where it
is not, whether the repetition was invited by the harness: an exit listed
under "UNTRIED (prefer these)" and then refused; a refusal that yields on
the third go, so persistence pays; a "no" with no fact behind it.

NO MODEL CALLS. Reads the same escalate_context / escalate_proposal /
escalate_feedback triples decisions.py reads. Every op is canonicalised to
(op, target) — use_warp(3,7), cross(north), interact(NAME), buy(ITEM) — so
"the same thing" means the same op at the same target, not the same JSON.

WHAT IS COUNTED, per escalation (escalate_start .. escalate_end/success):

  fresh / repeat   the round's FIRST op has / has not been proposed earlier
                   in this escalation. Repeat gap = rounds since last time.
  verdict          what the harness said about that first op in the trace:
                   REFUSED (guard), FAILED (ran, no), no-effect, ok.
  after-refusal    the model re-proposed the exact op the harness had just
                   refused; what happened the second time. A "REFUSED then
                   ok" here is a refusal that yielded — the harness taught
                   persistence.
  contradiction    the refused exit was, in the SAME prompt, listed as
                   UNTRIED ("prefer these") or named by the KNOWN WAY line.
                   That is the harness offering with one hand and refusing
                   with the other; it is ours, not the model's.

Baseline over 31 journals, 2026-08-18: 43.8% of rounds repeat, 18.8%
repeat the previous round; 30% of all rounds are refused; 7,134 of the
refusals are the reversal guard; 15% of those and 38% of the failed-3x
refusals contradicted the prompt that produced them.

  planner/repeats.py                   the live journal
  planner/repeats.py LOG [LOG ...]     e.g. run/executor_log*.jsonl
  planner/repeats.py --by-subgoal      the sinks
  planner/repeats.py --new             only rounds whose prompt carries the
                                       map-edges line (post 2026-08-17)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"

UNTRIED_RE = re.compile(r"EXITS FROM HERE — UNTRIED[^:]*:(.*?)(?:Already taken"
                        r" from here:|$)", re.S)
KNOWN_RE = re.compile(r"THE KNOWN WAY TO [^\n]*?take (?:walk (\w+)|the door "
                      r"at \((\d+,\d+)\))")
KEY_RE = re.compile(r"\((\d+,\d+)\)|walk (north|south|east|west)\b"
                    r"|\((north|south|east|west)\)")


# THE LEDGER FORMAT (2026-08-18, EXPLORE_DESIGN §3). Since the ledger
# shipped the exits are numbered entries — " 3. door (3,7) -> X — taken 2x",
# " 5. walk north -> UNKNOWN — never taken from here" — and the old
# "EXITS FROM HERE — UNTRIED ...: / Already taken from here:" block is gone
# from prompts rendered under it. Both shapes are read, so the eras compare.
LEDGER_LINE = re.compile(r"^\s*\d+\.\s+(?:door \((\d+,\d+)\)|walk "
                         r"(north|south|east|west))\b(.*)$", re.M)


def ledger_exits(mem: str):
    """(untried, taken) exit keys as the ledger block lists them."""
    untried, taken = set(), set()
    for m in LEDGER_LINE.finditer(mem or ""):
        key = m.group(1) or m.group(2)
        rest = m.group(3) or ""
        if "never taken from here" in rest or "turned you back once" in rest:
            untried.add(key)
        else:
            taken.add(key)
    return untried, taken


def keys_in(text: str) -> set:
    return {next(g for g in m.groups() if g)
            for m in KEY_RE.finditer(text or "")}


def canon(step: dict) -> str:
    """(op, target) — what "the same thing" means here."""
    s = dict(step)
    op = s.pop("op", None)
    s.pop("when", None)
    if op in ("use_warp", "walk_to", "field_move"):
        return f"{op}({s.get('x')},{s.get('y')})"
    if op == "cross":
        return f"cross({s.get('dir')})"
    if op == "interact":
        return f"interact({s.get('name') or (s.get('x'), s.get('y'))})"
    if op == "menu":
        return f"menu({s.get('index')})"
    if op in ("buy", "sell", "use_item", "toss", "store_item",
              "retrieve_item"):
        return f"{op}({s.get('item')})"
    return f"{op}({json.dumps(s, sort_keys=True)})" if s else f"{op}()"


def exit_key(step: dict) -> str | None:
    if step.get("op") == "cross":
        return str(step.get("dir"))
    if step.get("op") == "use_warp":
        return f"{step.get('x')},{step.get('y')}"
    return None


def verdict_of(trace: list, cop: str) -> str:
    """The trace line for the round's first op, classified. REFUSED lines
    are `op(...): REFUSED` or bare `op: REFUSED` (the failed-3x guard prints
    no params), so match on the op name at the head of the line."""
    head = cop.split("(")[0]
    for t in trace or []:
        h = t.split(":", 1)[0]
        if head not in h:
            continue
        if "REFUSED" in t:
            return "REFUSED"
        if "FAILED" in t:
            return "FAILED"
        if "did not change" in t or "NO visible effect" in t:
            return "no-effect"
        if ": ok" in t or ": note" in t:
            return "ok"
    return "?"


def refusal_kind(t: str) -> str:
    if "just came in through" in t or "the door you came in by" in t:
        return "reversal"          # both wordings; the second is the
                                   # confirm-once form from 2026-08-18
    if "failed 3 times" in t:
        return "failed-3x"
    if "already been in" in t:
        return "revisit"
    if "provably failed" in t or "KNOWN DEAD END" in t:
        return "dead-end"
    if "fully searched" in t:
        return "searched"
    if "NOTHING changed" in t:
        return "inert-object"
    if "PROVEN uncrossable" in t:
        return "sealed-seam"
    if "cannot afford" in t or "one costs" in t:
        return "unaffordable"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*", default=None)
    ap.add_argument("--by-subgoal", action="store_true",
                    help="rank subgoals by refused and repeated rounds")
    ap.add_argument("--new", action="store_true",
                    help="only rounds whose prompt carries the map-edges "
                         "line (the marker decisions.py --new uses)")
    args = ap.parse_args()
    paths = args.logs or [RUN / "executor_log.jsonl"]

    rounds = 0
    first = Counter()
    gap = Counter()
    verdict = Counter()          # (fresh|repeat, verdict)
    after_refusal = Counter()    # verdict on an op re-proposed right after
                                 # the harness refused that same op
    refusals = Counter()         # kind -> n
    contra = Counter()           # kind -> n refused while offered UNTRIED
    contra_known = Counter()     # kind -> n refused while KNOWN WAY named it
    per_esc = []                 # (rounds, repeats)
    per_sg_ref = Counter()
    per_sg_rep = Counter()
    per_sg_rounds = Counter()
    esc = None
    ctx = None
    for p in paths:
        try:
            lines = Path(p).read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            k = d.get("kind")
            if k == "escalate_start":
                esc = {"sg": d.get("subgoal"), "seen": {}, "n": 0,
                       "rep": 0, "last_refused": None, "pending": None,
                       "cls": None, "skip": False}
                continue
            if esc is None:
                continue
            if k == "escalate_context":
                ctx = d.get("memory") or ""
                esc["skip"] = args.new and "THIS MAP HAS" not in ctx
                continue
            if k == "escalate_proposal":
                macro = [s for s in (d.get("macro") or [])
                         if isinstance(s, dict)]
                if not macro or esc["skip"]:
                    esc["pending"] = None
                    continue
                cops = [canon(s) for s in macro]
                esc["n"] += 1
                rounds += 1
                per_sg_rounds[esc["sg"]] += 1
                c0 = cops[0]
                if c0 in esc["seen"]:
                    first["repeat"] += 1
                    esc["rep"] += 1
                    per_sg_rep[esc["sg"]] += 1
                    gap[min(esc["n"] - esc["seen"][c0], 6)] += 1
                    esc["cls"] = "repeat"
                else:
                    first["fresh"] += 1
                    esc["cls"] = "fresh"
                for c in cops:
                    esc["seen"].setdefault(c, esc["n"])
                esc["seen"][c0] = esc["n"]
                esc["pending"] = (cops, macro)
                continue
            if k == "escalate_feedback":
                if not esc["pending"]:
                    continue
                cops, macro = esc["pending"]
                esc["pending"] = None
                trace = d.get("trace") or []
                v = verdict_of(trace, cops[0])
                verdict[(esc["cls"], v)] += 1
                if v == "REFUSED":
                    per_sg_ref[esc["sg"]] += 1
                if esc["last_refused"] == cops[0]:
                    after_refusal[v] += 1
                esc["last_refused"] = cops[0] if v == "REFUSED" else None
                # which refusals contradicted the prompt they answered
                mover = next((exit_key(s) for s in macro
                              if s.get("op") in ("cross", "use_warp")), None)
                um = UNTRIED_RE.search(ctx or "")
                untried = keys_in(um.group(1)) if um else set()
                if not um and "WHERE YOU STAND:" in (ctx or ""):
                    untried, _ = ledger_exits(ctx or "")
                km = KNOWN_RE.search(ctx or "")
                known = (km.group(1) or km.group(2)) if km else None
                for t in trace:
                    if "REFUSED" not in t:
                        continue
                    kind = refusal_kind(t)
                    refusals[kind] += 1
                    head = t.split(":", 1)[0]
                    if mover and head.startswith(("use_warp", "cross")):
                        if mover in untried:
                            contra[kind] += 1
                        if known and mover == known:
                            contra_known[kind] += 1
                continue
            if k in ("escalate_end", "escalate_success"):
                if esc["n"]:
                    per_esc.append((esc["n"], esc["rep"]))
                esc = None

    if not rounds:
        sys.exit("no escalation rounds found")
    rep = first["repeat"]
    print(f"{rounds} escalation rounds in {len(per_esc)} escalations "
          f"({len(paths)} journal(s))\n")
    print("IS EACH ROUND A NEW TRY?")
    print(f"  fresh first op   {first['fresh']:6d}  "
          f"{100 * first['fresh'] / rounds:5.1f}%")
    print(f"  repeat first op  {rep:6d}  {100 * rep / rounds:5.1f}%"
          f"   (immediate repeat of the previous round: "
          f"{gap[1]}, {100 * gap[1] / rounds:.1f}%)")
    print("  repeat gap (rounds since it was last proposed; 6 = 6+): "
          + ", ".join(f"{g}:{n}" for g, n in sorted(gap.items())))
    ns = [n for n, _ in per_esc]
    threeplus = sum(1 for n, r in per_esc if r >= 2)
    print(f"  rounds per escalation: median {statistics.median(ns):.0f}, "
          f"mean {statistics.mean(ns):.1f}; escalations with 2+ repeats: "
          f"{threeplus} ({100 * threeplus / len(per_esc):.0f}%)")

    ref = sum(n for (c, v), n in verdict.items() if v == "REFUSED")
    print("\nWHAT THE HARNESS SAID TO THE FIRST OP")
    for cls in ("fresh", "repeat"):
        row = {v: verdict.get((cls, v), 0)
               for v in ("ok", "no-effect", "FAILED", "REFUSED", "?")}
        print(f"  {cls:7s} " + "  ".join(f"{v} {n}" for v, n in row.items()))
    print(f"  refused rounds overall: {ref} ({100 * ref / rounds:.1f}% of "
          f"all rounds)")
    if after_refusal:
        tot = sum(after_refusal.values())
        print(f"\n  The model re-proposed the exact op it had just been "
              f"refused {tot} times.\n  Second time round: "
              + ", ".join(f"{v} {n}" for v, n in after_refusal.most_common())
              + f"\n  — {after_refusal.get('ok', 0)} of those refusals "
                f"YIELDED. A no that becomes a yes on the third go is a "
                f"lesson in persistence.")

    print("\nREFUSALS BY KIND, and how many contradicted the prompt that "
          "produced them\n  (the same text listed that exit under UNTRIED "
          "'prefer these' / named it as THE KNOWN WAY)")
    for kind, n in refusals.most_common():
        print(f"  {n:6d}  {kind:13s}  offered-untried {contra[kind]:5d} "
              f"({100 * contra[kind] / n:3.0f}%)   known-way "
              f"{contra_known[kind]:4d}")

    if args.by_subgoal:
        print("\nSINKS — subgoals by refused rounds")
        for sg, n in per_sg_ref.most_common(12):
            print(f"  {n:5d} refused / {per_sg_rep[sg]:5d} repeats / "
                  f"{per_sg_rounds[sg]:5d} rounds  {sg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
