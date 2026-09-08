#!/usr/bin/env python3
"""A walk hop that a regrown bush stops is cut and re-walked by go itself.

A cut bush regrows every time its map is re-entered, so a road walked with
the bush down is walled again on arrival. The door hop has cut the bush its
refusal blames since 08-26; the intra-map WALK hop stamped the leg and
returned first, so `go ROUTE_16` from Cerulean stopped at ROUTE_9|0,8 on the
(5,8) bush, named it in its own words, and did not cut (run 16, 2026-09-08;
user: "go should just route through the bush no?"). Same rule, same blame
test: only the bush the shim says stopped the walk, only with CUT in the
party, once per hop, before any stamp is written.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


ex = E.Executor.__new__(E.Executor)
DET = ("no path — the ground you have SEEN and can walk from here is 9 cell(s) and the closest it "
       "comes to 6,2 is 4,8. At the EDGE of that ground stand: CUT_TREE (a bush CUT clears) at (5,8) "
       "— that is what is beside the boundary, not a claim that any of it is what stops you")
CUTTER = {"party": [{"species": "GLOOM", "moves": [{"id": "ACID"}, {"id": "CUT"}]}]}
NOCUT = {"party": [{"species": "GLOOM", "moves": [{"id": "ACID"}]}]}
ck("the bush the refusal blames is read as (x,y)", ex._blamed_bush(DET, CUTTER) == (5, 8))
ck("no CUT in the party, no bush to cut", ex._blamed_bush(DET, NOCUT) is None)
ck("a bush the shim rules out is not the one",
   ex._blamed_bush("no path ... Also near that edge, though not what stopped you: CUT_TREE (a bush CUT clears) at (9,18)",
                   CUTTER) is None)
ck("no bush named, nothing", ex._blamed_bush("no path — a LEDGE at the edge of reachable ground", CUTTER) is None)

src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("def _walk_route(")
body = src[i:]
cut_at = body.find("_bx = self._blamed_bush(_wdet, o)")
stamp_at = body.find('_wrec["blocked_at"] = self._world_mark(o)')
ck("the walk hop asks which bush the refusal blamed", cut_at > 0)
ck("...before it stamps the hop as blocked", 0 < cut_at < stamp_at)
ck("...cuts it and re-sends the same walk", 'self._send_safe("field_move", move="CUT",\n                                              x=_bx[0], y=_bx[1])' in body
   and body.find('_wres = self._send_safe("walk_to", x=_ax, y=_ay)', cut_at) > cut_at)
ck("...and the journal says it was the walk hop's cut", 'hop="walk"' in body[cut_at:stamp_at])
sys.exit(1 if fails else 0)
