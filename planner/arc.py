#!/usr/bin/env python3
"""Did the harness get better or worse between one run and the next?

The question the rig could not answer (user, 2026-09-05: "its hard to say
whether things that helped at one point in the run hurt at other points
during the run, so its not noticed until the next run"). Every fix in this
repo is validated twice, and both are blind to it:

  - an offline test written the same day, which pins THAT incident;
  - watching the live run at the exact spot it was stuck.

The second is selection bias by construction — you only ever see a change
where you made it. So a fix that helps at leg 12 and hurts at leg 42 is
invisible until a later run reaches leg 42, by which time a hundred other
things have changed too. This is the meter for that.

NO MODEL CALLS, NO GAME. It streams archived journals and counts outcomes
the executor already writes down, then puts the runs side by side.

  planner/arc.py                      every run/executor_log*.jsonl, oldest first
  planner/arc.py A.jsonl B.jsonl      just these, in the order given
  planner/arc.py --phases             each run split into quarters by leg
  planner/arc.py --diff               what moved between the last two
  planner/arc.py --kinds              which row kinds each journal contains
  planner/arc.py --deep A B            also: is it still reasoning from the page?
  planner/arc.py --areas               where each run spent its rounds, by building and by stage
  planner/arc.py --legs                rounds per leg for the first legs of each run, side by side

WHERE IT GOT STUCK IS A PLACE, AND PLACES ARE COMPARABLE. The sticking
points of a run are named by the user from memory — "mt moon taking
*forever* this run, rock tunnel, the thirsty guards and celadons mart,
pokemon tower, silph co, safari a little, then seafoam, now this leg"
(2026-09-05) — and a memory of where it was slow is the thing a regression
hides behind. Every escalation page opens with WHERE YOU STAND, so the
rounds of a run can be bucketed by the building the party stood in when it
had to think. --areas prints that per run, folded to the building (Mt Moon's
three floors are one place; so are a mart's five), and puts the last two runs
side by side on a watch-list of the named spots plus whatever else is large.
A journal whose pages never carried the marker prints "--", not zeros.

A BUILDING HIDES A CORRIDOR. Rock Tunnel by itself read 45 -> 96 rounds
between the two Hall of Fame runs; the roads to it, Route 9 and Route 10,
read 91 -> 276 and 108 -> 241, and nobody names a road as a sticking point
(user, 2026-09-06: "the leadup to rocktunnel should be included in the runs
rocktunnel area, because a big issue this run was the inflation of that
specific part of it"). So every building also belongs to a STAGE — the
stretch of the game it is walked in — and --areas prints the stages beside
the buildings. And "a larger amount of time spent in the initial legs" is a
claim about LEGS, not places: --legs puts rounds per leg for the first legs
of each run side by side.

THE OUTCOME TABLE IS THE CHEAP HALF. Routing either lands or it does not,
and that is countable from row kinds alone. The question that actually
keeps a run honest is the other one (user, 2026-09-05: "im talking more
about explore and general reasoning from what its being told drifting
between runs"), and it needs the prompt and the reply side by side:

  explore    is a sweep still FINDING anything, or walking to look at
             ground that turns out to be nothing? Yield is cells that came
             newly on screen, straight out of the op's own answer.
  grounding  did the map-changing op it wrote name something the page had
             just listed? decisions.py answers that for one journal; --deep
             asks it of several and lines the answers up. `ungrounded` is
             the model inventing a coordinate instead of reading the list,
             and it is the number that moves when prose changes.
  repeat     did the round re-propose an op already tried this escalation?

--deep parses the journals properly rather than scanning them, so it is
slow: name the two runs you want to compare rather than turning it loose
on every journal on disk.

TWO TRAPS, BOTH LOAD-BEARING, BOTH REPORTED RATHER THAN HIDDEN:

1. A COUNTER THAT DID NOT EXIST YET READS AS ZERO. `route_hop_surfed` was
   born in August; a July journal scores 0 rides, which is not "it never
   rode", it is "nothing was writing that down". That is the very failure
   this tool exists to catch, reproduced inside the tool, so any metric
   whose numerator kind is ENTIRELY ABSENT from a journal prints "--" and
   not a number. Absence of the counter is never evidence about the run.

2. A RATE IS ALSO A STATEMENT ABOUT WHERE THE RUN WAS. Seafoam and Route
   20 are split by water, and a run that spends its routing budget there
   concentrates every water bug into a handful of hops; the same harness
   scores clean on a run that spent its budget in towns. So every table
   carries its denominators, and --phases shows where in the run the
   movement is. A number that moved is a QUESTION, never a verdict.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

KIND = re.compile(rb'"kind":\s*"([a-z_]+)"')
NEWCELLS = re.compile(rb"(\d+) cell\(s\) newly on screen")
TOREG = re.compile(rb'"to":\s*"([A-Z_0-9]+\|[0-9]+,[0-9]+)"')
STEP = re.compile(rb'"step":\s*"([a-z_]+)"')
TOMAP = re.compile(rb'"to":\s*"([A-Z_0-9]+)\|')
GOAL = re.compile(rb'"goal":\s*"((?:[^"\\]|\\.){0,120})')
AREA = re.compile(rb'WHERE YOU STAND:\s*([A-Z_0-9]+)\|')
_FLOOR = re.compile(r"_(?:B\d+F|\d+F|ROOF|ELEVATOR)$")


def building(map_id: str) -> str:
    """One place however many floors — the same fold ledger._building
    makes, plus the compounds that split by name rather than by floor."""
    m = str(map_id or "")
    if m.endswith("_POKECENTER"):
        return m                  # the Center by Mt Moon is not the cave
    for pre in ("SAFARI_ZONE", "SEAFOAM_ISLANDS", "POKEMON_MANSION",
                "VICTORY_ROAD", "ROCKET_HIDEOUT", "SILPH_CO", "MT_MOON",
                "ROCK_TUNNEL", "POKEMON_TOWER", "CELADON_MART"):
        if m == pre or m.startswith(pre + "_"):
            return pre
    return _FLOOR.sub("", m)


# STAGES: the stretch of the game a map is walked in. Every building falls
# in exactly one; the rest is ELSEWHERE. These are watch buckets, not
# geography — Route 22 is here as the League road because that is where
# its rounds pile up, though the rival is fought on it early.
STAGES = [
    ("OPENING",       ("PALLET_TOWN", "REDS_HOUSE", "BLUES_HOUSE", "OAKS_LAB",
                       "ROUTE_1", "VIRIDIAN_CITY", "VIRIDIAN_POKECENTER",
                       "VIRIDIAN_MART", "VIRIDIAN_SCHOOL_HOUSE",
                       "VIRIDIAN_NICKNAME_HOUSE", "ROUTE_2", "VIRIDIAN_FOREST",
                       "PEWTER_CITY", "PEWTER_POKECENTER", "PEWTER_MART",
                       "PEWTER_GYM", "PEWTER_NIDORAN_HOUSE",
                       "PEWTER_SPEECH_HOUSE", "MUSEUM")),
    ("MT_MOON",       ("ROUTE_3", "ROUTE_4", "MT_MOON", "MT_MOON_POKECENTER")),
    ("CERULEAN",      ("CERULEAN_CITY", "CERULEAN_POKECENTER", "CERULEAN_MART",
                       "CERULEAN_GYM", "CERULEAN_BADGE_HOUSE",
                       "CERULEAN_TRADE_HOUSE", "CERULEAN_TRASHED_HOUSE",
                       "BIKE_SHOP", "ROUTE_24", "ROUTE_25", "BILLS_HOUSE")),
    ("VERMILION",     ("ROUTE_6", "ROUTE_6_GATE", "VERMILION_CITY",
                       "VERMILION_POKECENTER", "VERMILION_MART", "VERMILION_GYM",
                       "VERMILION_PIDGEY_HOUSE", "VERMILION_TRADE_HOUSE",
                       "VERMILION_OLD_ROD_HOUSE", "VERMILION_DOCK", "SS_ANNE",
                       "POKEMON_FAN_CLUB", "ROUTE_11", "ROUTE_11_GATE",
                       "DIGLETTS_CAVE")),
    ("ROCK_TUNNEL",   ("ROUTE_9", "ROUTE_10", "ROCK_TUNNEL", "ROCK_TUNNEL_POKECENTER",
                       "POWER_PLANT")),
    ("LAVENDER",      ("LAVENDER_TOWN", "LAVENDER_POKECENTER", "LAVENDER_MART",
                       "LAVENDER_CUBONE_HOUSE", "NAME_RATERS_HOUSE",
                       "MR_FUJIS_HOUSE", "POKEMON_TOWER", "ROUTE_12",
                       "ROUTE_12_GATE")),
    ("SAFFRON_GATES", ("ROUTE_5", "ROUTE_5_GATE", "ROUTE_7", "ROUTE_7_GATE",
                       "ROUTE_8", "ROUTE_8_GATE", "UNDERGROUND_PATH_NORTH_SOUTH",
                       "UNDERGROUND_PATH_WEST_EAST", "UNDERGROUND_PATH_ROUTE_5",
                       "UNDERGROUND_PATH_ROUTE_6", "UNDERGROUND_PATH_ROUTE_7",
                       "UNDERGROUND_PATH_ROUTE_8", "DAYCARE")),
    ("CELADON",       ("CELADON_CITY", "CELADON_POKECENTER", "CELADON_MART",
                       "CELADON_GYM", "CELADON_MANSION", "CELADON_HOTEL",
                       "CELADON_DINER", "CELADON_CHIEF_HOUSE", "GAME_CORNER",
                       "GAME_CORNER_PRIZE_ROOM", "ROCKET_HIDEOUT", "ROUTE_16",
                       "ROUTE_16_GATE", "ROUTE_16_FLY_HOUSE", "ROUTE_17",
                       "ROUTE_18", "ROUTE_18_GATE")),
    ("SAFFRON",       ("SAFFRON_CITY", "SAFFRON_POKECENTER", "SAFFRON_MART",
                       "SAFFRON_GYM", "SILPH_CO", "FIGHTING_DOJO",
                       "MR_PSYCHICS_HOUSE", "COPYCATS_HOUSE", "SAFFRON_PIDGEY_HOUSE")),
    ("FUCHSIA",       ("ROUTE_13", "ROUTE_14", "ROUTE_15", "ROUTE_15_GATE",
                       "FUCHSIA_CITY", "FUCHSIA_POKECENTER", "FUCHSIA_MART",
                       "FUCHSIA_GYM", "FUCHSIA_GOOD_ROD_HOUSE",
                       "FUCHSIA_BILLS_GRANDPAS_HOUSE", "FUCHSIA_MEETING_ROOM",
                       "WARDENS_HOUSE", "SAFARI_ZONE")),
    ("CINNABAR",      ("ROUTE_19", "ROUTE_20", "ROUTE_21", "SEAFOAM_ISLANDS",
                       "CINNABAR_ISLAND", "CINNABAR_POKECENTER", "CINNABAR_MART",
                       "CINNABAR_GYM", "CINNABAR_LAB", "POKEMON_MANSION")),
    ("LEAGUE",        ("VIRIDIAN_GYM", "ROUTE_22", "ROUTE_22_GATE", "ROUTE_23",
                       "VICTORY_ROAD", "INDIGO_PLATEAU", "INDIGO_PLATEAU_LOBBY",
                       "LORELEIS_ROOM", "BRUNOS_ROOM", "AGATHAS_ROOM",
                       "LANCES_ROOM", "CHAMPIONS_ROOM", "HALL_OF_FAME")),
]
_STAGE_OF = {}
for _name, _members in STAGES:
    for _m in _members:
        _STAGE_OF[_m] = _name


def stage_of(bld: str) -> str:
    """The stage a building belongs to, by exact name and then by prefix
    (CELADON_MANSION_1F folds to CELADON_MANSION before it gets here;
    CINNABAR_LAB_FOSSIL_ROOM does not, so the prefix catches it)."""
    b = str(bld or "")
    if b in _STAGE_OF:
        return _STAGE_OF[b]
    for m, st in _STAGE_OF.items():
        if b.startswith(m + "_"):
            return st
    return "ELSEWHERE"


# the sticking points named from memory, as buildings; --areas always
# shows these beside the largest of whatever else the run did
WATCH = ["MT_MOON", "ROCK_TUNNEL", "ROUTE_5_GATE", "ROUTE_6_GATE",
         "ROUTE_7_GATE", "ROUTE_8_GATE", "CELADON_MART", "POKEMON_TOWER",
         "MR_FUJIS_HOUSE", "SILPH_CO", "SAFARI_ZONE", "SEAFOAM_ISLANDS",
         "POKEMON_MANSION", "VICTORY_ROAD"]

# name -> (numerator kinds, denominator kind, "per what")
METRICS = [
    ("rounds/esc",  ["escalate_proposal"],     "escalate_start",    "esc"),
    ("esc/solved",  ["escalate_start"],        "escalate_success",  "solved"),
    ("refused%",    ["dead_end_refused", "escalate_repeat_refused",
                     "inference_refused"],     "escalate_proposal", "round"),
    ("blocked/go",  ["walk_edge_blocked"],     "go_step",           "go"),
    ("lost/go",     ["route_abandoned", "route_walk_lost"],
                                               "go_step",           "go"),
    ("unreach/esc", ["target_unreachable"],    "escalate_start",    "esc"),
    ("rides/go",    ["route_hop_surfed", "route_ride"],
                                               "go_step",           "go"),
    ("dryexpl%",    ["explore_none"],          "explore_step",      "explore"),
    ("fights/rnd",  ["battle_start"],          "escalate_proposal", "round"),
]

# the explore half: what the looking actually returned
EXPLORE = [
    ("expl/rnd",    ["explore_step"],          "escalate_proposal", "round"),
    ("drysweep%",   ["sweep_dry"],             "sweep_result",      "sweep"),
    ("newarea/leg", ["new_region"],            "plan_start",        "leg"),
]


def scan(path: str, keep_lines: bool = False) -> dict:
    """One pass, regex only: an 89 MB journal is not worth json.loads.

    The per-row buffer is only built for --phases, because this box
    sheds background work under memory pressure and a meter that
    costs the run its RAM is not a meter."""
    counts: dict = {}
    maps: dict = {}
    areas: dict = {}         # building -> rounds the party stood in it
    located = 0              # rounds whose page said where it stood
    goals: list = []         # each plan_start's goal text, in order
    rounds_by_leg: list = [] # escalate_context rows between plan_starts
    regions: set = set()
    cells = [0]
    legs: list = []          # line index of each plan_start, for --phases
    per_line: list = []      # (kind, line_no) for the kinds we bucket
    n = 0
    with open(path, "rb") as fh:
        for n, raw in enumerate(fh):
            m = KIND.search(raw)
            if not m:
                continue
            k = m.group(1).decode()
            # an explore step that found nothing is its own outcome
            if k == "explore_step":
                s = STEP.search(raw)
                if s and s.group(1) == b"none":
                    counts["explore_none"] = counts.get("explore_none", 0) + 1
            counts[k] = counts.get(k, 0) + 1
            if k == "escalate_context":
                w = AREA.search(raw)
                if w:
                    located += 1
                    b = building(w.group(1).decode())
                    areas[b] = areas.get(b, 0) + 1
            if k == "plan_start":
                legs.append(n)
                g = GOAL.search(raw)
                goals.append(g.group(1).decode("utf-8", "replace") if g else "")
                rounds_by_leg.append(0)
            if k == "escalate_context" and rounds_by_leg:
                rounds_by_leg[-1] += 1
            elif k == "explored":
                t = TOMAP.search(raw)
                if t:
                    mp = t.group(1).decode()
                    maps[mp] = maps.get(mp, 0) + 1
                g = TOREG.search(raw)
                if g:
                    reg = g.group(1).decode()
                    if reg not in regions:
                        regions.add(reg)
                        counts["new_region"] = counts.get("new_region", 0) + 1
            # A SWEEP'S YIELD IS IN ITS OWN ANSWER, and the op says it in
            # words: "swept 11 step(s), 42 cell(s) newly on screen". A
            # sweep that returns nothing is the shape of explore walking
            # somewhere to look at ground that was not there.
            for c in NEWCELLS.finditer(raw):
                counts["sweep_result"] = counts.get("sweep_result", 0) + 1
                v = int(c.group(1))
                cells[0] += v
                if v == 0:
                    counts["sweep_dry"] = counts.get("sweep_dry", 0) + 1
            if keep_lines:
                per_line.append((k, n))
    return {"path": path, "counts": counts, "maps": maps, "legs": legs,
            "lines": n + 1, "per_line": per_line, "swept_cells": cells[0],
            "areas": areas, "located": located, "goals": goals,
            "rounds_by_leg": rounds_by_leg}


def stages_of(r: dict) -> dict:
    """Rounds per stage, summed from the buildings."""
    out: dict = {}
    for b, n in (r.get("areas") or {}).items():
        st = stage_of(b)
        out[st] = out.get(st, 0) + n
    return out


def areas_rows(r: dict, top: int = 12):
    """(building, rounds, share) for the places a run spent its rounds,
    largest first; None when the journal's pages never said where the
    party stood — absence of the marker is not a run that went nowhere."""
    if not r.get("located"):
        return None
    tot = r["located"]
    rows = sorted(r["areas"].items(), key=lambda kv: -kv[1])[:top]
    return [(b, n, n / tot) for b, n in rows]


def areas_table(runs: list, top: int = 12):
    for r in runs:
        rows = areas_rows(r, top)
        c = r["counts"]
        print(f"\n{label(r['path'])}: {c.get('escalate_context', 0)} rounds, "
              f"{r.get('located', 0)} of them placed")
        if rows is None:
            print("   -- these pages carry no WHERE YOU STAND line; nothing "
                  "was writing the place down, so this run has no opinion")
            continue
        marts = sum(n for b, n in r["areas"].items() if b.endswith("_MART"))
        for b, n, sh in rows:
            print(f"   {b:<28}{n:>6}  {sh * 100:5.1f}%")
        if marts:
            print(f"   {'(every _MART together)':<28}{marts:>6}  "
                  f"{marts / r['located'] * 100:5.1f}%")
        print("   -- by stage --")
        for st, n in sorted(stages_of(r).items(), key=lambda kv: -kv[1]):
            print(f"   {st:<28}{n:>6}  {n / r['located'] * 100:5.1f}%")


def areas_diff(a: dict, b: dict, top: int = 10):
    """The watch-list and the big movers, side by side. Rounds AND share:
    a longer run spends more rounds everywhere, and share alone hides a
    place that doubled while the run tripled."""
    if not (a.get("located") and b.get("located")):
        print("\n-- areas not comparable: one journal's pages never said "
              "where the party stood")
        return
    names = list(WATCH)
    for r in (a, b):
        for bld, _n, _s in areas_rows(r, top) or []:
            if bld not in names:
                names.append(bld)
    print(f"\n{label(a['path'])}  ->  {label(b['path'])}   (rounds, share) — by stage")
    sa_, sb_ = stages_of(a), stages_of(b)
    for st, _ in STAGES + [("ELSEWHERE", ())]:
        na, nb = sa_.get(st, 0), sb_.get(st, 0)
        if not na and not nb:
            continue
        fa, fb = na / a["located"], nb / b["located"]
        mark = "  "
        if max(na, nb) >= 20 and abs(fb - fa) >= 0.02:
            mark = "UP" if fb > fa else "DOWN"
        print(f"  {st:<26}{na:>5} {fa * 100:5.1f}%  ->  {nb:>5} {fb * 100:5.1f}%  {mark}")
    print(f"\n{label(a['path'])}  ->  {label(b['path'])}   (rounds, share) — by building")
    for bld in names:
        na, nb = a["areas"].get(bld, 0), b["areas"].get(bld, 0)
        if not na and not nb:
            continue
        sa, sb = na / a["located"], nb / b["located"]
        mark = "  "
        if max(na, nb) >= 20 and abs(sb - sa) >= 0.02:
            mark = "UP" if sb > sa else "DOWN"
        print(f"  {bld:<26}{na:>5} {sa * 100:5.1f}%  ->  {nb:>5} "
              f"{sb * 100:5.1f}%  {mark}")
    print("\nA place that took more of the run is a question, not a verdict: "
          "the run may have arrived there weaker, or the leg list may have "
          "sent it back. UP/DOWN marks a share that moved two points or more "
          "with at least twenty rounds behind it.")


# the deep half: the prompt and the reply, side by side
DEEP = [
    ("grounded%",   ["d_untried", "d_taken", "d_named"], "d_scored", "move"),
    ("ungrounded%", ["d_invented"],        "d_scored",   "move"),
    ("nooffer%",    ["d_nothing"],         "d_moves",    "move"),
    ("repeat%",     ["d_repeat"],          "d_rounds",   "round"),
]


def deep_scan(path: str) -> dict:
    """Pair each prompt with the reply it produced, and score the pairing.

    The classes are decisions.py's, imported rather than restated so the two
    cannot drift — that split is the bug this repo keeps paying for. A move
    is scored only when the page listed SOMETHING to move through: a prompt
    offering no exit at all is a harness state, and counting it against the
    model is how you conclude the model is stupid (decisions.py's own words).
    """
    import json as _json
    import decisions as D
    import repeats as R
    c: dict = {}
    mem = None
    seen: set = set()
    with open(path, "rb") as fh:
        for raw in fh:
            m = KIND.search(raw)
            if not m:
                continue
            k = m.group(1)
            if k not in (b"escalate_context", b"escalate_proposal",
                         b"escalate_start"):
                continue
            try:
                row = _json.loads(raw)
            except ValueError:
                continue
            if k == b"escalate_start":
                seen = set()
                continue
            if k == b"escalate_context":
                mem = row.get("memory") or ""
                continue
            macro = row.get("macro")
            c["d_rounds"] = c.get("d_rounds", 0) + 1
            # a round that re-proposes an op already tried this escalation
            first = next((st for st in (macro or [])
                          if isinstance(st, dict)), None)
            if first is not None:
                key = R.canon(first)
                if key in seen:
                    c["d_repeat"] = c.get("d_repeat", 0) + 1
                seen.add(key)
            if mem is None:
                continue
            mv = D.move_of(macro)
            if mv is None:
                continue                      # talked, pressed, waited
            c["d_moves"] = c.get("d_moves", 0) + 1
            untried, taken = D.ledger_exits(mem)
            if not untried and not taken:
                c["d_nothing"] = c.get("d_nothing", 0) + 1
                continue
            c["d_scored"] = c.get("d_scored", 0) + 1
            if mv in untried:
                c["d_untried"] = c.get("d_untried", 0) + 1
            elif mv in taken:
                c["d_taken"] = c.get("d_taken", 0) + 1
            elif mv in D.keys_in(mem):
                c["d_named"] = c.get("d_named", 0) + 1
            else:
                c["d_invented"] = c.get("d_invented", 0) + 1
    return c


def rate(counts: dict, nums: list, den: str):
    """None when the counter never existed; else (value, numerator, denom)."""
    if not any(k in counts for k in nums):
        return None                      # trap 1: absence is not evidence
    d = counts.get(den, 0)
    if not d:
        return None
    v = sum(counts.get(k, 0) for k in nums)
    return (v / d, v, d)


def fmt(r, pct: bool) -> str:
    if r is None:
        return "   --"
    v = r[0]
    return f"{v * 100:4.1f}%" if pct else f"{v:5.2f}"


def label(path: str) -> str:
    ts = os.path.getmtime(path)
    import datetime
    return (datetime.datetime.fromtimestamp(ts).strftime("%m-%d") + " "
            + os.path.basename(path).replace("executor_log", "")
              .replace(".pre-discovery", "").replace(".jsonl", "")
              .strip(".") or "live")


def group(runs: list, metrics: list, title: str, extra=None):
    print(f"\n{title}")
    head = f"{'run':<14}"
    for name, _, _, _ in metrics:
        head += f"{name:>13}"
    print(head + ("      swept" if extra == "cells" else ""))
    for r in runs:
        row = f"{label(r['path']):<14}"
        for name, nums, den, _ in metrics:
            row += f"{fmt(rate(r['counts'], nums, den), name.endswith('%')):>13}"
        if extra == "cells":
            n = r["counts"].get("sweep_result", 0)
            row += f"{(r['swept_cells'] // n if n else 0):>11}"
        print(row)


def table(runs: list, phases: bool):
    head = f"{'run':<14}{'legs':>5}{'esc':>6}{'rnds':>7}"
    for name, _, _, _ in METRICS:
        head += f"{name:>12}"
    print(head)
    for r in runs:
        c = r["counts"]
        row = (f"{label(r['path']):<14}{c.get('plan_start', 0):>5}"
               f"{c.get('escalate_start', 0):>6}"
               f"{c.get('escalate_proposal', 0):>7}")
        for name, nums, den, _ in METRICS:
            row += f"{fmt(rate(c, nums, den), name.endswith('%')):>12}"
        print(row)
        top = sorted(r["maps"].items(), key=lambda kv: -kv[1])[:4]
        if top:
            print(f"{'':<14}where it walked: "
                  + ", ".join(f"{m} {n}" for m, n in top))
        if phases:
            for qi, q in enumerate(quarters(r), 1):
                sub = f"  q{qi}"
                line = f"{sub:<14}{'':>5}{q.get('escalate_start', 0):>6}" \
                       f"{q.get('escalate_proposal', 0):>7}"
                for name, nums, den, _ in METRICS:
                    line += f"{fmt(rate(q, nums, den), name.endswith('%')):>12}"
                print(line)


def quarters(r: dict) -> list:
    """Counts per quarter of the run, measured in LEGS attempted — the axis
    the question is actually about ("it helped early and hurt late")."""
    legs = r["legs"]
    if len(legs) < 4:
        return []
    cuts = [legs[int(len(legs) * f / 4)] for f in (1, 2, 3)] + [1 << 62]
    out = [{} for _ in range(4)]
    for k, ln in r["per_line"]:
        q = next(i for i, c in enumerate(cuts) if ln < c)
        out[q][k] = out[q].get(k, 0) + 1
    return out


def legs_table(runs: list, n: int = 15):
    """Rounds per leg for the first n legs of each run, side by side.

    Legs are matched by INDEX, not by name — two outlines authored by the
    model differ — so each run's goal text is printed with its count. The
    axis the question is about ("a larger amount of time spent in the
    initial legs") is position in the run, and this is that axis."""
    if not runs:
        return
    width = max(len(label(r["path"])) for r in runs)
    print("\nROUNDS PER LEG, the first %d legs of each run (a leg re-authored "
          "mid-campaign counts its rounds under the same index)" % n)
    for r in runs:
        rb = r.get("rounds_by_leg") or []
        gs = r.get("goals") or []
        tot = sum(rb)
        print(f"\n{label(r['path'])}: {len(rb)} plan starts, {tot} rounds"
              + (f", first {n} legs = {sum(rb[:n])} rounds "
                 f"({sum(rb[:n]) / tot * 100:.0f}%)" if tot else ""))
        for i in range(min(n, len(rb))):
            print(f"   leg {i + 1:>2} {rb[i]:>5}  {gs[i][:60] if i < len(gs) else ''}")
    if len(runs) >= 2:
        a, b = runs[-2], runs[-1]
        ra, rb = a.get("rounds_by_leg") or [], b.get("rounds_by_leg") or []
        print(f"\n{label(a['path'])}  ->  {label(b['path'])}   rounds in the first {n} plan starts: "
              f"{sum(ra[:n])} -> {sum(rb[:n])}")
    print("\nA plan start is an attempt or a re-authoring, not an outline leg: a leg that "
          "took four attempts is four starts. Read the goal texts to line them up.")


def diff(a: dict, b: dict):
    print(f"\n{label(a['path'])}  ->  {label(b['path'])}")
    for name, nums, den, per in METRICS:
        ra, rb = rate(a["counts"], nums, den), rate(b["counts"], nums, den)
        if ra is None or rb is None:
            print(f"  {name:<12} -- not comparable: the counter is absent "
                  f"from one of them")
            continue
        # a denominator too small to argue from is said so, not rounded off
        thin = min(ra[2], rb[2]) < 30
        d = rb[0] - ra[0]
        pct = name.endswith("%")
        arrow = "  " if abs(d) < (0.02 if pct else 0.15) else (
            "UP" if d > 0 else "DOWN")
        print(f"  {name:<12}{fmt(ra, pct)} -> {fmt(rb, pct)}  {arrow:<4}"
              f"  ({ra[1]}/{ra[2]} -> {rb[1]}/{rb[2]})"
              + ("   [thin: too few to argue from]" if thin else ""))
    print("\nA number that moved is a question. Check `where it walked` "
          "above: a run that spent its budget in a water-split cave scores "
          "worse on routing with an identical harness.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--phases", action="store_true",
                    help="split each run into quarters by leg")
    ap.add_argument("--diff", action="store_true",
                    help="what moved between the last two runs")
    ap.add_argument("--kinds", action="store_true",
                    help="which row kinds each journal contains")
    ap.add_argument("--deep", action="store_true",
                    help="also score prompt-against-reply (slow: name the "
                         "journals you want)")
    ap.add_argument("--min-legs", type=int, default=3,
                    help="skip journals with fewer legs than this")
    ap.add_argument("--areas", action="store_true",
                    help="where each run spent its rounds, by building and "
                         "by stage; with two or more runs, the last two side by side")
    ap.add_argument("--legs", type=int, nargs="?", const=15, default=None,
                    help="rounds per leg for the first N legs of each run (default 15)")
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob("run/executor_log*.jsonl"),
                            key=os.path.getmtime)
    runs = []
    for p in logs:
        if not Path(p).exists():
            continue
        r = scan(p, keep_lines=a.phases)
        if r["counts"].get("plan_start", 0) < a.min_legs:
            continue
        runs.append(r)
    if not runs:
        sys.exit("no journals with enough legs to compare")
    if a.kinds:
        for r in runs:
            print(f"\n{label(r['path'])}: "
                  + ", ".join(sorted(r["counts"])))
        return
    if a.areas:
        areas_table(runs)
        if len(runs) >= 2:
            areas_diff(runs[-2], runs[-1])
        return
    if a.legs:
        legs_table(runs, a.legs)
        return
    table(runs, a.phases)
    group(runs, EXPLORE, "EXPLORE — is the looking still finding anything?",
          extra="cells")
    if a.deep:
        for r in runs:
            r["counts"].update(deep_scan(r["path"]))
        group(runs, DEEP,
              "GROUNDING — did the op it wrote name what the page listed?")
        print("\n'ungrounded' is the model writing a coordinate the page "
              "never named. 'nooffer' is the page listing no exit at all, "
              "which is ours, not its.")
    if a.diff and len(runs) >= 2:
        diff(runs[-2], runs[-1])
        if a.deep:
            for name, nums, den, _ in DEEP:
                ra = rate(runs[-2]["counts"], nums, den)
                rb = rate(runs[-1]["counts"], nums, den)
                if ra is None or rb is None:
                    print(f"  {name:<12} -- not comparable")
                    continue
                print(f"  {name:<12}{fmt(ra, True)} -> {fmt(rb, True)}"
                      f"        ({ra[1]}/{ra[2]} -> {rb[1]}/{rb[2]})")


if __name__ == "__main__":
    main()
