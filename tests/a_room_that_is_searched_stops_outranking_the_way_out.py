#!/usr/bin/env python3
"""Explore counts only work it would actually do, and an area with none
left stops outranking everywhere else.

ROUTE_24 was the only region on the board with anything reachable left:
13 spots of unseen ground, an untaken east edge, the way to Bill and the
S.S. Ticket. It was picked ZERO times in nine visits while Cerulean's
Pokecenter and gym took three each (2026-09-14, user: "it should have
explored its way up to bills house simply by virtue of the fact that its
the only place to go with new area it hasnt seen").

Two things pinned it. The rank tuple puts _local above everything but the
band, and every Cerulean building is local because a numbered door from
the party's own part reaches it, while the way north is a SEAM and is
not. And those buildings could never stop looking unfinished, because
their untouched lists held the PC, the Center's nurse and the gym's own
leader -- three things explore decided on 2026-09-14 it will never press.
The Pokecenter's list was NURSE, SUPER_NERD, PC for ever.

So the picker now counts what explore would actually do, using the same
filter its own press list uses, and _local means "the area you are still
searching" rather than "the area you are in": once a room has no
reachable frontier, no untaken exit and nothing left explore would press,
it takes its place in the general field. A way out no walk reaches is
deliberately not counted, because walking there again cannot reach it.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
src = (ROOT / "planner" / "executor.py").read_text()

# ---- what counts as work left ------------------------------------------------
i = src.index("unpressed = [n for n in ledger.untouched_in(self, region)")
blk = src[i - 1500:i + 2600]
ck("the remote count drops what explore refuses to press",
   "if not self._not_for_explore_to_press(\n                             n, \"trainer\", region)]" in blk)
ck("...which is the same filter explore's own press list uses",
   src.count("_not_for_explore_to_press(") >= 4)

o = types.SimpleNamespace(_is_gym_leader=E.Executor._is_gym_leader)
held = types.MethodType(E.Executor._not_for_explore_to_press, o)
ck("a Center's PC and nurse stop counting as work left",
   held("PC", "trainer", "CERULEAN_POKECENTER|0,3")
   and held("CERULEANPOKECENTER_NURSE", "trainer", "CERULEAN_POKECENTER|0,3"))
ck("...and so does that gym's own leader",
   held("CERULEANGYM_MISTY", "trainer", "CERULEAN_GYM|0,1"))
ck("everyone else still counts",
   not held("CERULEANPOKECENTER_SUPER_NERD", "trainer", "CERULEAN_POKECENTER|0,3")
   and not held("CERULEANGYM_GYM_GUIDE", "trainer", "CERULEAN_GYM|0,1")
   and not held("CERULEANMART_CLERK", "trainer", "CERULEAN_MART|0,2")
   and not held("ITEM_ROUTE_24_10_5", "trainer", "ROUTE_24|4,4"))

# ---- and locality now means "still being searched" ---------------------------
j = src.index("_has_left = bool(left or unpressed or unseen)")
lblk = src[j - 300:j + 500]
ck("locality asks whether anything is left there", "_has_left = bool(left or unpressed or unseen)" in lblk)
ck("...and a way no walk reaches is not counted as something left",
   "_unr" not in lblk.split("_has_left =")[1].split("\n")[0])
ck("...and only a room still being searched keeps its place",
   "_local = 0 if ((_reg_b == _here_b or region in _rooms)\n                           and _has_left) else 1" in src)
ck("locality still ranks above the starvation term and distance",
   "r = (_pri, _stale, _local, _goal, _picks, len(path), _way_here," in src)

# the arithmetic of the decision
def local(same_place, left, unpressed, unseen):
    return 0 if (same_place and bool(left or unpressed or unseen)) else 1
ck("a room with people still to press stays local", local(True, [], ["CLERK"], 0) == 0)
ck("a room with ground still to see stays local", local(True, [], [], 4) == 0)
ck("a room with an untaken exit stays local", local(True, ["3,7"], [], 0) == 0)
ck("a room with none of the three joins the general field",
   local(True, [], [], 0) == 1)
ck("somewhere else is not local however much it holds",
   local(False, ["east"], ["ITEM"], 13) == 1)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
