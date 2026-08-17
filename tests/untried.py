#!/usr/bin/env python3
"""The two definitions of UNTRIED must agree.

There are two, and they are read by different halves of the harness:

  _frontier_left(region)  works from the persisted frontier. The floor
                          note, the escort and the elsewhere list read it.
  _untried_exits(obs)     works from the live observation. The refusal
                          text, the free round and the stuck note read it.

They cannot be identical — one knows reachability and the other knows the
ledger — but every RULE they share must produce the same answer, and three
times in one day it did not:

  * six copies of "frontier minus walked", two of which had forgotten
    `_no_cross`, so a proven wall was advertised as an unopened road;
  * `_taken_here` widened coordinates to map scope in one and not the
    other, so a door walked from the far side of a split map read as
    untried from this side;
  * shut-door reopening lived only in `_untried_exits`, so a door that
    turned you back was permanently taken by the definition the escort
    reads — and MT_MOON_1F reported "nothing untried" across 81 arrivals
    with three doorways never stood at.

Each cost hours and one of them cost a mountain. The rule that came out of
it: WHEN A CONCEPT HAS TWO IMPLEMENTATIONS, ONE OF THEM IS WRONG, AND IT
IS THE ONE YOU DID NOT JUST EDIT. This makes the next divergence fail
loudly instead of quietly.

No game, no model, no ledger on disk — synthetic worlds only, so it runs
in a second and cannot be flaky.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

MAP = "TESTMAP"
HERE = f"{MAP}|0,0"
OTHER = f"{MAP}|9,9"          # another region of the SAME map


def world(flags=1):
    return {"badges": [], "flags": ["f"] * flags, "bag": {}}


def make(explored=None, frontier=None, no_cross=None, no_cross_at=None,
         exit_tries=None, mark=None):
    ex = object.__new__(E.Executor)
    ex.explored = explored or {}
    ex.frontier = frontier or {}
    ex._no_cross = {r: set(v) for r, v in (no_cross or {}).items()}
    ex._no_cross_at = no_cross_at or {}
    ex._exit_tries = exit_tries or {}
    ex.visits = {HERE: 1}
    ex._mark_now = mark or E.Executor._world_mark(world())
    return ex


def obs_for(ex, warps, conns=None, mark_flags=1):
    """An observation whose warps are all REACHABLE, so the one thing the
    two definitions legitimately disagree about is held constant."""
    return {"map": {"id": MAP, "region": "0,0",
                    "warps": [{"x": int(k.split(",")[0]),
                               "y": int(k.split(",")[1]),
                               "dest": "SOMEWHERE", "reachable": True}
                              for k in warps],
                    "connections": {d: "SOMEWHERE" for d in (conns or [])}},
            "player": {"x": 0, "y": 0}, **world(mark_flags)}


def keys_of(listing):
    """_untried_exits returns prose; pull the exit keys back out."""
    out = set()
    for s in listing:
        s = str(s)
        if s.startswith("("):
            out.add(s[1:s.index(")")])
        elif s.startswith("walk "):
            out.add(s.split()[1])
    return out


CASES = []


def case(name):
    def wrap(fn):
        CASES.append((name, fn))
        return fn
    return wrap


@case("a door nobody has opened is untried in both")
def _():
    ex = make(frontier={HERE: ["1,1"]})
    return ex, obs_for(ex, ["1,1"]), {"1,1"}


@case("a door walked from ANOTHER region of the same map is taken in both")
def _():
    ex = make(explored={OTHER: {"1,1": {"to": "ELSEWHERE|0,0", "n": 1}}},
              frontier={HERE: ["1,1"]})
    return ex, obs_for(ex, ["1,1"]), set()


@case("a shut door stays out while the world has not moved")
def _():
    m = E.Executor._world_mark(world(1))
    ex = make(explored={HERE: {"1,1": {"to": HERE, "shut": True,
                                       "shut_at": m, "n": 1}}},
              frontier={HERE: ["1,1"]}, mark=m)
    return ex, obs_for(ex, ["1,1"], mark_flags=1), set()


@case("a shut door comes back once the world has moved")
def _():
    old = E.Executor._world_mark(world(1))
    now = E.Executor._world_mark(world(2))
    ex = make(explored={HERE: {"1,1": {"to": HERE, "shut": True,
                                       "shut_at": old, "n": 1}}},
              frontier={HERE: ["1,1"]}, mark=now)
    return ex, obs_for(ex, ["1,1"], mark_flags=2), {"1,1"}


@case("a seam proven uncrossable stays out while the world has not moved")
def _():
    m = E.Executor._world_mark(world(1))
    ex = make(frontier={HERE: ["north"]}, no_cross={HERE: {"north"}},
              no_cross_at={HERE: {"north": m}}, mark=m)
    return ex, obs_for(ex, [], ["north"], mark_flags=1), set()


@case("a seam proof expires when the world moves")
def _():
    old = E.Executor._world_mark(world(1))
    now = E.Executor._world_mark(world(2))
    ex = make(frontier={HERE: ["north"]}, no_cross={HERE: {"north"}},
              no_cross_at={HERE: {"north": old}}, mark=now)
    return ex, obs_for(ex, [], ["north"], mark_flags=2), {"north"}


@case("a door reached for twice and never got through is not untried")
def _():
    m = E.Executor._world_mark(world(1))
    ex = make(frontier={HERE: ["1,1"]},
              exit_tries={HERE: {"1,1": {"n": 2, "at": m}}}, mark=m)
    return ex, obs_for(ex, ["1,1"], mark_flags=1), set()


@case("...but ONE failed reach could be a wanderer, so it stays untried")
def _():
    m = E.Executor._world_mark(world(1))
    ex = make(frontier={HERE: ["1,1"]},
              exit_tries={HERE: {"1,1": {"n": 1, "at": m}}}, mark=m)
    return ex, obs_for(ex, ["1,1"], mark_flags=1), {"1,1"}


def main():
    fails = []
    for name, fn in CASES:
        ex, obs, want = fn()
        a = set(ex._frontier_left(HERE))
        b = keys_of(ex._untried_exits(obs))
        ok = (a == want) and (b == want)
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          want {sorted(want)}")
            print(f"          _frontier_left  -> {sorted(a)}"
                  + ("" if a == want else "   <-- disagrees"))
            print(f"          _untried_exits  -> {sorted(b)}"
                  + ("" if b == want else "   <-- disagrees"))
            fails.append(name)
    print(f"\n{'-' * 60}")
    if fails:
        print(f"THE TWO DEFINITIONS OF UNTRIED DISAGREE: {len(fails)} case(s)")
        return 1
    print(f"both definitions agree on all {len(CASES)} rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
