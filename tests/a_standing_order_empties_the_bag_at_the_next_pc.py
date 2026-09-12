#!/usr/bin/env python3
"""The bag is decided where it hurts and emptied where there is a PC.

Run 16's numbers, off its own journal: 504 escalation pages stood with the
bag at 20 of 20 kinds, and FOURTEEN of those were in a room with a PC. The
rest were Seafoam B3F, Silph 7F, the Mansion and Route 20 — where the only
op that frees a slot is the one that destroys the thing. Meanwhile the run
stood in a Pokemon Center on 115 pages with nothing pressing, and stored
ONE item all run, never a key item, while five spent ones (CARD_KEY,
LIFT_KEY, SECRET_KEY, SILPH_SCOPE, S_S_TICKET) rode into the Elite Four
with six Full Restores and no Revives.

It was never that it did not know. The sentence saying a Center's PC takes
key items and hands them back was on 752 pages of that run. The pressure
and the remedy were in different rooms, so a correct round-by-round choice
was made 504 times and the bag never emptied.

So: {"op":"store_later"} takes the DECISION in the room where it is being
thought about, and the harness carries out the DEED in the room where it is
possible, for no round. What goes on the list is never ours.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                       # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))


def obs(pc=False, reachable=True, bag=None, mode="overworld"):
    objs = []
    if pc:
        objs.append({"x": 13, "y": 4, "kind": "fixture", "name": "PC",
                     "reachable": reachable})
    return {"mode": mode, "player": {"x": 10, "y": 5},
            "party": [{"species": "CHARIZARD", "level": 61}],
            "bag": dict(bag if bag is not None
                        else {"SILPH_SCOPE": 1, "S_S_TICKET": 1,
                              "FULL_RESTORE": 6}),
            "key_items": ["SILPH_SCOPE", "S_S_TICKET"],
            "map": {"id": "SEAFOAM_ISLANDS_B3F", "region": "10,5",
                    "warps": [], "connections": {}, "objects": objs}}


def fresh():
    ex = E.Executor.__new__(E.Executor)
    ex._stow = []
    ex.sent = []
    ex.log = lambda *a, **k: None
    def _send(op, **kw):
        ex.sent.append((op, kw))
        it = kw.get("item")
        ok = it in ex._bag_now
        if ok:
            ex._bag_now.pop(it, None)
        return {"result": {"ok": ok,
                           "detail": "stored" if ok else "not in the bag"}}
    ex._send_safe = _send
    ex.settle = lambda: obs(pc=True, bag=ex._bag_now)
    ex._bag_now = {"SILPH_SCOPE": 1, "S_S_TICKET": 1, "FULL_RESTORE": 6}
    return ex


# ---- the room test is the FIXTURE, not the map's name -------------------
ck("a room with a reachable PC is a room with a PC",
   E.Executor._pc_here(obs(pc=True)))
ck("no PC fixture, no PC", not E.Executor._pc_here(obs(pc=False)))
ck("a PC no walk reaches is not one you can use",
   not E.Executor._pc_here(obs(pc=True, reachable=False)))
ck("a PC is no use with a menu up",
   not E.Executor._pc_here(obs(pc=True, mode="ui")))

# ---- the order fires where the PC is, and nowhere else ------------------
ex = fresh()
ex._stow = ["SILPH_SCOPE", "S_S_TICKET"]
ex._stow_at_pc(obs(pc=False), {"id": "x"})
ck("four floors down a dungeon nothing is stored and the order stands",
   ex.sent == [] and ex._stow == ["SILPH_SCOPE", "S_S_TICKET"])

ex._stow_at_pc(obs(pc=True), {"id": "x"})
ck("at a PC both go in, in the order the model wrote them",
   [i for _, k in ex.sent for i in [k.get("item")]]
   == ["SILPH_SCOPE", "S_S_TICKET"])
ck("...by the op that destroys nothing",
   all(o == "store_item" for o, _ in ex.sent))
ck("...and a carried-out order is not carried out twice", ex._stow == [])

# ---- what the PC would not take is still waiting ------------------------
ex2 = fresh()
ex2._stow = ["SILPH_SCOPE", "TM_DIG"]
ex2._bag_now = {"SILPH_SCOPE": 1, "TM_DIG": 1}
ex2._send_safe = lambda op, **kw: (
    ex2.sent.append((op, kw)) or
    {"result": {"ok": kw.get("item") != "TM_DIG",
                "detail": "the PC would not take it"}})
ex2._stow_at_pc(obs(pc=True, bag={"SILPH_SCOPE": 1, "TM_DIG": 1}), {"id": "x"})
ck("a refused item stays on the order and the rest still went",
   ex2._stow == ["TM_DIG"] and len(ex2.sent) == 2)

# ---- an order only ever moves what the model named ----------------------
ex3 = fresh()
ex3._stow = ["SILPH_SCOPE"]
ex3._stow_at_pc(obs(pc=True), {"id": "x"})
ck("the harness stores the named thing and NOTHING else",
   [k.get("item") for _, k in ex3.sent] == ["SILPH_SCOPE"])
ex4 = fresh()
ex4._stow_at_pc(obs(pc=True), {"id": "x"})
ck("no order, no automatic tidying of anyone's bag", ex4.sent == [])
ex5 = fresh()
ex5._stow = ["BICYCLE"]          # named, but not carried today
ex5._stow_at_pc(obs(pc=True), {"id": "x"})
ck("a thing not in the bag is not chased", ex5.sent == [])

# ---- the words -----------------------------------------------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("the op is in the vocabulary the page hands over",
   '{"op":"store_later","items":["SILPH_SCOPE","S_S_TICKET"]}' in SRC)
ck("...said to cost no round when it fires",
   "NO round spent on it" in SRC)
ck("a pending order rides the bag on every page",
   "STANDING ORDER YOU LEFT:" in SRC and "to cancel it" in SRC)
ck("the no-PC-here branch offers deciding it anyway",
   "You can still DECIDE it here: " in SRC)
ck("writing the order is never counted as the world moving",
   "NOTHING HAS HAPPENED " in SRC)
ck("...and re-writing the same list says so",
   "that is ALREADY the standing order" in SRC)
ck("the deed runs at the round boundary",
   "start = self._stow_at_pc(start, sg) or start" in SRC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
