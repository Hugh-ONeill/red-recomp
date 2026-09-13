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
import re
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


# ---------------------------------------------------------------- premises
# WHAT COUNTS AS A FALSE PREMISE, and what emphatically does not. The model's
# own Pokemon knowledge is not an invention — that it knows Blaine uses fire
# types, or that a LEAF_STONE evolves a GLOOM, is the whole reason it is
# playing and the pamphlet standard says so. What it must NOT reason from is
# a claim about THIS RUN'S WORLD that the page it was handed does not
# support: a map it is not on, a door at coordinates nothing listed, an item
# it is not carrying. Those are the ones no amount of deliberation repairs
# (user, 2026-09-13: "thinking is not going to magically insert more true
# facts, but im hoping that it reasons over the facts it has ... better").
#
# So the mechanical pass looks ONLY at world-state tokens, and it is
# deliberately conservative: a species or a move name is never counted, and
# anything the page mentions anywhere at all is taken as supported.
def _names(fname):
    try:
        return {l.strip() for l in (REPO / "planner" / fname).read_text()
                .splitlines() if l.strip()}
    except OSError:
        return set()


MAPS = _names("engine_maps.txt")
ITEMS = _names("engine_items.txt")
SPECIES = _names("engine_species.txt")
MOVES = _names("engine_moves.txt")


def page_for(journal, trace):
    """The escalation page this trace reasoned over: same subgoal, the
    context written for the same round. Without it nothing here can be
    said, and the meter says so rather than guessing."""
    sg, rnd = trace.get("subgoal"), trace.get("round")
    best = None
    for r in journal:
        if r.get("kind") != "escalate_context" or r.get("subgoal") != sg:
            continue
        # escalate_context carries no round; the one written closest
        # BEFORE this trace is the page it was handed
        if trace.get("t") and r.get("t") and r["t"] > trace["t"]:
            continue
        if best is None or (r.get("t") or 0) > (best.get("t") or 0):
            best = r
    return (best or {}).get("memory") or ""


def unsupported(trace_text: str, page: str):
    """World-state tokens the trace leans on that the page never mentions.

    Returns (maps, items, coords). A name in BOTH the species and the map
    lists (there is no such case today, but VICTORY_ROAD_1F-style ids are
    close enough to warrant it) is dropped rather than counted twice."""
    txt = str(trace_text or "")
    page = str(page or "")
    up = set(re.findall(r"\b[A-Z][A-Z_0-9]{2,}\b", txt))
    up -= SPECIES | MOVES          # game knowledge is not an invention
    maps = sorted(n for n in (up & MAPS) if n not in page)
    items = sorted(n for n in (up & ITEMS) if n not in page)
    # a door or a tile it claims is there. Only pairs written as the ops
    # write them, so prose numbers ("level 30") are never read as a cell.
    coords = sorted({c for c in re.findall(r"\((\d{1,3},\s?\d{1,3})\)", txt)
                     if c.replace(" ", "") not in page.replace(" ", "")})
    return maps, items, coords


JUDGE_SYS = (
    "You are auditing one round of a Pokemon Red bot. You are given THE "
    "PAGE the bot was handed and THE REASONING it then produced. Your job "
    "is NOT to say whether the reasoning is true. It is to say which of "
    "its load-bearing claims THE PAGE DOES NOT SUPPORT.\n"
    "A load-bearing claim is one the plan rests on — most often a claim "
    "about WHY: why something is blocked, why an action would open it, why "
    "a place is worth going to. Those are the ones to check.\n"
    "A claim is UNSUPPORTED when the page neither states it nor shows it, "
    "however confident or reasonable it sounds. A remembered fact about "
    "Pokemon Red, asserted as the REASON for the plan, is unsupported "
    "unless the page backs it — being sure is not evidence. Do not try to "
    "decide whether such a claim is correct; only whether the page said "
    "it. Ordinary description that matches the page is supported and is "
    "not worth listing.\n"
    "DO NOT LIST THE OBJECTIVE. What the run is trying to achieve — win "
    "the badge, reach the town, get the item — is the goal it was given, "
    "not a claim it made, and a plan that simply says what it is going for "
    "has invented nothing. List a claim only if the plan would be POINTLESS "
    "were that claim false.\n"
    "Reply with a JSON object and nothing else: "
    "{\"unsupported\":[\"<claim>\", ...],\"verdict\":\"reasoning\"} "
    "where verdict is \"reasoning\" when every load-bearing claim came "
    "off the page, and \"false premise\" when the plan rests on at least "
    "one claim the page did not give it."
)


def judge(page: str, trace_text: str, model: str):
    """Ask a model which claims the page does not support. Judgement, so it
    is opt-in and never runs as part of the plain read."""
    import brock_probe
    body = (f"THE PAGE:\n{page[:14000]}\n\n"
            f"THE REASONING:\n{str(trace_text)[:8000]}")
    try:
        reply = brock_probe.chat(
            [{"role": "system", "content": JUDGE_SYS},
             {"role": "user", "content": body}], model)
        m = re.search(r"\{.*\}", reply or "", re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:
        return {"error": str(e)[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", type=Path,
                    default=REPO / "run/executor_log.jsonl")
    ap.add_argument("--traces", type=Path,
                    default=REPO / "run/thinking.jsonl")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--judge", metavar="MODEL", default=None,
                    help="also ask a model which claims the page did not "
                         "support (one call per trace)")
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
        # DID IT REASON OVER THE PAGE, OR OVER SOMETHING IT MADE UP? The
        # whole bet on thinking is that it reasons BETTER over the facts it
        # has, not that it acquires more — so a trace leaning on a map, an
        # item or a tile the page never mentioned is not a thinking problem
        # at all, and no cap or budget fixes it. One of these is worth more
        # than any number of firings as a signal to stop paying.
        page = page_for(journal, t)
        if not page:
            print("    (no page found for this round — cannot say)")
        else:
            maps, items, coords = unsupported(txt, page)
            if maps or items or coords:
                bits = []
                if maps:
                    bits.append("maps " + ", ".join(maps[:4]))
                if items:
                    bits.append("items " + ", ".join(items[:4]))
                if coords:
                    bits.append("tiles " + ", ".join(coords[:4]))
                print("    FALSE PREMISE: reasoned from "
                      + "; ".join(bits)
                      + " — none of which its page mentioned. More "
                        "deliberation will not repair this one.")
            else:
                print("    premises: everything it names was on its page")
            if a.judge:
                v = judge(page, txt, a.judge)
                if v.get("error"):
                    print(f"    (judge failed: {v['error']})")
                else:
                    print(f"    judged: {v.get('verdict')}"
                          + ("".join("\n      unsupported: " + str(c)[:140]
                                     for c in (v.get("unsupported") or [])[:5])))
        print("    " + (txt if a.full else
                        (txt[:600] + ("..." if len(txt) > 600 else "")))
              .replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
