#!/usr/bin/env python3
"""Standing in a Center with a party that is not party_healthy, the harness
asks whether to heal, for no round, and does only what the answer says.

A first cut of this healed on its own (2026-09-14, for an hour), on the
reading that there is never a reason not to. The user's rule is that the
harness does not decide for the model, it puts the facts in front of it:
"we cant force it to heal via the harness though, it has to decide to do
after maybe a little encouragement". So it is the TM and stone questions'
shape: the facts of the room (who is hurt, what the counter does, what it
costs, what it changes), a small answer space, one model call, no round.
Before either existed the run walked into the Mt Moon Center with Spike
at 0/40 hp, pressed nothing, and walked back out to fight on Route 4
with two Pokemon.

Asked once per visit: whatever the answer, the question is not put again
until the party has left the room and come back.
"""
from __future__ import annotations
import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402
import brock_probe                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HURT = {"mode": "overworld",
        "map": {"id": "MT_MOON_POKECENTER", "region": "0,3",
                "objects": [{"name": "MTMOONPOKECENTER_NURSE", "kind": "person",
                             "reachable": True, "x": 3, "y": 1},
                            {"name": "PC", "reachable": True, "x": 13, "y": 1}]},
        "party": [{"species": "NIDORAN_M", "nickname": "Spike", "level": 15, "hp": 0, "max_hp": 40},
                  {"species": "CHARMANDER", "nickname": "Ignis", "level": 22, "hp": 44, "max_hp": 62},
                  {"species": "PIKACHU", "nickname": "Sparky", "level": 12, "hp": 33, "max_hp": 33}]}
WELL = copy.deepcopy(HURT)
for m in WELL["party"]:
    m["hp"] = m["max_hp"]
SG = {"id": "reach_cerulean_city", "goal_text": "Walk from Route 24 into Cerulean City."}

asked = []
def fake(answer='{"why":"Spike cannot fight at 0 hp","heal":true}', reply_ok=True, after=WELL):
    o = types.SimpleNamespace(sent=[], logged=[], model="stub")
    o._send_safe = lambda op, **kw: (o.sent.append((op, kw)) or
                                     {"result": {"ok": reply_ok, "detail": "healed" if reply_ok else "nobody at the counter"}})
    o.settle = lambda: after
    o.log = lambda kind, **kw: o.logged.append((kind, kw))
    o._where = E.Executor._where
    o._nurse_here = E.Executor._nurse_here
    o.HEAL_SYS = E.Executor.HEAL_SYS
    o._ask_heal = types.MethodType(E.Executor._ask_heal, o)
    brock_probe.chat = lambda msgs, model, **kw: (asked.append(msgs) or answer)
    return o

# ---- the question --------------------------------------------------------------
o = fake(); asked.clear()
out = o._ask_heal(HURT, SG)
ck("a hurt party beside a nurse is ASKED about, once", len(asked) == 1, len(asked))
u = asked[0][-1]["content"]; sysm = asked[0][0]["content"]
ck("...with who is hurt, as the screen shows it",
   "Spike L15 0/40 hp — FAINTED" in u and "Ignis L22 44/62 hp" in u, u)
ck("...and not the ones at full health", "Sparky" not in u)
ck("...what the counter does and what it changes",
   "costs nothing" in u and "wake at" in u and "cannot fight until" in sysm)
ck("...and what the run is in the middle of", SG["goal_text"] in u)
ck("...and that no round is spent either way", "No round is spent" in u)
ck("the harness recommends nothing in the question",
   not any(w in (u + sysm).lower() for w in ("you should", "heal now", "go heal", "you must")), u)
ck("saying no is offered as a real answer", "Saying no is a real answer" in sysm)

# ---- yes: the deed follows, for no round ----------------------------------------
ck("a yes is carried out with one op", o.sent == [("heal", {})], o.sent)
ck("...and the observation handed back is the healed one", E.pred_holds({"party_healthy": True}, out))
ck("...and the answer and its reason are on record",
   any(k == "heal_asked" and kw.get("heal") is True and "0 hp" in kw.get("why", "") for k, kw in o.logged)
   and any(k == "heal_done" and kw.get("ok") for k, kw in o.logged), o.logged)

# ---- no: nothing happens, and the answer stands for the visit ------------------
o = fake(answer='{"why":"I will heal after the gym, the Center is next door","heal":false}'); asked.clear()
o._ask_heal(HURT, SG)
ck("a no sends nothing", o.sent == [])
ck("...and is on record with its reason",
   any(k == "heal_asked" and kw.get("heal") is False and "after the gym" in kw.get("why", "") for k, kw in o.logged))
o._ask_heal(HURT, SG)
ck("the question is not put again the same visit", len(asked) == 1, len(asked))
OUTSIDE = {**HURT, "map": {"id": "ROUTE_4", "region": "4,4", "objects": []}}
o._ask_heal(OUTSIDE, SG); o._ask_heal(HURT, SG)
ck("...until the party has left the room and come back", len(asked) == 2, len(asked))

# ---- what is never asked ---------------------------------------------------------
o = fake(); asked.clear()
o._ask_heal(WELL, SG); ck("a healthy party: no question", asked == [] and o.sent == [])
o._ask_heal({**HURT, "map": {**HURT["map"], "objects": [{"name": "PC", "reachable": True}]}}, SG)
ck("no nurse in the room: no question", asked == [])
o._ask_heal({**HURT, "mode": "dialog"}, SG); ck("not in the overworld: no question", asked == [])
o._ask_heal({**HURT, "map": {**HURT["map"], "objects": [{"name": "MTMOONPOKECENTER_NURSE", "reachable": False}]}}, SG)
ck("a nurse no walk reaches: no question", asked == [])

# ---- an unreadable answer is a no -----------------------------------------------
o = fake(answer="sure, heal"); asked.clear()
o._ask_heal(HURT, SG)
ck("an answer that is not JSON heals nothing", o.sent == [] and len(asked) == 1)

# ---- the party-healthy test is the plan predicate's own --------------------------
o = fake(); asked.clear()
STATUS = copy.deepcopy(WELL); STATUS["party"][1]["status"] = "PSN"
o._ask_heal(STATUS, SG)
ck("full hp with a status is still not healthy: asked, and the status is named",
   len(asked) == 1 and "PSN" in asked[0][-1]["content"])

# ---- it sits at the round boundary beside the bag standing order -----------------
src = (ROOT / "planner" / "executor.py").read_text()
i_stow = src.index("start = self._stow_at_pc(start, sg) or start")
i_heal = src.index("start = self._ask_heal(start, sg) or start")
i_teach = src.index("start = self._ask_teach(start, sg) or start")
ck("it runs at the round boundary, between the bag order and the TM question",
   i_stow < i_heal < i_teach)
ck("nothing heals without an answer", "_heal_here" not in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
