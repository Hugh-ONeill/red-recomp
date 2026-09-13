"""A test of a rule must own the world the rule reads.

author.py reads run/explored.json from eight places, run/obs.json,
run/executor_log.jsonl and run/outline_leg, all by RELATIVE path — so a
test that stubs one reader still has seven doors open onto whatever the
live run happens to be doing. Six tests were written against run 16's
world and all six went red the moment run 17 archived it and started
fresh: "someone knows CUT now", "this run has walked several parts of
ROUTE_20", "ROUTE_23 is joined by walk: edges". None of those is a claim
about a RULE. They are claims about a playthrough, and a playthrough
moves (2026-09-13).

Every one of those reads is relative, which is the whole fix: one chdir
closes all of them at once.

    with pinned(explored={"ROUTE_20|1,1": {}}, obs={"map": {...}}):
        ...                      # run/ is a world you wrote

The lesson predates this file — tests/coming_out_is_not_standing_where_you
_already_were.py had to learn it alone when run 16 walked a door and broke
it — and this is where it stops being learned one test at a time.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path


@contextlib.contextmanager
def pinned(explored=None, visits=None, frontier=None, obs=None,
           journal=None, leg=None, **extra):
    """Run the block with run/ as a world you wrote, then put it back.

    explored/visits/frontier land in run/explored.json in the shape the
    readers expect; visits and frontier default to matching explored, so
    naming the walked regions alone gives a consistent world. Anything in
    `extra` is written as run/<name>.json.
    """
    explored = dict(explored or {})
    if visits is None:
        visits = {r: 1 for r in explored}
    if frontier is None:
        frontier = {r: [] for r in explored}
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        run = Path(d) / "run"
        run.mkdir(parents=True)
        (run / "explored.json").write_text(json.dumps({
            "explored": explored, "visits": visits, "frontier": frontier,
            "dead_ends": {}, "region_mark": {}, "sightings": {}}))
        (run / "obs.json").write_text(json.dumps(obs if obs is not None
                                                 else {}))
        (run / "executor_log.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in (journal or [])))
        if leg is not None:
            (run / "outline_leg").write_text(str(leg))
        for name, val in extra.items():
            (run / f"{name}.json").write_text(json.dumps(val))
        os.chdir(d)
        try:
            yield run
        finally:
            os.chdir(here)


def pin_world(**kw):
    """The same world, for a FLAT test that has no block to wrap.

    Most of these tests are a straight run of ck() calls at module level,
    and indenting one under a `with` to fix a world it never meant to read
    would bury the thing it is actually about. This chdirs for the rest of
    the process and cleans up at exit. Returns the run/ path.
    """
    import atexit
    cm = pinned(**kw)
    run = cm.__enter__()
    atexit.register(lambda: cm.__exit__(None, None, None))
    return run
