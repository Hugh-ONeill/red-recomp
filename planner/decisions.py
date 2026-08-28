#!/usr/bin/env python3
"""Did it take a logical option, GIVEN WHAT IT WAS SHOWN?

The precondition for area-footprint mode (user, 2026-08-17): footprint
REMOVES information — a door is not known until the player has swept past
it — so if the run then fails, there are two explanations and no way to
separate them. Either the sweep never surfaced the thing, or the model had
it and did not act. That confound has to be closed before the change, not
after, and historically this is exactly where harness bugs have shaken out
([[feedback_illogical_means_harness]]: wrong FACTS are the model's;
illogical choices given what it was shown are ours).

So: a baseline. Given full information, how often does it take an option
the prompt actually offered?

NO MODEL CALLS. Every decision the run has ever made is already in the
journal — `escalate_context` carries the exact `memory` text the model was
shown, and the `escalate_proposal` after it carries the macro it wrote.
1,741 paired decisions and counting. This reads them.

WHAT IS BEING SCORED, precisely. Only the map-changing op, because that is
the decision the exits block is about and where the escalations go
(reach_cerulean_city 68, exit_mt_moon 44). The classes:

  offered-untried  it took an exit the text listed as UNTRIED. The prompt
                   says "prefer these"; it did.
  offered-taken    it took an exit the text listed as already taken. Not
                   wrong on its own — the text itself says retaking is
                   right when there is unopened ground beyond — so this is
                   reported, never counted as a miss.
  ungrounded       it proposed a door or direction the text never
                   mentioned. This is the interesting one: the model
                   inventing a coordinate rather than reading the list.
  nothing-offered  the text listed NO untried exit. Whatever the model did,
                   this decision was not winnable from what it was given —
                   a harness state, not a model failure. Counting these as
                   model misses is how you conclude the model is stupid.
  no-move          the macro changed no map (talked, pressed, waited).
                   Out of scope here.

  planner/decisions.py                 the live journal
  planner/decisions.py --misses        show the ungrounded ones in full
  planner/decisions.py LOG [LOG ...]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"

# "EXITS FROM HERE — UNTRIED (...): walk west out of here -> CERULEAN_CITY,
#  (12,9)->UNKNOWN. Already taken from here: (east) -> ROUTE_10|0,4 [...]"
UNTRIED_RE = re.compile(r"EXITS FROM HERE — UNTRIED[^:]*:(.*?)(?:Already taken"
                        r" from here:|$)", re.S)
TAKEN_RE = re.compile(r"Already taken from here:(.*?)(?:\n|$)", re.S)
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
        if ("never taken from here" in rest or "turned you back once" in rest
                or "never crossed" in rest):
            untried.add(key)
        else:
            taken.add(key)
    return untried, taken


def keys_in(text: str) -> set:
    """Every exit key a chunk of prompt names — coordinates and directions
    alike, in the two shapes the text uses for each."""
    out = set()
    for m in KEY_RE.finditer(text or ""):
        out.add(next(g for g in m.groups() if g))
    return out


def move_of(macro) -> str | None:
    """The macro's map-changing op, as an exit key. Only the FIRST one: the
    executor discards everything after it (one leg per macro), so anything
    later was never going to run."""
    if isinstance(macro, str):
        try:
            macro = ast.literal_eval(macro)
        except (ValueError, SyntaxError):
            return None
    for step in macro or []:
        if not isinstance(step, dict):
            continue
        op = step.get("op")
        if op == "cross" and step.get("dir"):
            return str(step["dir"])
        if op == "use_warp" and step.get("x") is not None:
            return f"{step.get('x')},{step.get('y')}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*", default=None)
    ap.add_argument("--era", choices=["all", "map-edges", "ledger"],
                    default="all",
                    help="restrict to one prompt era by its own marker line "
                         "(map-edges: 'THIS MAP HAS'; ledger: 'WHERE YOU "
                         "STAND:'). The journal has no clock, so the era is "
                         "read from the text the model was shown.")
    ap.add_argument("--new", action="store_true",
                    help="alias for --era ledger (the current era; was "
                         "--era map-edges when this flag was written)")
    ap.add_argument("--misses", action="store_true",
                    help="print the ungrounded proposals in full")
    args = ap.parse_args()
    paths = args.logs or [RUN / "executor_log.jsonl"]
    _era = "ledger" if args.new else args.era
    _ERA_MARK = {"map-edges": "THIS MAP HAS", "ledger": "WHERE YOU STAND:"}
    def _in_era(mem):
        return _era == "all" or _ERA_MARK[_era] in (mem or "")

    verdict = Counter()
    by_subgoal = Counter()
    shown = []
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
            if k == "escalate_context":
                ctx = d
                continue
            if k != "escalate_proposal" or ctx is None:
                continue
            mem = ctx.get("memory") or ""
            move = move_of(d.get("macro"))
            ctx = None
            # THE FIX IS ITS OWN TIMESTAMP. The journal carries no clock, so
            # "before and after the map-edges line" cannot be asked of it —
            # except that a context rendered after the fix CONTAINS that
            # line. Filter on the text itself.
            if not _in_era(mem):
                continue
            if move is None:
                verdict["no-move"] += 1
                continue
            # THE EXITS BLOCK IS NOT THE WHOLE PROMPT. A move to a
            # coordinate the exits list never names may still be grounded —
            # in the remote "ways you have NEVER taken" list, the route
            # line, the doorways line. Scoring only against the exits block
            # calls those inventions, and on this corpus it did: 271 of them
            # under subgoals like catch_water_pokemon, where going somewhere
            # else entirely is the sane move and the exits list is not where
            # it was named. Check the whole text before saying invented.
            anywhere = keys_in(mem)
            um = UNTRIED_RE.search(mem)
            untried = keys_in(um.group(1)) if um else set()
            tm = TAKEN_RE.search(mem)
            taken = keys_in(tm.group(1)) if tm else set()
            if not um and not tm and "WHERE YOU STAND:" in mem:
                untried, taken = ledger_exits(mem)
            if not untried:
                # NO NEW OPTION IS NOT NO OPTION. A mapped corridor
                # legitimately has nothing untried, and the text says so and
                # then says retaking a known door is still right when there
                # is unopened ground beyond it. Lumping these together made
                # 69% of every decision ever recorded look like the harness
                # offering nothing, when most of them are the ordinary state
                # of walked ground. Split by whether the move was one the
                # text actually named.
                if move in taken:
                    verdict["no-new/known"] += 1
                elif move in anywhere:
                    verdict["no-new/named-elsewhere"] += 1
                else:
                    verdict["invented"] += 1
                    by_subgoal[d.get("subgoal")] += 1
                    if len(shown) < 12:
                        shown.append((d.get("subgoal"), move,
                                      sorted(untried), sorted(taken)))
                continue
            if move in untried:
                verdict["offered-untried"] += 1
            elif move in taken:
                verdict["offered-taken"] += 1
            elif move in anywhere:
                verdict["named-elsewhere"] += 1
            else:
                verdict["invented"] += 1
                by_subgoal[d.get("subgoal")] += 1
                if len(shown) < 12:
                    shown.append((d.get("subgoal"), move,
                                  sorted(untried), sorted(taken)))

    total = sum(verdict.values())
    if not total:
        sys.exit("no paired decisions found")
    print(f"{total} recorded decisions with a map-changing op\n")
    print("GIVEN WHAT IT WAS SHOWN")
    order = ["offered-untried", "offered-taken", "named-elsewhere",
             "no-new/known", "no-new/named-elsewhere", "invented",
             "no-move"]
    for k in order:
        n = verdict.get(k, 0)
        print(f"  {k:16s} {n:6d}  {100 * n / total:5.1f}%")

    decid = verdict["offered-untried"] + verdict["offered-taken"] \
        + verdict["named-elsewhere"]
    if decid:
        good = verdict["offered-untried"] + verdict["offered-taken"]
        print(f"\n  Of the {decid} decisions where an untried exit WAS on "
              f"offer,\n  {good} ({100 * good / decid:.1f}%) named an exit "
              f"the text listed.")
    nn = verdict["no-new/known"] + verdict["no-new/named-elsewhere"]
    if nn:
        print(f"\n  {nn} decisions were made in a room with NOTHING untried "
              f"— the ordinary\n  state of walked ground. Of those, "
              f"{verdict['no-new/known']} "
              f"({100 * verdict['no-new/known'] / nn:.1f}%) re-took a door "
              f"the text\n  named and "
              f"{verdict['no-new/named-elsewhere']} went somewhere named "
              f"in another part of the prompt.")
    allg = (verdict["offered-untried"] + verdict["offered-taken"]
            + verdict["named-elsewhere"] + verdict["no-new/known"]
            + verdict["no-new/named-elsewhere"])
    allb = verdict["invented"]
    if allg + allb:
        print(f"\n  OVERALL, across every recorded decision with a move: "
              f"{100 * allg / (allg + allb):.1f}% named\n  something the "
              f"prompt had put in front of it.")

    if by_subgoal:
        print("\nUNGROUNDED BY SUBGOAL")
        for name, n in by_subgoal.most_common(10):
            print(f"  {n:5d}  {name}")
    if args.misses and shown:
        print("\nWHAT UNGROUNDED LOOKS LIKE")
        for sg, move, untried, taken in shown:
            print(f"  [{sg}] proposed {move!r}")
            print(f"      untried on offer: {untried}")
            print(f"      already taken   : {taken}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
