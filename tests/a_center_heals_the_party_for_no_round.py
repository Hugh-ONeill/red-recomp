#!/usr/bin/env python3
"""Standing in a Center with a party that is not party_healthy heals it,
for no round.

There is no reason not to: the counter's only offer is a free full heal,
and its one side effect (waking here after a blackout) is one the run has
never once wanted otherwise. So it is a deed, not a question, with the
same standing as the bag standing order beside it at the round boundary.
Watched on 2026-09-14: the run walked into the Mt Moon Center with Spike
at 0/40 hp, pressed nothing, and walked back out to fight on Route 4 with
two Pokemon (user: "basically theres no reason to not heal your pokemon
unless party=healthy").

Fires once per visit: a counter that refused is not asked again until the
party has left the room and come back.
"""
from __future__ import annotations
import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HURT = {"mode": "overworld",
        "map": {"id": "MT_MOON_POKECENTER", "region": "0,3",
                "objects": [{"name": "MTMOONPOKECENTER_NURSE", "kind": "person",
                             "reachable": True, "x": 3, "y": 1},
                            {"name": "PC", "reachable": True, "x": 13, "y": 1}]},
        "party": [{"species": "NIDORAN_M", "nickname": "Spike", "hp": 0, "max_hp": 40},
                  {"species": "CHARMANDER", "nickname": "Ignis", "hp": 33, "max_hp": 55},
                  {"species": "PIKACHU", "nickname": "Sparky", "hp": 33, "max_hp": 33}]}
WELL = copy.deepcopy(HURT)
for m in WELL["party"]:
    m["hp"] = m["max_hp"]

def fake(reply_ok=True, after=WELL):
    o = types.SimpleNamespace(sent=[], logged=[], printed=[])
    o._send_safe = lambda op, **kw: (o.sent.append((op, kw)) or
                                     {"result": {"ok": reply_ok,
                                                 "detail": "healed" if reply_ok else "nobody at the counter"}})
    o.settle = lambda: after
    o.log = lambda kind, **kw: o.logged.append((kind, kw))
    o._where = E.Executor._where
    o._nurse_here = E.Executor._nurse_here
    o._heal_here = types.MethodType(E.Executor._heal_here, o)
    return o

# ---- the deed ----------------------------------------------------------------
o = fake()
out = o._heal_here(HURT, {"id": "reach_cerulean_city"})
ck("a hurt party beside a nurse is healed, with one op and no round",
   o.sent == [("heal", {})], o.sent)
ck("...and the observation handed back is the healed one",
   E.pred_holds({"party_healthy": True}, out))
ck("...and the journal says who was hurt",
   any(k == "heal_done" and kw.get("ok") and "Spike 0/40" in kw.get("before", "")
       and "Ignis 33/55" in kw.get("before", "") for k, kw in o.logged), o.logged)

# ---- what does not fire ------------------------------------------------------
o = fake()
o._heal_here(WELL, {}); ck("a healthy party is left alone", o.sent == [])
o = fake()
o._heal_here({**HURT, "map": {**HURT["map"], "objects": [{"name": "PC", "reachable": True}]}}, {})
ck("no nurse in the room: nothing is sent", o.sent == [])
o = fake()
o._heal_here({**HURT, "mode": "dialog"}, {}); ck("not in the overworld: nothing is sent", o.sent == [])
o = fake()
o._heal_here({**HURT, "map": {**HURT["map"], "objects": [{"name": "MTMOONPOKECENTER_NURSE", "reachable": False}]}}, {})
ck("a nurse no walk reaches is not asked", o.sent == [])

# ---- once per visit ----------------------------------------------------------
o = fake(reply_ok=False, after=HURT)
o._heal_here(HURT, {}); o._heal_here(HURT, {})
ck("a counter that refused is asked once, not every round", len(o.sent) == 1, o.sent)
ck("...and the refusal is on record",
   any(k == "heal_done" and not kw.get("ok") and "nobody" in kw.get("detail", "") for k, kw in o.logged))
OUTSIDE = {**HURT, "map": {"id": "ROUTE_4", "region": "4,4", "objects": []}}
o._heal_here(OUTSIDE, {}); o._heal_here(HURT, {})
ck("...until the party has left the room and come back", len(o.sent) == 2, o.sent)

# ---- the party-healthy test is the plan predicate's own ----------------------
o = fake()
STATUS = copy.deepcopy(WELL); STATUS["party"][1]["status"] = "PSN"
o._heal_here(STATUS, {})
ck("full hp with a status is still not healthy: healed", o.sent == [("heal", {})])

# ---- it sits at the round boundary beside the bag standing order -------------
src = (ROOT / "planner" / "executor.py").read_text()
i_stow = src.index("start = self._stow_at_pc(start, sg) or start")
i_heal = src.index("start = self._heal_here(start, sg) or start")
i_teach = src.index("start = self._ask_teach(start, sg) or start")
ck("it runs at the round boundary, right after the bag standing order",
   i_stow < i_heal < i_teach)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
