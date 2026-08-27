#!/usr/bin/env python3
"""The Safari Zone's step clock ending a walk is not the ground refuting
the route.

When the Safari game's steps run out mid-walk the PA calls "Ding-dong!
Time's up!" and the park warps the party to the gate. The shim reported
that as bare "warped"; the executor read seven such landings as the
route being refuted and put the Secret House door and both North->West
warps into _bad_seam for good, after which `go` could not route to the
Secret House and the model called it "a broken chain" (leg 36,
2026-08-27, chain stopped).

The shim now names the clock at every site that reports a warp mid-op,
and the executor treats a walk the world cut as saying nothing about the
edge: not blocked, not voided, not refuted.
"""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

lua = (ROOT / "harness/shim.lua").read_text()
ck("the shim knows whether the Safari game is running",
   "local function safari_running(G)" in lua)
ck("...and names the clock when a warp ends it",
   "Ding-dong! Time's up!" in lua and "local function safari_ended_note" in lua)
ck("the step-walk op says it", 'tostring(ow.map and ow.map.id)\n        .. safari_ended_note(G, _sf0)' in lua)
ck("walk_to says it, whether it stepped or crossed",
   '"warped" .. _note' in lua and '"crossed mid-walk (door unknown)" .. _note' in lua)
ck("the explore loop says it", 'why = "warped to " .. tostring(ow.map and ow.map.id)\n        .. safari_ended_note(G, _sf0)' in lua)
ck("each site captures the flag at op start", lua.count("local _sf0 = safari_running(G)") >= 3)

ck("use_warp's own return names it too (it discards the walk's detail)",
   'return true, "warped" .. safari_ended_note(G, _sf0u)' in lua
   and "local _sf0u = safari_running(G)" in lua)

# read off the observations, whatever the op said
clock = E.Executor._safari_clock_cut
pre = {"safari": {"steps": 12, "balls": 30}, "map": {"id": "SAFARI_ZONE_NORTH"}}
gate = {"map": {"id": "SAFARI_ZONE_GATE"}}
ck("clock running before, gone after, standing at the gate: the clock cut it", clock(pre, gate))
ck("...not if the game is still running", not clock(pre, {"safari": {"steps": 3}, "map": {"id": "SAFARI_ZONE_GATE"}}))
ck("...not if it landed somewhere other than the gate",
   not clock(pre, {"map": {"id": "SAFARI_ZONE_WEST"}}))
ck("...not if no game was running to begin with", not clock({"map": {"id": "ROUTE_1"}}, gate))
ck("...and a missing observation is not a clock", not clock(None, None))

cut = E.Executor._walk_cut_by_the_world
ck("a walk the Safari clock ended was cut by the world",
   cut("warped — the SAFARI GAME ended on the way (PA: Ding-dong! Time's up!) and the park sent you out to the gate"))
ck("...so was one a battle box interrupted", cut("stopped because a box was up (kind=wild)"))
ck("a walk that simply did not arrive was not", not cut("warped to SAFARI_ZONE_GATE") and not cut("blocked by a fence"))

src = (ROOT / "planner/executor.py").read_text()
i = src.index("def _walk_route(")
body = src[i:]
guard = body.index('if "SAFARI GAME ended" in str(_last_det or "")')
ck("the guard also reads the observations", "or self._safari_clock_cut(pre, o)" in body[guard:guard + 200])
ck("...and names the clock itself when the op did not",
   "steps ran out" in body[guard:guard + 900])
ck("the clock guard comes before the edge is judged",
   guard < body.index("frm = self._where(pre)\n                rec = ")
   and guard < body.index("self._bad_seam.add("))
ck("...returns without blocking, voiding or refuting",
   "route_walk_lost_safari_clock" in body[guard:guard + 1200]
   and "return self._where(o)" in body[guard:guard + 1200])
ck("...and the verdict says the route still stands",
   "The route as recorded still stands" in body[guard:guard + 1200])
ck("the walked-edge branch uses the same predicate",
   "if self._walk_cut_by_the_world(_last_det):" in body)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
